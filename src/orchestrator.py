from __future__ import annotations
import logging
import os
import re
import tempfile

from src.schemas.models import (
    PipelineState, PipelineContext, FinalOutput,
    RepoAnalysisResult, DockerfileSpec, BuildResult, TestResult, EnvVarSpec,
)
from src.agents.repo_analysis_agent import RepoAnalysisAgent
from src.agents.dockerfile_agent import DockerfileAgent
from src.agents.build_test_agent import BuildTestAgent
from src.model.client import ModelClient
from src import config

logger = logging.getLogger(__name__)


def is_secrets_only_error(test_result: TestResult) -> bool:
    """Check if the test failure is only due to missing secrets."""
    if test_result.mcp_handshake_ok:
        return False
    if test_result.missing_secrets:
        return True
    # Check startup log for secrets-related errors only
    log = test_result.startup_log.lower()
    secrets_keywords = ["api_key", "api key", "token", "secret", "unauthorized", "authentication"]
    code_keywords = ["syntaxerror", "importerror", "modulenotfounderror", "no such file", "permission denied", "segfault"]
    has_secrets_issue = any(kw in log for kw in secrets_keywords)
    has_code_issue = any(kw in log for kw in code_keywords)
    return has_secrets_issue and not has_code_issue


def is_code_error(test_result: TestResult) -> bool:
    """Check if test failure is due to a code/config error (not secrets)."""
    if not test_result.container_started:
        return True
    log = test_result.startup_log.lower()
    code_keywords = ["syntaxerror", "importerror", "modulenotfounderror", "no such file",
                     "permission denied", "segfault", "exec format error", "not found"]
    return any(kw in log for kw in code_keywords)


class Orchestrator:
    def __init__(
        self,
        model_client: ModelClient | None = None,
        max_fix_attempts: int | None = None,
        skip_test: bool = False,
    ) -> None:
        self.model_client = model_client or ModelClient()
        self.max_fix_attempts = max_fix_attempts or config.MAX_FIX_ATTEMPTS
        self.skip_test = skip_test

        self.repo_analysis_agent = RepoAnalysisAgent(model_client=self.model_client)
        self.dockerfile_agent = DockerfileAgent(model_client=self.model_client)
        self.build_test_agent = BuildTestAgent()

    def run(self, repo_path: str, output_dir: str = "./output") -> FinalOutput:
        work_dir = tempfile.mkdtemp(prefix="mcp-auto-installer-")
        ctx = PipelineContext(
            repo_path=os.path.abspath(repo_path),
            work_dir=work_dir,
            max_fix_attempts=self.max_fix_attempts,
        )

        try:
            return self._execute_pipeline(ctx, output_dir)
        except Exception as e:
            logger.exception("Pipeline failed with exception")
            return FinalOutput(
                success=False,
                repo_path=ctx.repo_path,
                dockerfile_content=ctx.dockerfile_spec.dockerfile_content if ctx.dockerfile_spec else "",
                env_template="",
                image_tag="",
                transport_type="unknown",
                required_secrets=[],
                mcp_handshake_tested=False,
                startup_command="",
                notes=[f"Pipeline crashed: {e}"],
            )

    def _execute_pipeline(self, ctx: PipelineContext, output_dir: str) -> FinalOutput:
        # Stage 1: Repo Analysis
        ctx.state = PipelineState.REPO_ANALYSIS
        logger.info("=== Stage: REPO_ANALYSIS ===")
        ctx.repo_analysis = self.repo_analysis_agent.run(ctx.repo_path)

        if ctx.repo_analysis.confidence < 0.3:
            ctx.state = PipelineState.FAILED
            return self._assemble_output(ctx, success=False,
                                         notes=["Repo analysis confidence too low: "
                                                 f"{ctx.repo_analysis.confidence}"])

        # Stage 2: Dockerfile Generation
        ctx.state = PipelineState.DOCKERFILE_GEN
        logger.info("=== Stage: DOCKERFILE_GEN ===")
        ctx.dockerfile_spec = self.dockerfile_agent.generate(
            ctx.repo_analysis, work_dir=ctx.work_dir,
        )

        if self.skip_test:
            ctx.state = PipelineState.DONE
            output = self._assemble_output(ctx, success=True,
                                           notes=["Test phase skipped by user"])
            self._write_output_files(output, output_dir)
            return output

        # Stage 3+: Build-Test-Fix Loop
        while ctx.fix_attempts <= ctx.max_fix_attempts:
            ctx.state = PipelineState.BUILD_TEST
            logger.info("=== Stage: BUILD_TEST (attempt %d/%d) ===",
                        ctx.fix_attempts, ctx.max_fix_attempts)

            ctx.build_result, ctx.test_result = self.build_test_agent.run(
                ctx.dockerfile_spec, ctx.repo_analysis, work_dir=ctx.work_dir,
            )

            # Success path
            if ctx.build_result.success and ctx.test_result.mcp_handshake_ok:
                ctx.state = PipelineState.DONE
                output = self._assemble_output(ctx, success=True)
                self._write_output_files(output, output_dir)
                return output

            # Secrets-only failure — treat as success with warning
            if ctx.build_result.success and is_secrets_only_error(ctx.test_result):
                ctx.state = PipelineState.DONE
                output = self._assemble_output(
                    ctx, success=True,
                    notes=["Build succeeded but MCP handshake failed — likely needs real secrets to run"],
                )
                self._write_output_files(output, output_dir)
                return output

            # Code/build error — try to fix
            if not ctx.build_result.success or is_code_error(ctx.test_result):
                ctx.fix_attempts += 1
                error_msg = ctx.build_result.error_summary or ctx.test_result.error_summary or "Unknown error"
                ctx.error_history.append(error_msg)

                if ctx.fix_attempts > ctx.max_fix_attempts:
                    break

                ctx.state = PipelineState.FIXING
                logger.info("=== Stage: FIXING (attempt %d/%d) ===",
                            ctx.fix_attempts, ctx.max_fix_attempts)
                ctx.dockerfile_spec = self.dockerfile_agent.fix(
                    ctx.repo_analysis,
                    build_result=ctx.build_result,
                    test_result=ctx.test_result,
                    previous_dockerfile=ctx.dockerfile_spec.dockerfile_content,
                )
                # Write updated Dockerfile
                dockerfile_path = os.path.join(ctx.work_dir, "Dockerfile")
                with open(dockerfile_path, "w") as f:
                    f.write(ctx.dockerfile_spec.dockerfile_content)
                continue

            # Unknown failure — increment and try fix
            ctx.fix_attempts += 1
            if ctx.fix_attempts > ctx.max_fix_attempts:
                break

        ctx.state = PipelineState.FAILED
        output = self._assemble_output(
            ctx, success=False,
            notes=[f"Max fix attempts ({ctx.max_fix_attempts}) reached. Errors: {ctx.error_history}"],
        )
        self._write_output_files(output, output_dir)
        return output

    def _assemble_output(
        self,
        ctx: PipelineContext,
        success: bool,
        notes: list[str] | None = None,
    ) -> FinalOutput:
        all_notes = list(notes or [])
        if ctx.repo_analysis and ctx.repo_analysis.notes:
            all_notes.extend(ctx.repo_analysis.notes)

        image_tag = ctx.build_result.image_tag if ctx.build_result else ""
        transport = ctx.repo_analysis.transport_type if ctx.repo_analysis else "unknown"

        # Build docker run command
        startup_parts = ["docker", "run"]
        if ctx.dockerfile_spec:
            for var in ctx.dockerfile_spec.env_vars_to_inject:
                startup_parts.append(f"-e {var}=${{var}}")
            for port in ctx.dockerfile_spec.exposed_ports:
                startup_parts.append(f"-p {port}:{port}")
        if transport == "stdio":
            startup_parts.append("-i")
        startup_parts.append(image_tag)
        startup_command = " ".join(startup_parts)

        required_secrets = []
        if ctx.repo_analysis:
            required_secrets = ctx.repo_analysis.required_env_vars

        return FinalOutput(
            success=success,
            repo_path=ctx.repo_path,
            dockerfile_content=ctx.dockerfile_spec.dockerfile_content if ctx.dockerfile_spec else "",
            env_template=ctx.repo_analysis.env_file_template if ctx.repo_analysis else "",
            image_tag=image_tag,
            transport_type=transport,
            required_secrets=required_secrets,
            mcp_handshake_tested=bool(ctx.test_result and ctx.test_result.mcp_handshake_ok),
            startup_command=startup_command,
            notes=all_notes,
        )

    def _write_output_files(self, output: FinalOutput, output_dir: str) -> None:
        os.makedirs(output_dir, exist_ok=True)

        # Dockerfile
        dockerfile_path = os.path.join(output_dir, "Dockerfile")
        with open(dockerfile_path, "w") as f:
            f.write(output.dockerfile_content)
        logger.info("Wrote %s", dockerfile_path)

        # .env.example
        env_path = os.path.join(output_dir, ".env.example")
        with open(env_path, "w") as f:
            f.write(output.env_template)
        logger.info("Wrote %s", env_path)

        # build-report.json
        report_path = os.path.join(output_dir, "build-report.json")
        with open(report_path, "w") as f:
            f.write(output.model_dump_json(indent=2))
        logger.info("Wrote %s", report_path)

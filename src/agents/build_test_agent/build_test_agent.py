from __future__ import annotations
import json
import logging
import os
import re

from src.schemas.models import (
    BuildResult, TestResult, DockerfileSpec, RepoAnalysisResult,
)
from src.tools.docker_tools import (
    build_image, run_container, get_container_logs,
    stop_and_remove_container, send_mcp_initialize,
)
from src import config

logger = logging.getLogger(__name__)

# Patterns that indicate secrets-only failure
SECRETS_ERROR_PATTERNS = [
    r"(?i)api.?key",
    r"(?i)missing.*(?:token|secret|key|credential)",
    r"(?i)unauthorized",
    r"(?i)authentication.*(?:failed|required|error)",
    r"(?i)invalid.*(?:token|key)",
    r"(?i)OPENAI_API_KEY",
    r"(?i)ANTHROPIC_API_KEY",
    r"(?i)DATABASE_URL",
]


class BuildTestAgent:
    def __init__(self) -> None:
        self.agent_id = "build-test-agent"
        self.max_round = 8
        self.tool_registry = {
            "build_image": build_image,
            "run_container": run_container,
            "get_container_logs": get_container_logs,
            "send_mcp_initialize": send_mcp_initialize,
            "stop_and_remove_container": stop_and_remove_container,
        }

    def run(
        self,
        dockerfile_spec: DockerfileSpec,
        repo_analysis: RepoAnalysisResult,
        work_dir: str = "",
    ) -> tuple[BuildResult, TestResult]:
        context_path = work_dir or repo_analysis.repo_path
        dockerfile_path = os.path.join(context_path, "Dockerfile")

        # Ensure Dockerfile exists on disk
        if not os.path.isfile(dockerfile_path):
            with open(dockerfile_path, "w") as f:
                f.write(dockerfile_spec.dockerfile_content)

        image_tag = f"mcp-auto-install-{os.path.basename(repo_analysis.repo_path).lower()}:latest"

        # Phase 1: Build
        logger.info("[%s] Building image %s from %s", self.agent_id, image_tag, context_path)
        build_result = build_image(
            context_path=context_path,
            dockerfile_path="Dockerfile",
            tag=image_tag,
            timeout=config.DOCKER_BUILD_TIMEOUT,
        )

        if not build_result.success:
            logger.warning("[%s] Build failed: %s", self.agent_id, build_result.error_summary)
            return build_result, TestResult(
                container_started=False,
                startup_log="",
                mcp_handshake_ok=False,
                error_summary=f"Build failed: {build_result.error_summary}",
                missing_secrets=[],
            )

        # Phase 2: Test
        logger.info("[%s] Build succeeded, starting container...", self.agent_id)
        container_id = None
        try:
            # Prepare env vars (use empty placeholders for secrets)
            env_vars = {}
            for var_name in dockerfile_spec.env_vars_to_inject:
                env_vars[var_name] = os.environ.get(var_name, "placeholder")

            # Prepare ports
            ports = {}
            for port in dockerfile_spec.exposed_ports:
                ports[f"{port}/tcp"] = port

            container_id = run_container(
                image_tag=image_tag,
                env_vars=env_vars,
                ports=ports,
                timeout=config.CONTAINER_STARTUP_TIMEOUT,
            )

            # Get startup logs
            startup_log = get_container_logs(container_id, tail=100)
            logger.info("[%s] Container started, got %d bytes of logs", self.agent_id, len(startup_log))

            # Check for secrets-related errors in logs
            missing_secrets = self._detect_missing_secrets(startup_log)

            # Phase 3: MCP Handshake
            transport = dockerfile_spec.expected_transport
            mcp_handshake_ok = False

            if transport in ("sse", "streamable-http"):
                port = dockerfile_spec.exposed_ports[0] if dockerfile_spec.exposed_ports else 8080
                target = f"http://localhost:{port}/mcp"
                response = send_mcp_initialize(target, transport)
            else:
                # stdio transport
                response = send_mcp_initialize(container_id, "stdio")

            mcp_handshake_ok = self._validate_mcp_response(response)
            logger.info("[%s] MCP handshake result: %s", self.agent_id, mcp_handshake_ok)

            error_summary = None
            if not mcp_handshake_ok:
                error_summary = f"MCP handshake failed. Response: {response[:500]}"

            test_result = TestResult(
                container_started=True,
                startup_log=startup_log[:5000],
                mcp_handshake_ok=mcp_handshake_ok,
                error_summary=error_summary,
                missing_secrets=missing_secrets,
            )

        except Exception as e:
            logger.exception("[%s] Test phase failed", self.agent_id)
            test_result = TestResult(
                container_started=False,
                startup_log="",
                mcp_handshake_ok=False,
                error_summary=str(e),
                missing_secrets=[],
            )
        finally:
            # Cleanup
            if container_id:
                logger.info("[%s] Cleaning up container %s", self.agent_id, container_id[:12])
                stop_and_remove_container(container_id)

        return build_result, test_result

    def _detect_missing_secrets(self, log: str) -> list[str]:
        missing = []
        for pattern in SECRETS_ERROR_PATTERNS:
            if re.search(pattern, log):
                match = re.search(pattern, log)
                if match:
                    missing.append(match.group(0))
        return list(set(missing))

    def _validate_mcp_response(self, response: str) -> bool:
        try:
            data = json.loads(response)
            if isinstance(data, dict):
                if data.get("jsonrpc") == "2.0" and "result" in data:
                    result = data["result"]
                    if "protocolVersion" in result or "serverInfo" in result:
                        return True
            return False
        except (json.JSONDecodeError, Exception):
            return False

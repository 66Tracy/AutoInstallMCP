from __future__ import annotations
import json
import logging
import os
import re

from src.agents.base_agent import BaseAgent
from src.model.client import ModelClient
from src.schemas.models import DockerfileSpec, RepoAnalysisResult, BuildResult, TestResult
from src.tools.file_tools import read_file, write_file
from .prompts import SYSTEM_PROMPT, GENERATE_PROMPT_TEMPLATE, FIX_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


class DockerfileAgent(BaseAgent):
    def __init__(self, model_client: ModelClient | None = None) -> None:
        super().__init__(
            agent_id="dockerfile-agent",
            max_round=10,
            model_client=model_client,
        )
        self.register_tool("read_file", read_file)
        self.register_tool("write_file", write_file)
        self.work_dir: str = ""

    def init_msg_thread(self) -> None:
        self.msg_thread.messages.clear()
        self.add_system_message(SYSTEM_PROMPT)

    def get_available_tools(self) -> list[str]:
        return ["read_file", "write_file"]

    def generate(self, repo_analysis: RepoAnalysisResult, work_dir: str = "") -> DockerfileSpec:
        self.work_dir = work_dir
        self.init_msg_thread()
        self._current_round = 0

        user_msg = GENERATE_PROMPT_TEMPLATE.format(
            repo_analysis_json=repo_analysis.model_dump_json(indent=2),
            base_image=repo_analysis.base_image_suggestion,
            transport_type=repo_analysis.transport_type,
            exposed_port=repo_analysis.exposed_port or "N/A",
        )
        self.add_user_message(user_msg)

        return self._run_until_result(repo_analysis)

    def fix(
        self,
        repo_analysis: RepoAnalysisResult,
        build_result: BuildResult | None = None,
        test_result: TestResult | None = None,
        previous_dockerfile: str = "",
    ) -> DockerfileSpec:
        self.init_msg_thread()
        self._current_round = 0

        build_log_lines = (build_result.build_log if build_result else "").split("\n")
        build_log_tail = "\n".join(build_log_lines[-30:])

        user_msg = FIX_PROMPT_TEMPLATE.format(
            repo_analysis_json=repo_analysis.model_dump_json(indent=2),
            previous_dockerfile=previous_dockerfile,
            build_success=build_result.success if build_result else "N/A",
            build_error=build_result.error_summary if build_result else "N/A",
            build_log_tail=build_log_tail,
            container_started=test_result.container_started if test_result else "N/A",
            mcp_handshake_ok=test_result.mcp_handshake_ok if test_result else "N/A",
            test_error=test_result.error_summary if test_result else "N/A",
            startup_log=test_result.startup_log if test_result else "N/A",
        )
        self.add_user_message(user_msg)

        return self._run_until_result(repo_analysis)

    def _run_until_result(self, repo_analysis: RepoAnalysisResult) -> DockerfileSpec:
        while not self.should_stop():
            self._current_round += 1
            logger.info("[%s] Round %d/%d", self.agent_id, self._current_round, self.max_round)

            tools = self.get_tool_definitions() if self._current_round < self.max_round - 1 else None
            response = self.model_client.chat_completion(
                messages=self.msg_thread.get_messages(),
                tools=tools,
            )

            choice = response.choices[0]
            message = choice.message

            assistant_msg: dict = {"role": "assistant"}
            if message.content:
                assistant_msg["content"] = message.content
            if message.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ]
            self.msg_thread.messages.append(assistant_msg)

            if message.tool_calls:
                from src.data_structures import FunctionCallIntent
                for tool_call in message.tool_calls:
                    intent = FunctionCallIntent.from_tool_call(tool_call)
                    result = self.execute_tool(intent)
                    self.msg_thread.add_message(
                        "tool",
                        content=result,
                        tool_call_id=tool_call.id,
                    )
                if self._current_round >= self.max_round - 2:
                    self.add_user_message(
                        "You are running out of rounds. STOP using tools and output the "
                        "DockerfileSpec JSON NOW in ```json ... ``` code blocks."
                    )
                continue

            if message.content:
                parsed = self._parse_result(message.content, repo_analysis)
                if parsed:
                    # Write Dockerfile to disk if work_dir is set
                    if self.work_dir:
                        dockerfile_path = os.path.join(self.work_dir, "Dockerfile")
                        write_file(dockerfile_path, parsed.dockerfile_content)
                        logger.info("Wrote Dockerfile to %s", dockerfile_path)
                    return parsed

            self.add_user_message(
                "Please output the DockerfileSpec as JSON in ```json ... ``` code blocks."
            )

        logger.warning("[%s] Reached max rounds", self.agent_id)
        return self._fallback_result(repo_analysis)

    def _parse_result(self, content: str, repo_analysis: RepoAnalysisResult) -> DockerfileSpec | None:
        json_match = re.search(r"```json\s*\n?(.*?)```", content, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return DockerfileSpec(**data)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Failed to parse JSON block: %s", e)

        try:
            start = content.index("{")
            end = content.rindex("}") + 1
            data = json.loads(content[start:end])
            return DockerfileSpec(**data)
        except (ValueError, json.JSONDecodeError, Exception):
            pass

        return None

    def _fallback_result(self, repo_analysis: RepoAnalysisResult) -> DockerfileSpec:
        return DockerfileSpec(
            dockerfile_content=f"FROM {repo_analysis.base_image_suggestion}\nCOPY . /app\nWORKDIR /app\n",
            env_vars_to_inject=[],
            expected_transport=repo_analysis.transport_type,
            exposed_ports=[repo_analysis.exposed_port] if repo_analysis.exposed_port else [],
            entrypoint=["echo", "Dockerfile generation failed"],
            notes=["Fallback Dockerfile - agent could not produce valid output"],
        )

from __future__ import annotations
import json
import logging
import re

from src.agents.base_agent import BaseAgent
from src.model.client import ModelClient
from src.schemas.models import RepoAnalysisResult
from src.tools.file_tools import list_directory_tree, read_file, search_files, search_in_files
from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


class RepoAnalysisAgent(BaseAgent):
    def __init__(self, model_client: ModelClient | None = None) -> None:
        super().__init__(
            agent_id="repo-analysis-agent",
            max_round=15,
            model_client=model_client,
        )
        self.register_tool("list_directory_tree", list_directory_tree)
        self.register_tool("read_file", read_file)
        self.register_tool("search_files", search_files)
        self.register_tool("search_in_files", search_in_files)

    def init_msg_thread(self) -> None:
        self.add_system_message(SYSTEM_PROMPT)

    def get_available_tools(self) -> list[str]:
        return ["list_directory_tree", "read_file", "search_files", "search_in_files"]

    def run(self, repo_path: str) -> RepoAnalysisResult:
        self.init_msg_thread()
        self._current_round = 0

        user_msg = USER_PROMPT_TEMPLATE.format(repo_path=repo_path)
        self.add_user_message(user_msg)

        while not self.should_stop():
            self._current_round += 1
            logger.info("[%s] Round %d/%d", self.agent_id, self._current_round, self.max_round)

            # Stop offering tools near the end to force final output
            tools = self.get_tool_definitions() if self._current_round < self.max_round - 1 else None
            response = self.model_client.chat_completion(
                messages=self.msg_thread.get_messages(),
                tools=tools,
            )

            choice = response.choices[0]
            message = choice.message

            # Add assistant message to thread
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

            # If there are tool calls, execute them
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
                # When nearing max rounds, force the agent to produce output
                if self._current_round >= self.max_round - 2:
                    self.add_user_message(
                        "You are running out of rounds. STOP using tools and produce your "
                        "final RepoAnalysisResult JSON NOW in ```json ... ``` code blocks."
                    )
                continue

            # No tool calls — try to parse the final response
            if message.content:
                parsed = self._parse_result(message.content, repo_path)
                if parsed:
                    return parsed

            # If parsing failed, ask for JSON
            self.add_user_message(
                "Please output your analysis as a JSON object in ```json ... ``` code blocks, "
                "matching the RepoAnalysisResult schema exactly."
            )

        logger.warning("[%s] Reached max rounds", self.agent_id)
        return self._fallback_result(repo_path)

    def _parse_result(self, content: str, repo_path: str) -> RepoAnalysisResult | None:
        # Try to extract JSON from ```json ... ``` blocks
        json_match = re.search(r"```json\s*\n?(.*?)```", content, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                data["repo_path"] = repo_path
                return RepoAnalysisResult(**data)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Failed to parse JSON block: %s", e)

        # Try to find raw JSON object
        try:
            start = content.index("{")
            end = content.rindex("}") + 1
            data = json.loads(content[start:end])
            data["repo_path"] = repo_path
            return RepoAnalysisResult(**data)
        except (ValueError, json.JSONDecodeError, Exception):
            pass

        return None

    def _fallback_result(self, repo_path: str) -> RepoAnalysisResult:
        return RepoAnalysisResult(
            repo_path=repo_path,
            language="unknown",
            package_manager="unknown",
            entry_point="unknown",
            install_commands=[],
            config_files_found=[],
            readme_summary="Analysis could not be completed",
            base_image_suggestion="ubuntu:22.04",
            transport_type="unknown",
            extra_system_deps=[],
            required_env_vars=[],
            optional_env_vars=[],
            env_file_template="",
            secrets_risk="high",
            confidence=0.0,
            notes=["Agent reached max rounds without producing a valid result"],
        )

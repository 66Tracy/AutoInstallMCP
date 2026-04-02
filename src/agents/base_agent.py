from __future__ import annotations
import inspect
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

from src.data_structures import MessageThread, FunctionCallIntent
from src.model.client import ModelClient

logger = logging.getLogger(__name__)


def _python_type_to_json_schema(annotation) -> dict:
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {"type": "string"}
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        args = getattr(annotation, "__args__", (Any,))
        return {"type": "array", "items": _python_type_to_json_schema(args[0])}
    return {"type": "string"}


class BaseAgent(ABC):
    def __init__(
        self,
        agent_id: str,
        max_round: int = 10,
        model_client: ModelClient | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.max_round = max_round
        self.msg_thread = MessageThread()
        self.model_client = model_client or ModelClient()
        self.tool_registry: dict[str, Callable] = {}
        self._current_round = 0

    def register_tool(self, name: str, func: Callable) -> None:
        self.tool_registry[name] = func

    def add_system_message(self, msg: str) -> None:
        self.msg_thread.add_message("system", msg)

    def add_user_message(self, msg: str) -> None:
        self.msg_thread.add_message("user", msg)

    def should_stop(self) -> bool:
        return self._current_round >= self.max_round

    def execute_tool(self, call: FunctionCallIntent, max_result_chars: int = 8000) -> str:
        func = self.tool_registry.get(call.name)
        if func is None:
            return json.dumps({"error": f"Unknown tool: {call.name}"})
        try:
            result = func(**call.arguments)
            if not isinstance(result, str):
                result = json.dumps(result, default=str)
            if len(result) > max_result_chars:
                result = result[:max_result_chars] + f"\n... [truncated, {len(result)} total chars]"
            return result
        except Exception as e:
            logger.exception("Tool %s failed", call.name)
            return json.dumps({"error": str(e)})

    def get_tool_definitions(self) -> list[dict]:
        definitions = []
        for name, func in self.tool_registry.items():
            sig = inspect.signature(func)
            doc = inspect.getdoc(func) or f"Tool: {name}"
            properties = {}
            required = []
            for pname, param in sig.parameters.items():
                prop = _python_type_to_json_schema(param.annotation)
                if param.default is inspect.Parameter.empty:
                    required.append(pname)
                else:
                    prop["default"] = param.default
                properties[pname] = prop
            definitions.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": doc,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            })
        return definitions

    def run(self, input_data: Any = None) -> Any:
        self.init_msg_thread()
        self._current_round = 0

        while not self.should_stop():
            self._current_round += 1
            logger.info("[%s] Round %d/%d", self.agent_id, self._current_round, self.max_round)

            tools = self.get_tool_definitions() or None
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

            # If no tool calls, the agent is done
            if not message.tool_calls:
                return message.content

            # Execute tool calls
            for tool_call in message.tool_calls:
                intent = FunctionCallIntent.from_tool_call(tool_call)
                result = self.execute_tool(intent)
                self.msg_thread.add_message(
                    "tool",
                    content=result,
                    tool_call_id=tool_call.id,
                )

        logger.warning("[%s] Reached max rounds (%d)", self.agent_id, self.max_round)
        return None

    @abstractmethod
    def init_msg_thread(self) -> None:
        ...

    @abstractmethod
    def get_available_tools(self) -> list[str]:
        ...

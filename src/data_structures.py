from __future__ import annotations
import json


class MessageThread:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def add_message(self, role: str, content: str | None = None, **kwargs) -> None:
        msg: dict = {"role": role}
        if content is not None:
            msg["content"] = content
        msg.update(kwargs)
        self.messages.append(msg)

    def get_messages(self) -> list[dict]:
        return list(self.messages)

    def __len__(self) -> int:
        return len(self.messages)


class FunctionCallIntent:
    def __init__(self, name: str, arguments: dict, call_id: str = "") -> None:
        self.name = name
        self.arguments = arguments
        self.call_id = call_id

    @classmethod
    def from_tool_call(cls, tool_call) -> FunctionCallIntent:
        args = tool_call.function.arguments
        if isinstance(args, str):
            args = json.loads(args)
        return cls(
            name=tool_call.function.name,
            arguments=args,
            call_id=tool_call.id,
        )

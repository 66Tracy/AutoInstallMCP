from __future__ import annotations
import logging
from openai import OpenAI, BadRequestError
from src import config

logger = logging.getLogger(__name__)


class ModelClient:
    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL,
        )
        self.default_model = config.LLM_MODEL

    def chat_completion(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ):
        kwargs: dict = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature if temperature is not None else config.LLM_TEMPERATURE,
            "max_tokens": max_tokens or config.LLM_MAX_TOKENS,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        logger.debug("LLM request: model=%s, messages=%d, tools=%s",
                      kwargs["model"], len(messages), len(tools) if tools else 0)
        try:
            response = self.client.chat.completions.create(**kwargs)
            logger.debug("LLM response: finish_reason=%s", response.choices[0].finish_reason)
            return response
        except BadRequestError as e:
            if "context length" in str(e).lower() or "too many tokens" in str(e).lower():
                logger.warning("Context too long, trimming middle messages and retrying...")
                trimmed = self._trim_messages(messages)
                kwargs["messages"] = trimmed
                response = self.client.chat.completions.create(**kwargs)
                return response
            raise

    @staticmethod
    def _trim_messages(messages: list[dict]) -> list[dict]:
        """Keep system message + first 2 messages + last 6 messages."""
        if len(messages) <= 10:
            return messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        kept = system_msgs + non_system[:2] + non_system[-6:]
        return kept

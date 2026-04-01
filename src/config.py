import os
from dotenv import load_dotenv

load_dotenv()

LLM_API_KEY: str = os.environ.get("LLM_API_KEY", "")
LLM_MODEL: str = os.environ.get("LLM_MODEL", "gpt-4o")
LLM_BASE_URL: str | None = os.environ.get("LLM_BASE_URL") or None
LLM_TEMPERATURE: float = float(os.environ.get("LLM_TEMPERATURE", "0.2"))
LLM_MAX_TOKENS: int = int(os.environ.get("LLM_MAX_TOKENS", "4096"))
WORK_DIR: str = os.environ.get("WORK_DIR", "/tmp/mcp-auto-installer")
MAX_FIX_ATTEMPTS: int = int(os.environ.get("MAX_FIX_ATTEMPTS", "3"))
DOCKER_BUILD_TIMEOUT: int = int(os.environ.get("DOCKER_BUILD_TIMEOUT", "600"))
CONTAINER_STARTUP_TIMEOUT: int = int(os.environ.get("CONTAINER_STARTUP_TIMEOUT", "30"))
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

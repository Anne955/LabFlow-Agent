from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PROVIDER = "fake"
DEFAULT_FAKE_MODEL = "fake-scripted"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com"
DEFAULT_OPENAI_MODEL = "gpt-4.1"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"

DEFAULT_MAX_STEPS = 8
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_NEW_TOKENS = 4096
DEFAULT_CONTEXT_BUDGET = 12_000
DEFAULT_TOOL_OUTPUT_LIMIT = 8_000

DOC_FILENAMES = (
    "AGENTS.md",
    "README.md",
    "pyproject.toml",
    "package.json",
    "pytest.ini",
    "tox.ini",
    "Makefile",
    "justfile",
)

IGNORED_DIRS = {
    ".git",
    ".pico",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
}

SAFE_SHELL_ENV_NAMES = {
    "PATH",
    "SystemRoot",
    "WINDIR",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
}

SECRET_NAME_HINTS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "AUTH",
    "CREDENTIAL",
)


def load_dotenv(start: Path) -> Path | None:
    """Load the first .env found from start upward without overriding existing env vars."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    candidates = [current, *current.parents]
    for directory in candidates:
        dotenv = directory / ".env"
        if dotenv.is_file():
            for line in dotenv.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
            return dotenv
    return None


def env_or(default: str, *names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def env_list(name: str) -> list[str]:
    value = os.environ.get(name, "")
    return [part.strip() for part in value.split(",") if part.strip()]


DEFAULT_RETRY_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY_MS = 500
DEFAULT_RETRY_MAX_DELAY_MS = 10_000


def load_retry_config():
    from .providers.retry import RetryConfig

    return RetryConfig(
        max_retries=int(env_or(str(DEFAULT_RETRY_MAX_RETRIES), "PICO_MAX_RETRIES")),
        base_delay_ms=int(env_or(str(DEFAULT_RETRY_BASE_DELAY_MS), "PICO_RETRY_BASE_DELAY_MS")),
        max_delay_ms=int(env_or(str(DEFAULT_RETRY_MAX_DELAY_MS), "PICO_RETRY_MAX_DELAY_MS")),
    )


def load_truncation_strategy():
    name = env_or("priority", "PICO_TRUNCATION_STRATEGY")
    if name == "smart":
        from .context_manager import SmartTruncation

        return SmartTruncation()
    from .context_manager import PriorityTruncation

    return PriorityTruncation()

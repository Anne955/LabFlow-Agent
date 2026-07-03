from __future__ import annotations

import os
import re
from collections.abc import Iterable

from .config import SAFE_SHELL_ENV_NAMES, SECRET_NAME_HINTS

_SECRET_VALUE_MIN_LENGTH = 8


def looks_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(hint in upper for hint in SECRET_NAME_HINTS)


def collect_secret_env_names(extra_names: Iterable[str] = ()) -> list[str]:
    names = set(extra_names)
    for name, value in os.environ.items():
        if value and looks_secret_name(name):
            names.add(name)
    return sorted(names)


def redact_text(text: str, secret_names: Iterable[str] = ()) -> str:
    redacted = text
    for name in secret_names:
        value = os.environ.get(name)
        if value and len(value) >= _SECRET_VALUE_MIN_LENGTH:
            redacted = redacted.replace(value, f"<redacted:{name}>")
    # Conservative fallback for common bearer/api-key shaped values.
    redacted = re.sub(r"\b(sk-[A-Za-z0-9_-]{12,})\b", "<redacted:secret>", redacted)
    redacted = re.sub(r"\b([A-Za-z0-9_=-]{32,})\b", redact_long_token, redacted)
    return redacted


def redact_long_token(match: re.Match[str]) -> str:
    token = match.group(1)
    if any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token):
        return "<redacted:token>"
    return token


def safe_shell_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if name in SAFE_SHELL_ENV_NAMES}

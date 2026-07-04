from __future__ import annotations

import warnings

warnings.warn(
    "pico.tool_registry is deprecated; import from pico.tools.registry instead.",
    DeprecationWarning,
    stacklevel=2,
)
from .tools.registry import build_labflow_tool_registry, build_tool_registry  # noqa: F401,E402

__all__ = ["build_labflow_tool_registry", "build_tool_registry"]

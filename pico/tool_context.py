from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tools import ToolResult


@dataclass
class ToolContext:
    root: Path
    path_resolver: Callable[[str], Path]
    shell_env_provider: Callable[[], dict[str, str]]
    depth: int = 0
    max_depth: int = 1
    spawn_delegate: Callable[[str, int], ToolResult] | None = None
    default_report_lang: str = "zh"

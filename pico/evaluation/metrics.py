from __future__ import annotations

from collections import Counter
from typing import Any


def aggregate_runs(reports: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(str(report.get("status", "unknown")) for report in reports)
    stop_reasons = Counter(str(report.get("stop_reason", "unknown")) for report in reports)
    total_tool_steps = sum(int(report.get("tool_steps", 0)) for report in reports)
    return {
        "total": len(reports),
        "statuses": dict(statuses),
        "stop_reasons": dict(stop_reasons),
        "tool_steps": total_tool_steps,
    }

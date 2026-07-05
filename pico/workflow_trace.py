from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .safety.guard import resolve_trace_path, sanitize_batch_id
from .task_state import now_iso


def load_trace_events(trace_path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not trace_path.is_file():
        return events
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def build_workflow_log(
    trace_path: Path, batch_id: str, run_id: str, session_id: str
) -> dict[str, Any]:
    safe_batch = sanitize_batch_id(batch_id)
    tool_events = []
    for event in load_trace_events(trace_path):
        if event.get("type") != "tool_finished":
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        result = payload.get("result", {})
        if not isinstance(result, dict):
            result = {}
        metadata = (
            result.get("metadata", {}) if isinstance(result.get("metadata", {}), dict) else {}
        )
        event_batch = str(metadata.get("batch_id") or safe_batch)
        tool_events.append(
            {
                "event_index": len(tool_events) + 1,
                "timestamp": event.get("created_at"),
                "run_id": run_id,
                "session_id": session_id,
                "batch_id": event_batch,
                "tool": payload.get("name"),
                "status": "ok" if result.get("ok") else "error",
                "error_code": result.get("error_code"),
                "input": payload.get("input", {}),
                "output_paths": result.get("affected_paths", []),
                "metadata": metadata,
                "duration_seconds": float(payload.get("duration_seconds") or 0.0),
            }
        )
    total_duration = sum(float(item.get("duration_seconds") or 0.0) for item in tool_events)
    return {
        "batch_id": safe_batch,
        "run_id": run_id,
        "session_id": session_id,
        "generated_at": now_iso(),
        "event_count": len(tool_events),
        "total_duration_seconds": total_duration,
        "events": tool_events,
    }


def write_workflow_log(root: Path, batch_id: str, log: dict[str, Any]) -> Path:
    path = resolve_trace_path(root, sanitize_batch_id(batch_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def build_run_summary(
    tool_summaries: list[dict[str, Any]],
    run_status: str,
    provider_metadata: dict[str, Any],
    prompt_metadata: dict[str, Any],
) -> dict[str, Any]:
    durations = [float(item.get("duration_seconds") or 0.0) for item in tool_summaries]
    return {
        "run_status": run_status,
        "tool_call_count": len(tool_summaries),
        "provider_call_count": int(
            provider_metadata.get("fake_call") or provider_metadata.get("calls") or 0
        )
        or None,
        "total_tool_duration_seconds": sum(durations),
        "context_budget_used": int(prompt_metadata.get("prompt_chars") or 0),
        "section_chars": prompt_metadata.get("section_chars", {}),
    }

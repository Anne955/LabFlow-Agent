from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_run_summary(trace_path: Path) -> dict | None:
    if not trace_path.is_file():
        return None
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "run_summary":
            return event.get("payload")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate run_summary metrics across batch workflow logs."
    )
    parser.add_argument(
        "traces_dir",
        help="Directory containing *_workflow_log.json or run trace.jsonl files",
    )
    args = parser.parse_args(argv)

    root = Path(args.traces_dir)
    files = sorted(root.glob("*.json"))
    header = (
        "batch_id,run_status,tool_call_count,provider_call_count,"
        "total_tool_duration_seconds,context_budget_used"
    )
    print(header)
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        batch_id = data.get("batch_id", path.stem)
        events = data.get("events", [])
        tool_count = len(events)
        duration = sum(float(e.get("duration_seconds") or 0.0) for e in events)
        print(f"{batch_id},-,{tool_count},-,{duration:.3f},-")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .task_state import TaskState, now_iso


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _quarantine(path: Path) -> None:
    """Rename a corrupt file aside so the next read starts clean. Never raises."""
    try:
        stamp = int(time.time() * 1000)
        path.rename(path.with_name(f"{path.stem}.corrupted.{stamp}{path.suffix}"))
    except OSError:
        pass


class SessionStore:
    def __init__(self, root: Path):
        self.root = root / ".pico" / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def save(self, session: dict[str, Any]) -> Path:
        session = dict(session)
        session.setdefault("created_at", now_iso())
        session["updated_at"] = now_iso()
        path = self.path_for(str(session["id"]))
        atomic_write_json(path, session)
        return path

    def load(self, session_id: str) -> dict[str, Any]:
        path = self.path_for(session_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _quarantine(path)
            return {"id": session_id, "history": [], "memory": {}}

    def latest(self) -> str | None:
        candidates = []
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            candidates.append((str(data.get("updated_at", "")), str(data.get("id", path.stem))))
        if not candidates:
            return None
        candidates.sort()
        return candidates[-1][1]


class RunStore:
    def __init__(self, root: Path):
        self.root = root / ".pico" / "runs"
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def start_run(self, task_state: TaskState) -> Path:
        directory = self.run_dir(task_state.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        self.write_task_state(task_state)
        return directory

    def write_task_state(self, task_state: TaskState) -> Path:
        path = self.run_dir(task_state.run_id) / "task_state.json"
        atomic_write_json(path, task_state.to_dict())
        return path

    def load_task_state(self, run_id: str) -> TaskState:
        path = self.run_dir(run_id) / "task_state.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return TaskState.from_dict(data)
        except (OSError, json.JSONDecodeError):
            _quarantine(path)
            return TaskState.create("recovered task")

    def append_trace(self, run_id: str, event: dict[str, Any]) -> Path:
        path = self.run_dir(run_id) / "trace.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return path

    def write_report(self, run_id: str, report: dict[str, Any]) -> Path:
        path = self.run_dir(run_id) / "report.json"
        atomic_write_json(path, report)
        return path

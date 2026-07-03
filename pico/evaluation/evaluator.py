from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class BenchmarkTask:
    id: str
    prompt: str
    category: str = "general"
    max_steps: int = 8
    expected_artifact: str | None = None


class BenchmarkEvaluator:
    def __init__(self, tasks: list[BenchmarkTask]):
        self.tasks = tasks

    @classmethod
    def from_file(cls, path: str | Path) -> "BenchmarkEvaluator":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        tasks = [BenchmarkTask(**item) for item in data.get("tasks", [])]
        return cls(tasks)

    def validate(self) -> list[str]:
        errors: list[str] = []
        seen: set[str] = set()
        for task in self.tasks:
            if not task.id:
                errors.append("task id is required")
            if task.id in seen:
                errors.append(f"duplicate task id: {task.id}")
            seen.add(task.id)
            if not task.prompt:
                errors.append(f"task {task.id} has empty prompt")
            if task.max_steps <= 0:
                errors.append(f"task {task.id} must have positive max_steps")
        return errors


def load_results(path: str | Path) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

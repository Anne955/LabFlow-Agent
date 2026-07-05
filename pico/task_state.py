from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class TaskState:
    run_id: str
    task_id: str
    user_request: str
    status: str = "running"
    attempts: int = 0
    tool_steps: int = 0
    last_tool: str | None = None
    stop_reason: str | None = None
    final_answer: str | None = None
    errors: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    @classmethod
    def create(cls, user_request: str) -> TaskState:
        return cls(run_id=new_id("run"), task_id=new_id("task"), user_request=user_request)

    def touch(self) -> None:
        self.updated_at = now_iso()

    def record_attempt(self) -> None:
        self.attempts += 1
        self.touch()

    def record_tool(self, name: str) -> None:
        self.tool_steps += 1
        self.last_tool = name
        self.touch()

    def finish_success(self, final_answer: str) -> None:
        self.status = "completed"
        self.stop_reason = "final_answer_returned"
        self.final_answer = final_answer
        self.touch()

    def finish_stopped(self, reason: str, final_answer: str | None = None) -> None:
        self.status = "stopped"
        self.stop_reason = reason
        self.final_answer = final_answer
        self.touch()

    def finish_failed(self, reason: str, error: str) -> None:
        self.status = "failed"
        self.stop_reason = reason
        self.errors.append(error)
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "user_request": self.user_request,
            "status": self.status,
            "attempts": self.attempts,
            "tool_steps": self.tool_steps,
            "last_tool": self.last_tool,
            "stop_reason": self.stop_reason,
            "final_answer": self.final_answer,
            "errors": self.errors,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskState:
        return cls(
            run_id=str(data["run_id"]),
            task_id=str(data["task_id"]),
            user_request=str(data.get("user_request", "")),
            status=str(data.get("status", "running")),
            attempts=int(data.get("attempts", 0)),
            tool_steps=int(data.get("tool_steps", 0)),
            last_tool=data.get("last_tool"),
            stop_reason=data.get("stop_reason"),
            final_answer=data.get("final_answer"),
            errors=list(data.get("errors", [])),
            created_at=str(data.get("created_at", now_iso())),
            updated_at=str(data.get("updated_at", now_iso())),
        )

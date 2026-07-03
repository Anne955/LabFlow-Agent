from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CheckpointState:
    workspace_fingerprint: str
    runtime_provider: str
    runtime_model: str


def evaluate_resume_state(expected: CheckpointState, actual: CheckpointState) -> str:
    if expected.workspace_fingerprint != actual.workspace_fingerprint:
        return "workspace_mismatch"
    if (expected.runtime_provider, expected.runtime_model) != (actual.runtime_provider, actual.runtime_model):
        return "runtime_mismatch"
    return "ok"

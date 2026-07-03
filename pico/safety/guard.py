from __future__ import annotations

import re
from pathlib import Path

from ..errors import SafetyViolationError

REGISTERED_SCRIPTS = {"normalize_csv.py"}
SAFE_BATCH_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def sanitize_batch_id(raw: str) -> str:
    batch_id = raw.strip()
    if not batch_id or not SAFE_BATCH_ID.match(batch_id):
        raise ValueError(f"invalid batch_id: {raw}")
    return batch_id


def resolve_workspace_path(root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {raw_path}") from exc
    return resolved_candidate


def assert_raw_data_readonly(root: Path, path: Path) -> None:
    rel = path.resolve().relative_to(root.resolve()).parts
    if len(rel) >= 2 and rel[0] == "data" and (rel[1] == "raw" or rel[1].startswith("batch_")):
        raise SafetyViolationError(f"raw data path is read-only: {path}")


def resolve_output_path(root: Path, batch_id: str, relative_name: str) -> Path:
    safe_batch = sanitize_batch_id(batch_id)
    base = (root / "outputs" / safe_batch).resolve()
    candidate = (base / relative_name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"output path escapes outputs/{safe_batch}: {relative_name}") from exc
    return candidate


def resolve_preprocessed_path(root: Path, batch_id: str, relative_name: str) -> Path:
    safe_batch = sanitize_batch_id(batch_id)
    base = (root / "outputs" / safe_batch / "preprocessed").resolve()
    candidate = (base / relative_name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(
            f"preprocessed path escapes outputs/{safe_batch}/preprocessed: {relative_name}"
        ) from exc
    return candidate


def resolve_report_path(root: Path, batch_id: str) -> Path:
    safe_batch = sanitize_batch_id(batch_id)
    return (root / "reports" / f"{safe_batch}_qc_report.md").resolve()


def resolve_trace_path(root: Path, batch_id: str) -> Path:
    safe_batch = sanitize_batch_id(batch_id)
    return (root / "traces" / f"{safe_batch}_workflow_log.json").resolve()


def resolve_registered_script(root: Path, script_name: str) -> Path:
    name = Path(script_name).name
    if name != script_name or name not in REGISTERED_SCRIPTS:
        raise ValueError(f"script is not registered: {script_name}")
    path = (root / "scripts" / name).resolve()
    scripts_root = (root / "scripts").resolve()
    try:
        path.relative_to(scripts_root)
    except ValueError as exc:
        raise ValueError(f"script path escapes scripts directory: {script_name}") from exc
    if not path.is_file():
        raise ValueError(f"registered script is missing: {script_name}")
    return path

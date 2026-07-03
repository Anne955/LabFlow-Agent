from __future__ import annotations

import csv
import json
import math
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from .safety.guard import (
    assert_raw_data_readonly,
    resolve_output_path,
    resolve_preprocessed_path,
    resolve_registered_script,
    resolve_report_path,
    resolve_trace_path,
    resolve_workspace_path,
    sanitize_batch_id,
)
from .tool_context import ToolContext
from .tools import ToolResult, relpath

REQUIRED_METADATA_FIELDS = ("sample_id", "method")
REQUIRED_SPECTRA_FIELDS = ("x", "intensity")
QC_COLUMNS = [
    "finding_id",
    "batch_id",
    "sample_id",
    "file",
    "check",
    "severity",
    "status",
    "message",
    "evidence",
]
MIN_SPECTRA_POINTS = 10
FILENAME_PATTERN = re.compile(r"^(?P<sample_id>.+)_(?P<method>[A-Za-z0-9-]+)\.csv$")


def tool_scan_experiment_dir(ctx: ToolContext, args: dict[str, object]) -> ToolResult:
    experiment_dir = ctx.path_resolver(str(args["experiment_dir"]))
    batch_id = sanitize_batch_id(str(args.get("batch_id") or experiment_dir.name))
    if not experiment_dir.exists():
        return ToolResult(False, f"experiment directory does not exist: {relpath(ctx, experiment_dir)}", error_code="not_found")
    if not experiment_dir.is_dir():
        return ToolResult(False, f"not a directory: {relpath(ctx, experiment_dir)}", error_code="not_directory")

    metadata_files = sorted([p for p in experiment_dir.iterdir() if p.name.lower() in {"metadata.csv", "metadata.xlsx"}])
    spectra_dir = experiment_dir / "spectra"
    spectra_files = sorted(spectra_dir.glob("*.csv")) if spectra_dir.is_dir() else []
    log_files = sorted([p for p in experiment_dir.iterdir() if p.name.lower() in {"instrument_log.txt", "instrument_log.log", "instrument_log.csv"}])
    other_files = sorted([p for p in experiment_dir.iterdir() if p.is_file() and p not in metadata_files and p not in log_files])
    suspicious = [p.name for p in spectra_files if not FILENAME_PATTERN.match(p.name)]
    missing = []
    if not metadata_files:
        missing.append("metadata.csv")
    if not spectra_dir.is_dir():
        missing.append("spectra/")

    by_suffix = Counter(p.suffix.lower() or "<none>" for p in experiment_dir.rglob("*") if p.is_file())
    metadata = {
        "batch_id": batch_id,
        "experiment_dir": relpath(ctx, experiment_dir),
        "metadata_path": relpath(ctx, metadata_files[0]) if metadata_files else None,
        "spectra_dir": relpath(ctx, spectra_dir) if spectra_dir.is_dir() else None,
        "instrument_log_path": relpath(ctx, log_files[0]) if log_files else None,
        "spectra_file_count": len(spectra_files),
        "other_file_count": len(other_files),
        "file_types": dict(sorted(by_suffix.items())),
        "suspicious_filenames": suspicious,
        "missing": missing,
    }
    text = [
        f"Batch: {batch_id}",
        f"Experiment directory: {metadata['experiment_dir']}",
        f"Metadata: {metadata['metadata_path'] or 'missing'}",
        f"Spectra files: {len(spectra_files)}",
        f"Instrument log: {metadata['instrument_log_path'] or 'not found'}",
        f"Suspicious filenames: {len(suspicious)}",
    ]
    if missing:
        text.append("Missing: " + ", ".join(missing))
    return ToolResult(True, "\n".join(text), metadata=metadata)


def tool_inspect_table(ctx: ToolContext, args: dict[str, object]) -> ToolResult:
    path = ctx.path_resolver(str(args["path"]))
    max_rows = max(0, int(args.get("max_rows", 5)))
    if not path.is_file():
        return ToolResult(False, f"not a file: {relpath(ctx, path)}", error_code="not_file")
    if path.suffix.lower() != ".csv":
        return ToolResult(False, f"unsupported table format for {relpath(ctx, path)}; CSV is supported in this build", error_code="unsupported_format")

    try:
        rows = _read_csv_dicts(path)
    except OSError as exc:
        return ToolResult(False, str(exc), error_code="io_error")
    except csv.Error as exc:
        return ToolResult(False, f"CSV parse error: {exc}", error_code="parse_error")

    columns = list(rows[0].keys()) if rows else _read_csv_header(path)
    missing = {col: sum(1 for row in rows if _is_blank(row.get(col))) for col in columns}
    inferred = {col: _infer_type([row.get(col, "") for row in rows]) for col in columns}
    duplicates = []
    if "sample_id" in columns:
        counts = Counter(row.get("sample_id", "") for row in rows if not _is_blank(row.get("sample_id")))
        duplicates = sorted([value for value, count in counts.items() if count > 1])
    numeric_stats = {col: _numeric_stats([row.get(col, "") for row in rows]) for col in columns if inferred[col] == "number"}
    preview = rows[:max_rows]
    metadata = {
        "path": relpath(ctx, path),
        "rows": len(rows),
        "columns": columns,
        "types": inferred,
        "missing_values": missing,
        "duplicate_sample_id": duplicates,
        "numeric_stats": numeric_stats,
        "preview": preview,
    }
    text = [f"Table: {metadata['path']}", f"Rows: {len(rows)}", "Columns: " + ", ".join(columns)]
    if duplicates:
        text.append("Duplicate sample_id: " + ", ".join(duplicates))
    if any(missing.values()):
        text.append("Missing values: " + json.dumps(missing, ensure_ascii=False, sort_keys=True))
    return ToolResult(True, "\n".join(text), metadata=metadata)


def tool_quality_check(ctx: ToolContext, args: dict[str, object]) -> ToolResult:
    experiment_dir = ctx.path_resolver(str(args["experiment_dir"]))
    batch_id = sanitize_batch_id(str(args.get("batch_id") or experiment_dir.name))
    if not experiment_dir.is_dir():
        return ToolResult(False, f"not a directory: {relpath(ctx, experiment_dir)}", error_code="not_directory")

    metadata_path = ctx.path_resolver(str(args["metadata_path"])) if args.get("metadata_path") else experiment_dir / "metadata.csv"
    spectra_dir = ctx.path_resolver(str(args["spectra_dir"])) if args.get("spectra_dir") else experiment_dir / "spectra"
    findings: list[dict[str, str]] = []

    metadata_rows: list[dict[str, str]] = []
    metadata_ids: list[str] = []
    if not metadata_path.is_file():
        findings.append(_finding(ctx, batch_id, "", metadata_path, "missing_metadata_file", "critical", f"metadata file not found: {relpath(ctx, metadata_path)}"))
    elif metadata_path.suffix.lower() != ".csv":
        findings.append(_finding(ctx, batch_id, "", metadata_path, "unsupported_metadata_format", "critical", "metadata must be CSV in this build"))
    else:
        metadata_rows = _read_csv_dicts(metadata_path)
        columns = set(metadata_rows[0].keys()) if metadata_rows else set(_read_csv_header(metadata_path))
        for field in REQUIRED_METADATA_FIELDS:
            if field not in columns:
                findings.append(_finding(ctx, batch_id, "", metadata_path, "missing_metadata_field", "critical", f"required metadata field is missing: {field}", field))
        for idx, row in enumerate(metadata_rows, start=2):
            sample_id = str(row.get("sample_id", "")).strip()
            if not sample_id:
                findings.append(_finding(ctx, batch_id, "", metadata_path, "missing_sample_id", "critical", f"metadata row {idx} has empty sample_id", f"row={idx}"))
                continue
            metadata_ids.append(sample_id)
            for key, value in row.items():
                if _is_blank(value):
                    findings.append(_finding(ctx, batch_id, sample_id, metadata_path, "missing_metadata_value", "warning", f"metadata field {key} is blank", key))
        for sample_id, count in Counter(metadata_ids).items():
            if count > 1:
                findings.append(_finding(ctx, batch_id, sample_id, metadata_path, "duplicate_sample_id", "critical", f"sample_id appears {count} times", str(count)))

    spectra_files = sorted(spectra_dir.glob("*.csv")) if spectra_dir.is_dir() else []
    if not spectra_dir.is_dir():
        findings.append(_finding(ctx, batch_id, "", spectra_dir, "missing_spectra_dir", "critical", f"spectra directory not found: {relpath(ctx, spectra_dir)}"))

    metadata_id_set = set(metadata_ids)
    file_sample_ids: dict[str, Path] = {}
    for path in spectra_files:
        match = FILENAME_PATTERN.match(path.name)
        if not match:
            findings.append(_finding(ctx, batch_id, _sample_id_from_name(path), path, "invalid_filename", "warning", "filename should match sample_id_method.csv", path.name))
            sample_id = _sample_id_from_name(path)
        else:
            sample_id = match.group("sample_id")
        file_sample_ids[sample_id] = path
        if sample_id not in metadata_id_set:
            findings.append(_finding(ctx, batch_id, sample_id, path, "file_without_metadata", "critical", "spectra file has no matching metadata record", path.name))
        findings.extend(_check_spectrum_file(ctx, batch_id, sample_id, path))

    for sample_id in sorted(metadata_id_set):
        if sample_id not in file_sample_ids:
            findings.append(_finding(ctx, batch_id, sample_id, spectra_dir / f"{sample_id}_*.csv", "missing_spectra_file", "critical", "metadata sample has no corresponding spectra CSV"))

    qc_path = resolve_output_path(ctx.root, batch_id, "qc_summary.csv")
    assert_raw_data_readonly(ctx.root, qc_path)
    _write_qc_summary(qc_path, findings)
    abnormal_samples = sorted({item["sample_id"] for item in findings if item["sample_id"]})
    by_check = Counter(item["check"] for item in findings)
    by_severity = Counter(item["severity"] for item in findings)
    metadata = {
        "batch_id": batch_id,
        "qc_summary_path": relpath(ctx, qc_path),
        "finding_count": len(findings),
        "abnormal_sample_count": len(abnormal_samples),
        "abnormal_samples": abnormal_samples,
        "by_check": dict(sorted(by_check.items())),
        "by_severity": dict(sorted(by_severity.items())),
    }
    text = [
        f"QC completed for {batch_id}",
        f"Findings: {len(findings)}",
        f"Abnormal samples: {len(abnormal_samples)}",
        f"QC summary: {metadata['qc_summary_path']}",
    ]
    if abnormal_samples:
        text.append("Abnormal sample list: " + ", ".join(abnormal_samples[:20]))
    return ToolResult(True, "\n".join(text), metadata=metadata, affected_paths=[metadata["qc_summary_path"]], workspace_changed=True)


def tool_run_preprocess_script(ctx: ToolContext, args: dict[str, object]) -> ToolResult:
    batch_id = sanitize_batch_id(str(args["batch_id"]))
    script_name = str(args["script_name"])
    script_path = resolve_registered_script(ctx.root, script_name)
    mode = str(args.get("mode") or ("batch" if args.get("input_dir") else "single"))
    if mode == "batch":
        return _run_batch_preprocess(ctx, args, batch_id, script_name, script_path)
    return _run_single_preprocess(ctx, args, batch_id, script_name, script_path)


def _run_single_preprocess(ctx: ToolContext, args: dict[str, object], batch_id: str, script_name: str, script_path: Path) -> ToolResult:
    input_path = resolve_workspace_path(ctx.root, str(args["input_path"]))
    if not input_path.is_file():
        return ToolResult(False, f"input file not found: {relpath(ctx, input_path)}", error_code="not_file")
    raw_output = str(args.get("output_path") or f"{input_path.stem}_normalized.csv")
    output_name = Path(raw_output).name if Path(raw_output).is_absolute() else raw_output
    output_path = resolve_preprocessed_path(ctx.root, batch_id, output_name)
    assert_raw_data_readonly(ctx.root, output_path)
    row = _run_preprocess_one(ctx, script_path, script_name, input_path, output_path)
    summary_path = resolve_output_path(ctx.root, batch_id, "preprocess_summary.csv")
    _write_preprocess_summary(summary_path, batch_id, [row])
    ok = row["status"] == "ok"
    affected = [row["output_path"], relpath(ctx, summary_path)] if ok else [relpath(ctx, summary_path)]
    return ToolResult(
        ok,
        f"preprocess {row['status']}: {row['file_path']} -> {row['output_path']}",
        metadata={
            "batch_id": batch_id,
            "script_name": script_name,
            "mode": "single",
            "input_file_count": 1,
            "success_count": 1 if ok else 0,
            "failed_count": 0 if ok else 1,
            "skipped_count": 0,
            "summary_path": relpath(ctx, summary_path),
            "output_path": row["output_path"],
        },
        error_code=None if ok else "script_failed",
        affected_paths=affected,
        workspace_changed=True,
    )


def _run_batch_preprocess(ctx: ToolContext, args: dict[str, object], batch_id: str, script_name: str, script_path: Path) -> ToolResult:
    input_dir = resolve_workspace_path(ctx.root, str(args.get("input_dir") or ""))
    if not input_dir.is_dir():
        return ToolResult(False, f"input directory not found: {relpath(ctx, input_dir)}", error_code="not_directory", metadata={"batch_id": batch_id, "script_name": script_name, "mode": "batch"})
    input_glob = str(args.get("input_glob") or "*.csv")
    max_files = max(1, int(args.get("max_files") or 200))
    output_suffix = str(args.get("output_suffix") or "_normalized.csv")
    skip_critical = bool(args.get("skip_critical", True))
    only_qc_passed = bool(args.get("only_qc_passed", False))
    skipped_samples = _critical_samples(ctx.root, batch_id) if (skip_critical or only_qc_passed) else set()
    candidates = sorted(input_dir.glob(input_glob))[:max_files]
    rows: list[dict[str, str]] = []
    for input_path in candidates:
        sample_id = _sample_id_from_name(input_path)
        if sample_id in skipped_samples:
            rows.append(_preprocess_row(ctx, script_name, input_path, Path(""), "skipped", "critical QC finding", 0.0))
            continue
        output_name = f"{input_path.stem}{output_suffix}"
        output_path = resolve_preprocessed_path(ctx.root, batch_id, output_name)
        assert_raw_data_readonly(ctx.root, output_path)
        rows.append(_run_preprocess_one(ctx, script_path, script_name, input_path, output_path))
    summary_path = resolve_output_path(ctx.root, batch_id, "preprocess_summary.csv")
    _write_preprocess_summary(summary_path, batch_id, rows)
    success = sum(1 for row in rows if row["status"] == "ok")
    failed = sum(1 for row in rows if row["status"] == "failed")
    skipped = sum(1 for row in rows if row["status"] == "skipped")
    affected = [row["output_path"] for row in rows if row["status"] == "ok"] + [relpath(ctx, summary_path)]
    metadata = {
        "batch_id": batch_id,
        "script_name": script_name,
        "mode": "batch",
        "input_file_count": len(candidates),
        "success_count": success,
        "failed_count": failed,
        "skipped_count": skipped,
        "summary_path": relpath(ctx, summary_path),
    }
    if not candidates:
        return ToolResult(False, "no preprocessing inputs matched", metadata=metadata, error_code="no_inputs", affected_paths=[relpath(ctx, summary_path)], workspace_changed=True)
    ok = success > 0
    return ToolResult(
        ok,
        f"batch preprocessing complete: success={success}, failed={failed}, skipped={skipped}",
        metadata=metadata,
        error_code=None if ok else "script_failed",
        affected_paths=affected,
        workspace_changed=True,
    )

def _critical_samples(root: Path, batch_id: str) -> set[str]:
    qc_path = root / "outputs" / batch_id / "qc_summary.csv"
    if not qc_path.is_file():
        return set()
    return {row.get("sample_id", "") for row in _read_csv_dicts(qc_path) if row.get("severity") == "critical" and row.get("sample_id")}


def _run_preprocess_one(ctx: ToolContext, script_path: Path, script_name: str, input_path: Path, output_path: Path) -> dict[str, str]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [sys.executable, str(script_path), str(input_path), str(output_path)],
            cwd=str(ctx.root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _preprocess_row(ctx, script_name, input_path, output_path, "failed", "timeout", time.perf_counter() - started)
    duration = time.perf_counter() - started
    status = "ok" if completed.returncode == 0 else "failed"
    error = "" if completed.returncode == 0 else (completed.stderr.strip() or f"returncode={completed.returncode}")
    return _preprocess_row(ctx, script_name, input_path, output_path, status, error, duration)


def _preprocess_row(ctx: ToolContext, script_name: str, input_path: Path, output_path: Path, status: str, error: str, duration: float) -> dict[str, str]:
    return {
        "sample_id": _sample_id_from_name(input_path),
        "file_path": relpath(ctx, input_path),
        "output_path": relpath(ctx, output_path) if str(output_path) else "",
        "status": status,
        "error_message": error,
        "script_name": script_name,
        "duration_seconds": f"{duration:.6f}",
    }


def _write_preprocess_summary(path: Path, batch_id: str, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["sample_id", "file_path", "output_path", "status", "error_message", "script_name", "duration_seconds"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def tool_summarize_outputs(ctx: ToolContext, args: dict[str, object]) -> ToolResult:
    batch_id = sanitize_batch_id(str(args["batch_id"]))
    output_dir = ctx.root / "outputs" / batch_id
    qc_path = output_dir / "qc_summary.csv"
    if not output_dir.exists():
        return ToolResult(False, f"output directory not found: outputs/{batch_id}", error_code="not_found")
    files = sorted(p for p in output_dir.rglob("*") if p.is_file())
    finding_count = 0
    abnormal_samples: set[str] = set()
    if qc_path.is_file():
        rows = _read_csv_dicts(qc_path)
        finding_count = len(rows)
        abnormal_samples = {row.get("sample_id", "") for row in rows if row.get("sample_id")}
    preprocess_path = output_dir / "preprocess_summary.csv"
    preprocess_rows = _read_csv_dicts(preprocess_path) if preprocess_path.is_file() else []
    success_count = sum(1 for row in preprocess_rows if row.get("status") == "ok")
    failed_count = sum(1 for row in preprocess_rows if row.get("status") == "failed")
    skipped_count = sum(1 for row in preprocess_rows if row.get("status") == "skipped")
    metadata = {
        "batch_id": batch_id,
        "output_files": [relpath(ctx, p) for p in files],
        "finding_count": finding_count,
        "abnormal_sample_count": len(abnormal_samples),
        "preprocessed_file_count": success_count,
        "preprocess_success_count": success_count,
        "preprocess_failed_count": failed_count,
        "preprocess_skipped_count": skipped_count,
    }
    text = [
        f"Batch: {batch_id}",
        f"Output files: {len(files)}",
        f"QC findings: {finding_count}",
        f"Abnormal samples: {len(abnormal_samples)}",
        f"Preprocess success/failed/skipped: {success_count}/{failed_count}/{skipped_count}",
    ]
    return ToolResult(True, "\n".join(text), metadata=metadata)


def tool_generate_report(ctx: ToolContext, args: dict[str, object]) -> ToolResult:
    batch_id = sanitize_batch_id(str(args["batch_id"]))
    qc_path = ctx.path_resolver(str(args["findings_path"])) if args.get("findings_path") else ctx.root / "outputs" / batch_id / "qc_summary.csv"
    if not qc_path.is_file():
        return ToolResult(False, f"QC summary not found: {relpath(ctx, qc_path)}", error_code="not_found", metadata={"batch_id": batch_id})
    rows = _read_csv_dicts(qc_path)
    by_check = Counter(row.get("check", "") for row in rows)
    by_severity = Counter(row.get("severity", "") for row in rows)
    abnormal_samples = sorted({row.get("sample_id", "") for row in rows if row.get("sample_id")})
    output_dir = ctx.root / "outputs" / batch_id
    preprocess_path = output_dir / "preprocess_summary.csv"
    preprocess_rows = _read_csv_dicts(preprocess_path) if preprocess_path.is_file() else []
    preprocess_success = sum(1 for row in preprocess_rows if row.get("status") == "ok")
    preprocess_failed = sum(1 for row in preprocess_rows if row.get("status") == "failed")
    preprocess_skipped = sum(1 for row in preprocess_rows if row.get("status") == "skipped")
    preprocessed = sorted((output_dir / "preprocessed").glob("*.csv")) if (output_dir / "preprocessed").is_dir() else []
    report_path = resolve_report_path(ctx.root, batch_id)
    assert_raw_data_readonly(ctx.root, report_path)
    assert_raw_data_readonly(ctx.root, qc_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    sections = [
        f"# LabFlow QC Report: {batch_id}",
        "",
        "## 数据概况",
        f"- Batch ID: {batch_id}",
        f"- QC summary: {relpath(ctx, qc_path)}",
        f"- Total findings: {len(rows)}",
        f"- Abnormal samples: {len(abnormal_samples)}",
        "",
        "## metadata 检查",
        _format_checks(by_check, ["missing_metadata_file", "unsupported_metadata_format", "missing_metadata_field", "missing_sample_id", "missing_metadata_value", "duplicate_sample_id"]),
        "",
        "## 文件一致性检查",
        _format_checks(by_check, ["missing_spectra_dir", "missing_spectra_file", "file_without_metadata", "invalid_filename"]),
        "",
        "## 数值异常检查",
        _format_checks(by_check, ["missing_spectrum_column", "missing_intensity", "non_numeric_intensity", "negative_intensity", "non_numeric_x", "x_not_monotonic", "too_few_points", "extreme_intensity"]),
        "",
        "## 预处理结果",
        f"- Preprocessed CSV files: {len(preprocessed)}",
        f"- Preprocess success: {preprocess_success}",
        f"- Preprocess failed: {preprocess_failed}",
        f"- Preprocess skipped: {preprocess_skipped}",
        *[f"- {relpath(ctx, path)}" for path in preprocessed[:20]],
        "",
        "## 异常样本列表",
        *(f"- {sample_id}" for sample_id in abnormal_samples[:50]),
        "" if abnormal_samples else "- No abnormal samples recorded.",
        "",
        "## 输出路径",
        f"- outputs: outputs/{batch_id}/",
        f"- report: {relpath(ctx, report_path)}",
        f"- workflow log: traces/{batch_id}_workflow_log.json",
        "",
        "## 复核建议",
        "- Critical findings should be reviewed against the raw instrument export before interpretation.",
        "- Re-run preprocessing only with registered scripts and preserve raw data unchanged.",
        "- Treat this report as rule-based QC evidence, not an automated scientific conclusion.",
        "",
        "## Severity counts",
        json.dumps(dict(sorted(by_severity.items())), ensure_ascii=False, indent=2),
    ]
    report_path.write_text("\n".join(sections), encoding="utf-8")
    return ToolResult(
        True,
        f"generated report: {relpath(ctx, report_path)}",
        metadata={"batch_id": batch_id, "report_path": relpath(ctx, report_path), "finding_count": len(rows), "preprocess_success_count": preprocess_success, "preprocess_failed_count": preprocess_failed, "preprocess_skipped_count": preprocess_skipped},
        affected_paths=[relpath(ctx, report_path)],
        workspace_changed=True,
    )


def tool_export_workflow_log(ctx: ToolContext, args: dict[str, object]) -> ToolResult:
    batch_id = sanitize_batch_id(str(args["batch_id"]))
    trace_path = resolve_trace_path(ctx.root, batch_id)
    assert_raw_data_readonly(ctx.root, trace_path)
    return ToolResult(
        True,
        f"workflow log export requested: {relpath(ctx, trace_path)}",
        metadata={"batch_id": batch_id, "workflow_log_path": relpath(ctx, trace_path), "pending_runtime_export": True},
        affected_paths=[relpath(ctx, trace_path)],
        workspace_changed=True,
    )


def _read_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        return next(reader, [])


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{str(key): str(value or "") for key, value in row.items()} for row in reader]


def _is_blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def _infer_type(values: list[str]) -> str:
    present = [value for value in values if not _is_blank(value)]
    if not present:
        return "empty"
    if all(_to_float(value) is not None for value in present):
        return "number"
    return "string"


def _numeric_stats(values: list[str]) -> dict[str, float | int]:
    numbers = [number for value in values if (number := _to_float(value)) is not None]
    if not numbers:
        return {"count": 0}
    return {"count": len(numbers), "min": min(numbers), "max": max(numbers), "mean": sum(numbers) / len(numbers)}


def _to_float(value: object) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _sample_id_from_name(path: Path) -> str:
    stem = path.stem
    return stem.rsplit("_", 1)[0] if "_" in stem else stem


def _finding(ctx: ToolContext, batch_id: str, sample_id: str, path: Path, check: str, severity: str, message: str, evidence: str = "") -> dict[str, str]:
    return {
        "finding_id": "",
        "batch_id": batch_id,
        "sample_id": sample_id,
        "file": relpath(ctx, path),
        "check": check,
        "severity": severity,
        "status": "fail",
        "message": message,
        "evidence": evidence,
    }


def _check_spectrum_file(ctx: ToolContext, batch_id: str, sample_id: str, path: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    try:
        rows = _read_csv_dicts(path)
    except (OSError, csv.Error) as exc:
        return [_finding(ctx, batch_id, sample_id, path, "spectrum_parse_error", "critical", f"cannot parse spectra CSV: {exc}")]
    columns = set(rows[0].keys()) if rows else set(_read_csv_header(path))
    for field in REQUIRED_SPECTRA_FIELDS:
        if field not in columns:
            findings.append(_finding(ctx, batch_id, sample_id, path, "missing_spectrum_column", "critical", f"required spectra column is missing: {field}", field))
    if len(rows) < MIN_SPECTRA_POINTS:
        findings.append(_finding(ctx, batch_id, sample_id, path, "too_few_points", "warning", f"spectra has too few points: {len(rows)}", str(len(rows))))
    if not all(field in columns for field in REQUIRED_SPECTRA_FIELDS):
        return findings

    xs: list[float] = []
    intensities: list[float] = []
    for idx, row in enumerate(rows, start=2):
        x = _to_float(row.get("x"))
        intensity = _to_float(row.get("intensity"))
        if x is None:
            findings.append(_finding(ctx, batch_id, sample_id, path, "non_numeric_x", "critical", f"row {idx} has non-numeric x", f"row={idx}"))
        else:
            xs.append(x)
        if _is_blank(row.get("intensity")):
            findings.append(_finding(ctx, batch_id, sample_id, path, "missing_intensity", "critical", f"row {idx} has missing intensity", f"row={idx}"))
        elif intensity is None:
            findings.append(_finding(ctx, batch_id, sample_id, path, "non_numeric_intensity", "critical", f"row {idx} has non-numeric intensity", f"row={idx}"))
        else:
            intensities.append(intensity)
            if intensity < 0:
                findings.append(_finding(ctx, batch_id, sample_id, path, "negative_intensity", "critical", f"row {idx} has negative intensity", str(intensity)))
    if len(xs) >= 2 and any(current <= previous for previous, current in zip(xs, xs[1:])):
        findings.append(_finding(ctx, batch_id, sample_id, path, "x_not_monotonic", "critical", "x values must be strictly increasing"))
    if intensities:
        mean = statistics.fmean(intensities)
        stdev = statistics.pstdev(intensities) if len(intensities) > 1 else 0.0
        if stdev and any(abs(value - mean) > 6 * stdev for value in intensities):
            findings.append(_finding(ctx, batch_id, sample_id, path, "extreme_intensity", "warning", "intensity contains extreme outlier", f"mean={mean:.4g};stdev={stdev:.4g}"))
    return findings


def _write_qc_summary(path: Path, findings: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QC_COLUMNS)
        writer.writeheader()
        for index, item in enumerate(findings, start=1):
            row = dict(item)
            row["finding_id"] = f"F{index:04d}"
            writer.writerow({key: row.get(key, "") for key in QC_COLUMNS})




def _format_checks(counts: Counter[str], keys: list[str]) -> str:
    lines = [f"- {key}: {counts.get(key, 0)}" for key in keys if counts.get(key, 0)]
    return "\n".join(lines) if lines else "- No findings in this section."

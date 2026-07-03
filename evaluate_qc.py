from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED_REPORT_SECTIONS = [
    "数据概况",
    "metadata 检查",
    "文件一致性检查",
    "数值异常检查",
    "预处理结果",
    "异常样本列表",
    "输出路径",
    "复核建议",
]


def normalize_key(batch_id: str, sample_or_file: str, check: str) -> tuple[str, str, str]:
    return (batch_id, sample_or_file, check)


def load_prediction_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_label_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("expected_findings") or data.get("labels") or []
    return [dict(row) for row in rows]


def rows_to_keys(rows: list[dict[str, Any]], batch_id: str) -> set[tuple[str, str, str]]:
    keys = set()
    for row in rows:
        key = row.get("sample_id") or row.get("file") or "batch"
        check = row.get("check") or row.get("anomaly_type")
        if check:
            keys.add(normalize_key(str(row.get("batch_id") or batch_id), str(key), str(check)))
    return keys


def load_predictions(path: Path) -> set[tuple[str, str]]:
    batch_id = infer_batch_id_from_pred(path)
    return {(sample, check) for _, sample, check in rows_to_keys(load_prediction_rows(path), batch_id)}


def load_labels(path: Path) -> set[tuple[str, str]]:
    batch_id = infer_batch_id_from_labels(path)
    return {(sample, check) for _, sample, check in rows_to_keys(load_label_rows(path), batch_id)}


def precision_recall_f1(predicted: set[tuple[Any, ...]], expected: set[tuple[Any, ...]]) -> dict[str, Any]:
    tp = len(predicted & expected)
    fp = len(predicted - expected)
    fn = len(expected - predicted)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def report_field_coverage(report_path: Path | None) -> dict[str, Any]:
    if report_path is None or not report_path.is_file():
        return {"covered": 0, "total": len(REQUIRED_REPORT_SECTIONS), "coverage": 0.0, "missing": REQUIRED_REPORT_SECTIONS}
    text = report_path.read_text(encoding="utf-8", errors="replace")
    missing = [section for section in REQUIRED_REPORT_SECTIONS if section not in text]
    covered = len(REQUIRED_REPORT_SECTIONS) - len(missing)
    return {"covered": covered, "total": len(REQUIRED_REPORT_SECTIONS), "coverage": covered / len(REQUIRED_REPORT_SECTIONS), "missing": missing}


def load_trace_duration(trace_path: Path | None) -> float | None:
    if trace_path is None or not trace_path.is_file():
        return None
    data = json.loads(trace_path.read_text(encoding="utf-8"))
    value = data.get("total_duration_seconds")
    if value is not None:
        return float(value)
    events = data.get("events", [])
    if isinstance(events, list):
        return sum(float(event.get("duration_seconds") or 0.0) for event in events)
    return None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def raw_data_miswrite_count(root: Path, labels_path: Path) -> int:
    if not labels_path.is_file():
        return 0
    data = json.loads(labels_path.read_text(encoding="utf-8"))
    manifest = data.get("raw_data_manifest") or []
    count = 0
    for item in manifest:
        path = root / str(item.get("path", ""))
        if not path.is_file():
            count += 1
            continue
        if item.get("sha256") and file_sha256(path) != item.get("sha256"):
            count += 1
    return count


def infer_batch_id_from_pred(path: Path) -> str:
    parent = path.parent.name
    return parent if parent else path.stem


def infer_batch_id_from_labels(path: Path) -> str:
    name = path.stem
    return name[:-7] if name.endswith("_labels") else name


def diagnostic_rows(predicted: set[tuple[str, str, str]], expected: set[tuple[str, str, str]]) -> list[dict[str, str]]:
    rows = []
    for batch_id, sample_id, check in sorted(predicted - expected):
        rows.append({"batch_id": batch_id, "sample_id": sample_id, "check": check, "error_type": "false_positive", "predicted": "true", "expected": "false", "reason": "Predicted finding is not present in labels"})
    for batch_id, sample_id, check in sorted(expected - predicted):
        rows.append({"batch_id": batch_id, "sample_id": sample_id, "check": check, "error_type": "false_negative", "predicted": "false", "expected": "true", "reason": "Expected finding was not predicted"})
    return rows


def count_metadata_samples(root: Path, batch_id: str) -> int:
    metadata = root / "data" / batch_id / "metadata.csv"
    if not metadata.is_file():
        return 0
    with metadata.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def evaluate_single(pred_path: Path, labels_path: Path, report_path: Path | None = None, trace_path: Path | None = None, root: Path | None = None) -> dict[str, Any]:
    root = root or Path.cwd()
    batch_id = infer_batch_id_from_labels(labels_path)
    predicted = rows_to_keys(load_prediction_rows(pred_path), batch_id)
    expected = rows_to_keys(load_label_rows(labels_path), batch_id)
    metrics = precision_recall_f1(predicted, expected)
    duration = load_trace_duration(trace_path)
    return {
        "batch_id": batch_id,
        **metrics,
        "predicted_count": len(predicted),
        "expected_count": len(expected),
        "end_to_end_task_completed": pred_path.is_file() and (report_path.is_file() if report_path else True) and (trace_path.is_file() if trace_path else True),
        "report_field_coverage": report_field_coverage(report_path),
        "raw_data_miswrite_count": raw_data_miswrite_count(root, labels_path),
        "average_processing_seconds": duration,
        "total_processing_seconds": duration,
        "errors": diagnostic_rows(predicted, expected),
    }


def evaluate_multi(pred_dir: Path, labels_dir: Path, reports_dir: Path, traces_dir: Path, root: Path) -> dict[str, Any]:
    per_batch = []
    all_predicted: set[tuple[str, str, str]] = set()
    all_expected: set[tuple[str, str, str]] = set()
    total_samples = 0
    durations = []
    raw_miswrites = 0
    coverages = []
    missing_by_batch: dict[str, list[str]] = {}
    for labels_path in sorted(labels_dir.glob("batch_demo_*_labels.json")):
        batch_id = infer_batch_id_from_labels(labels_path)
        pred_path = pred_dir / batch_id / "qc_summary.csv"
        report_path = reports_dir / f"{batch_id}_qc_report.md"
        trace_path = traces_dir / f"{batch_id}_workflow_log.json"
        predicted = rows_to_keys(load_prediction_rows(pred_path), batch_id)
        expected = rows_to_keys(load_label_rows(labels_path), batch_id)
        all_predicted |= predicted
        all_expected |= expected
        total_samples += count_metadata_samples(root, batch_id)
        duration = load_trace_duration(trace_path)
        if duration is not None:
            durations.append(duration)
        raw_miswrites += raw_data_miswrite_count(root, labels_path)
        coverage = report_field_coverage(report_path)
        coverages.append(float(coverage["coverage"]))
        if coverage["missing"]:
            missing_by_batch[batch_id] = list(coverage["missing"])
        batch_metrics = precision_recall_f1(predicted, expected)
        per_batch.append({"batch_id": batch_id, **batch_metrics, "predicted_count": len(predicted), "expected_count": len(expected), "sample_count": count_metadata_samples(root, batch_id), "completed": pred_path.is_file() and report_path.is_file() and trace_path.is_file(), "processing_seconds": duration, "report_coverage": coverage["coverage"]})
    metrics = precision_recall_f1(all_predicted, all_expected)
    errors = diagnostic_rows(all_predicted, all_expected)
    return {
        "batch_count": len(per_batch),
        "sample_count": total_samples,
        "expected_count": len(all_expected),
        "predicted_count": len(all_predicted),
        **metrics,
        "end_to_end_task_completed": all(item["completed"] for item in per_batch) if per_batch else False,
        "report_field_coverage": {"average_coverage": sum(coverages) / len(coverages) if coverages else 0.0, "min_coverage": min(coverages) if coverages else 0.0, "missing_by_batch": missing_by_batch},
        "raw_data_miswrite_count": raw_miswrites,
        "average_processing_seconds": sum(durations) / len(durations) if durations else None,
        "total_processing_seconds": sum(durations) if durations else None,
        "per_batch": per_batch,
        "errors": errors,
    }


def write_errors(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["batch_id", "sample_id", "check", "error_type", "predicted", "expected", "reason"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def resume_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_name": "LabFlow Agent",
        "benchmark_batches": summary.get("batch_count", 1),
        "sample_records": summary.get("sample_count"),
        "anomaly_types": len({item["check"] for item in summary.get("errors", [])}) if summary.get("errors") else None,
        "labeled_findings": summary.get("expected_count"),
        "predicted_findings": summary.get("predicted_count"),
        "precision": summary.get("precision"),
        "recall": summary.get("recall"),
        "f1": summary.get("f1"),
        "report_field_coverage": summary.get("report_field_coverage", {}).get("average_coverage") if isinstance(summary.get("report_field_coverage"), dict) else None,
        "raw_data_miswrite_count": summary.get("raw_data_miswrite_count"),
        "average_processing_seconds": summary.get("average_processing_seconds"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate LabFlow QC predictions against labels.")
    parser.add_argument("--pred", help="Path to qc_summary.csv")
    parser.add_argument("--labels", help="Path to labels JSON")
    parser.add_argument("--report", default=None, help="Optional generated Markdown report path")
    parser.add_argument("--trace", default=None, help="Optional workflow log path")
    parser.add_argument("--pred-dir", default=None)
    parser.add_argument("--labels-dir", default=None)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--traces-dir", default="traces")
    parser.add_argument("--output", default=None)
    parser.add_argument("--errors", default=None)
    parser.add_argument("--resume-metrics", default=None)
    args = parser.parse_args(argv)
    root = Path.cwd()
    if args.pred:
        if not args.labels:
            parser.error("--labels is required with --pred")
        result = evaluate_single(Path(args.pred), Path(args.labels), Path(args.report) if args.report else None, Path(args.trace) if args.trace else None, root)
        errors = result.pop("errors")
        if args.errors:
            write_errors(Path(args.errors), errors)
        if args.output:
            Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        if args.resume_metrics:
            Path(args.resume_metrics).write_text(json.dumps(resume_metrics({"batch_count": 1, **result}), indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if not args.pred_dir or not args.labels_dir:
        parser.error("either --pred/--labels or --pred-dir/--labels-dir is required")
    summary = evaluate_multi(Path(args.pred_dir), Path(args.labels_dir), Path(args.reports_dir), Path(args.traces_dir), root)
    errors = summary.pop("errors")
    if args.output:
        Path(args.output).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.errors:
        write_errors(Path(args.errors), errors)
    if args.resume_metrics:
        Path(args.resume_metrics).write_text(json.dumps(resume_metrics(summary), indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

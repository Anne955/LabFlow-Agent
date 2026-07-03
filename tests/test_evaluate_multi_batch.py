from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluate_qc import evaluate_multi, main


def write_qc(path: Path, batch_id: str, sample_id: str, check: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["finding_id", "batch_id", "sample_id", "file", "check", "severity", "status", "message", "evidence"])
        writer.writeheader()
        writer.writerow({"finding_id": "F0001", "batch_id": batch_id, "sample_id": sample_id, "file": "file.csv", "check": check, "severity": "critical", "status": "fail", "message": "", "evidence": ""})


class EvaluateMultiBatchTests(unittest.TestCase):
    def test_multi_batch_writes_summary_errors_and_resume_metrics(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for batch_id in ["batch_demo_001", "batch_demo_002"]:
                (root / "data" / batch_id).mkdir(parents=True)
                (root / "data" / batch_id / "metadata.csv").write_text("sample_id,method\ns1,raman\n", encoding="utf-8")
                write_qc(root / "outputs" / batch_id / "qc_summary.csv", batch_id, "s1", "negative_intensity")
                (root / "labels").mkdir(exist_ok=True)
                (root / "labels" / f"{batch_id}_labels.json").write_text(json.dumps({"batch_id": batch_id, "expected_findings": [{"sample_id": "s1", "check": "negative_intensity"}]}), encoding="utf-8")
                (root / "reports").mkdir(exist_ok=True)
                (root / "reports" / f"{batch_id}_qc_report.md").write_text("\n".join(["数据概况", "metadata 检查", "文件一致性检查", "数值异常检查", "预处理结果", "异常样本列表", "输出路径", "复核建议"]), encoding="utf-8")
                (root / "traces").mkdir(exist_ok=True)
                (root / "traces" / f"{batch_id}_workflow_log.json").write_text(json.dumps({"total_duration_seconds": 1.5, "events": []}), encoding="utf-8")
            cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                self.assertEqual(
                    main([
                        "--pred-dir", "outputs",
                        "--labels-dir", "labels",
                        "--reports-dir", "reports",
                        "--traces-dir", "traces",
                        "--output", "evaluation_summary.json",
                        "--errors", "evaluation_errors.csv",
                        "--resume-metrics", "resume_metrics.json",
                    ]),
                    0,
                )
            finally:
                os.chdir(cwd)
            summary = json.loads((root / "evaluation_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["batch_count"], 2)
            self.assertEqual(summary["average_processing_seconds"], 1.5)
            self.assertTrue((root / "evaluation_errors.csv").is_file())
            self.assertTrue((root / "resume_metrics.json").is_file())


if __name__ == "__main__":
    unittest.main()

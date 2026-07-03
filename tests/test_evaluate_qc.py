from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluate_qc import load_labels, load_predictions, precision_recall_f1, report_field_coverage


class EvaluateQCTests(unittest.TestCase):
    def test_precision_recall_f1(self):
        predicted = {("s1", "a"), ("s2", "b")}
        expected = {("s1", "a"), ("s3", "c")}
        metrics = precision_recall_f1(predicted, expected)
        self.assertEqual(metrics["true_positive"], 1)
        self.assertEqual(metrics["false_positive"], 1)
        self.assertEqual(metrics["false_negative"], 1)
        self.assertAlmostEqual(metrics["precision"], 0.5)
        self.assertAlmostEqual(metrics["recall"], 0.5)
        self.assertAlmostEqual(metrics["f1"], 0.5)

    def test_load_predictions_and_labels(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pred = root / "qc_summary.csv"
            pred.write_text(
                "finding_id,batch_id,sample_id,file,check,severity,status,message,evidence\n"
                "F0001,b,s1,file.csv,negative_intensity,critical,fail,msg,e\n",
                encoding="utf-8",
            )
            labels = root / "labels.json"
            labels.write_text(json.dumps({"labels": [{"sample_id": "s1", "check": "negative_intensity"}]}), encoding="utf-8")
            self.assertEqual(load_predictions(pred), {("s1", "negative_intensity")})
            self.assertEqual(load_labels(labels), {("s1", "negative_intensity")})

    def test_report_field_coverage(self):
        with TemporaryDirectory() as directory:
            report = Path(directory) / "report.md"
            report.write_text("数据概况\nmetadata 检查\n文件一致性检查\n", encoding="utf-8")
            coverage = report_field_coverage(report)
            self.assertEqual(coverage["covered"], 3)
            self.assertLess(coverage["coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluate_qc import diagnostic_rows, rows_to_keys, write_errors


class EvaluationErrorsTests(unittest.TestCase):
    def test_diagnostic_rows_include_false_positive_and_false_negative(self):
        predicted = rows_to_keys([{"batch_id": "b", "sample_id": "s1", "check": "a"}], "b")
        expected = rows_to_keys([{"batch_id": "b", "sample_id": "s2", "check": "b"}], "b")
        rows = diagnostic_rows(predicted, expected)
        self.assertEqual({row["error_type"] for row in rows}, {"false_positive", "false_negative"})
        with TemporaryDirectory() as directory:
            path = Path(directory) / "errors.csv"
            write_errors(path, rows)
            with path.open("r", encoding="utf-8") as handle:
                loaded = list(csv.DictReader(handle))
            self.assertEqual(len(loaded), 2)


if __name__ == "__main__":
    unittest.main()

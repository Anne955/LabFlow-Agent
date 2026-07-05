from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.errors import SafetyViolationError
from pico.safety.guard import assert_raw_data_readonly


class RawDataReadonlyTests(unittest.TestCase):
    def test_writing_batch_data_raises_safety_violation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "data" / "batch_001" / "spectra" / "x.csv"
            raw.parent.mkdir(parents=True)
            with self.assertRaises(SafetyViolationError):
                assert_raw_data_readonly(root, raw)

    def test_writing_outputs_is_allowed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / "outputs" / "batch_001" / "qc_summary.csv"
            out.parent.mkdir(parents=True)
            assert_raw_data_readonly(root, out)  # must not raise

    def test_writing_data_raw_raises(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "data" / "raw" / "sample.csv"
            raw.parent.mkdir(parents=True)
            with self.assertRaises(SafetyViolationError):
                assert_raw_data_readonly(root, raw)


if __name__ == "__main__":
    unittest.main()

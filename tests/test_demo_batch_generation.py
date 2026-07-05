from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.generate_demo_batches import main


class DemoBatchGenerationTests(unittest.TestCase):
    def test_generator_creates_requested_batches_and_labels(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                main(
                    [
                        "--batches",
                        "2",
                        "--samples-per-batch",
                        "5",
                        "--seed",
                        "7",
                        "--root",
                        str(root),
                    ]
                ),
                0,
            )
            for index in [1, 2]:
                batch_id = f"batch_demo_{index:03d}"
                batch = root / "data" / batch_id
                self.assertTrue((batch / "metadata.csv").is_file())
                self.assertTrue((batch / "instrument_log.txt").is_file())
                self.assertTrue((batch / "spectra").is_dir())
                labels = root / "labels" / f"{batch_id}_labels.json"
                self.assertTrue(labels.is_file())
                data = json.loads(labels.read_text(encoding="utf-8"))
                self.assertIn("expected_findings", data)
                self.assertGreater(len(data["expected_findings"]), 0)
                self.assertIn("raw_data_manifest", data)


if __name__ == "__main__":
    unittest.main()

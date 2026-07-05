from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.convert_rruff_to_labflow_csv import convert_rruff_batch, parse_rruff_txt


def write_raw(path: Path, offset: int = 0) -> None:
    lines = ["# RRUFF header", "## comment", "not numeric"]
    for idx in range(12):
        x = 100 + idx
        y = 1000 + offset + idx
        if idx % 3 == 0:
            lines.append(f"{x} {y}")
        elif idx % 3 == 1:
            lines.append(f"{x},{y}")
        else:
            lines.append(f"{x}\t{y}\textra")
    path.write_text("\n".join(lines), encoding="utf-8")


class RruffConverterTests(unittest.TestCase):
    def test_parse_rruff_txt_ignores_headers_and_delimiters(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "RRUFF_R050000_raman.txt"
            write_raw(path)
            points = parse_rruff_txt(path, min_points=10)
            self.assertEqual(len(points), 12)
            self.assertEqual(points[0], (100.0, 1000.0))

    def test_converter_creates_labflow_batch_from_local_txt_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            for idx in range(20):
                write_raw(raw / f"RRUFF_R{50000 + idx:06d}_raman.txt", idx)
            output = root / "data" / "batch_public_rruff_001"
            result = convert_rruff_batch(raw, output, "batch_public_rruff_001", limit=20)
            self.assertEqual(result["converted"], 20)
            metadata = output / "metadata.csv"
            self.assertTrue(metadata.is_file())
            self.assertTrue((output / "instrument_log.txt").is_file())
            spectra = sorted((output / "spectra").glob("*.csv"))
            self.assertEqual(len(spectra), 20)
            with spectra[0].open("r", encoding="utf-8") as handle:
                self.assertEqual(handle.readline().strip(), "x,intensity")
            with metadata.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 20)
            self.assertEqual(
                set(rows[0]),
                {
                    "sample_id",
                    "method",
                    "instrument",
                    "operator",
                    "file_path",
                    "source_dataset",
                    "source_id",
                },
            )
            self.assertEqual(rows[0]["method"], "raman")
            for row in rows:
                self.assertTrue((output / row["file_path"]).is_file())

    def test_converter_fails_if_too_few_usable_spectra(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            write_raw(raw / "RRUFF_R050000_raman.txt")
            with self.assertRaises(ValueError):
                convert_rruff_batch(raw, root / "out", "batch_public_rruff_001", limit=20)


if __name__ == "__main__":
    unittest.main()

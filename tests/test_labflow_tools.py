from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.labflow_tools import tool_inspect_table, tool_quality_check, tool_scan_experiment_dir
from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.workspace import resolve_in_workspace


def make_context(root: Path) -> ToolContext:
    return ToolContext(
        root=root,
        path_resolver=lambda raw: resolve_in_workspace(root, raw),
        shell_env_provider=safe_shell_env,
    )


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class LabFlowToolsTests(unittest.TestCase):
    def test_scan_experiment_dir_identifies_inputs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "data" / "batch_demo_001"
            (batch / "spectra").mkdir(parents=True)
            (batch / "metadata.csv").write_text("sample_id,method\ns1,raman\n", encoding="utf-8")
            (batch / "instrument_log.txt").write_text("ok", encoding="utf-8")
            (batch / "spectra" / "s1_raman.csv").write_text("x,intensity\n1,2\n", encoding="utf-8")
            result = tool_scan_experiment_dir(make_context(root), {"experiment_dir": "data/batch_demo_001"})
            self.assertTrue(result.ok)
            self.assertEqual(result.metadata["batch_id"], "batch_demo_001")
            self.assertEqual(result.metadata["spectra_file_count"], 1)
            self.assertEqual(result.metadata["missing"], [])

    def test_inspect_table_reports_duplicates_and_missing_values(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            table = root / "metadata.csv"
            write_csv(
                table,
                [
                    {"sample_id": "s1", "method": "raman", "operator": "A"},
                    {"sample_id": "s1", "method": "", "operator": "B"},
                ],
                ["sample_id", "method", "operator"],
            )
            result = tool_inspect_table(make_context(root), {"path": "metadata.csv"})
            self.assertTrue(result.ok)
            self.assertEqual(result.metadata["rows"], 2)
            self.assertEqual(result.metadata["duplicate_sample_id"], ["s1"])
            self.assertEqual(result.metadata["missing_values"]["method"], 1)

    def test_quality_check_writes_summary_and_detects_core_anomalies(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "data" / "batch_demo_001"
            spectra = batch / "spectra"
            spectra.mkdir(parents=True)
            write_csv(
                batch / "metadata.csv",
                [
                    {"sample_id": "s1", "method": "raman", "operator": "A"},
                    {"sample_id": "s1", "method": "raman", "operator": "B"},
                    {"sample_id": "s2", "method": "raman", "operator": ""},
                    {"sample_id": "s3", "method": "raman", "operator": "C"},
                ],
                ["sample_id", "method", "operator"],
            )
            write_csv(
                spectra / "s1_raman.csv",
                [
                    {"x": 1, "intensity": 1},
                    {"x": 2, "intensity": -3},
                ],
                ["x", "intensity"],
            )
            write_csv(spectra / "s2_raman.csv", [{"x": 2, "intensity": 1}, {"x": 1, "intensity": 2}], ["x", "intensity"])
            write_csv(spectra / "orphan_raman.csv", [{"x": 1, "intensity": 1}], ["x", "intensity"])
            write_csv(spectra / "badname.csv", [{"x": 1}], ["x"])

            result = tool_quality_check(make_context(root), {"experiment_dir": "data/batch_demo_001"})
            self.assertTrue(result.ok)
            qc_path = root / "outputs" / "batch_demo_001" / "qc_summary.csv"
            self.assertTrue(qc_path.is_file())
            text = qc_path.read_text(encoding="utf-8")
            self.assertIn("duplicate_sample_id", text)
            self.assertIn("negative_intensity", text)
            self.assertIn("x_not_monotonic", text)
            self.assertIn("file_without_metadata", text)
            self.assertIn("missing_spectra_file", text)
            self.assertIn("missing_spectrum_column", text)


if __name__ == "__main__":
    unittest.main()

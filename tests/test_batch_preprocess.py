from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.labflow_tools import tool_quality_check, tool_run_preprocess_script
from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.workspace import resolve_in_workspace


def make_context(root: Path) -> ToolContext:
    return ToolContext(
        root=root,
        path_resolver=lambda raw: resolve_in_workspace(root, raw),
        shell_env_provider=safe_shell_env,
    )


def write_spectrum(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "x,intensity\n" + "\n".join(f"{idx},{idx + 10}" for idx in range(1, 13)) + "\n",
        encoding="utf-8",
    )


class BatchPreprocessTests(unittest.TestCase):
    def test_batch_preprocess_writes_summary_and_skips_critical_samples(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "data" / "batch_demo_001"
            spectra = batch / "spectra"
            spectra.mkdir(parents=True)
            (batch / "metadata.csv").write_text(
                "sample_id,method\nsample_001,raman\nsample_002,raman\n", encoding="utf-8"
            )
            write_spectrum(spectra / "sample_001_raman.csv")
            (spectra / "sample_002_raman.csv").write_text(
                "x,intensity\n1,-1\n2,2\n", encoding="utf-8"
            )
            scripts = root / "scripts"
            scripts.mkdir()
            source_script = Path(__file__).resolve().parents[1] / "scripts" / "normalize_csv.py"
            (scripts / "normalize_csv.py").write_text(
                source_script.read_text(encoding="utf-8"), encoding="utf-8"
            )
            ctx = make_context(root)
            qc_result = tool_quality_check(
                ctx, {"experiment_dir": "data/batch_demo_001", "batch_id": "batch_demo_001"}
            )
            self.assertTrue(qc_result.ok)
            result = tool_run_preprocess_script(
                ctx,
                {
                    "script_name": "normalize_csv.py",
                    "batch_id": "batch_demo_001",
                    "mode": "batch",
                    "input_dir": "data/batch_demo_001/spectra",
                    "input_glob": "*.csv",
                    "output_suffix": "_normalized.csv",
                    "skip_critical": True,
                },
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.metadata["mode"], "batch")
            self.assertEqual(result.metadata["success_count"], 1)
            self.assertEqual(result.metadata["skipped_count"], 1)
            summary = root / "outputs" / "batch_demo_001" / "preprocess_summary.csv"
            self.assertTrue(summary.is_file())
            with summary.open("r", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertIn("skipped", {row["status"] for row in rows})


if __name__ == "__main__":
    unittest.main()

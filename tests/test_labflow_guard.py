from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.labflow_tools import tool_run_preprocess_script
from pico.safety.guard import (
    resolve_output_path,
    resolve_registered_script,
    sanitize_batch_id,
)
from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.workspace import resolve_in_workspace


def make_context(root: Path) -> ToolContext:
    return ToolContext(
        root=root,
        path_resolver=lambda raw: resolve_in_workspace(root, raw),
        shell_env_provider=safe_shell_env,
    )


class LabFlowGuardTests(unittest.TestCase):
    def test_sanitize_batch_id_rejects_path_like_values(self):
        self.assertEqual(sanitize_batch_id("batch_demo_001"), "batch_demo_001")
        with self.assertRaises(ValueError):
            sanitize_batch_id("../batch_demo_001")

    def test_output_path_is_constrained_to_outputs_batch(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = resolve_output_path(root, "batch_demo_001", "qc_summary.csv")
            self.assertEqual(path, root.resolve() / "outputs" / "batch_demo_001" / "qc_summary.csv")
            with self.assertRaises(ValueError):
                resolve_output_path(root, "batch_demo_001", "../../raw.csv")

    def test_registered_script_rejects_unlisted_names(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "normalize_csv.py").write_text("", encoding="utf-8")
            self.assertEqual(
                resolve_registered_script(root, "normalize_csv.py").name, "normalize_csv.py"
            )
            with self.assertRaises(ValueError):
                resolve_registered_script(root, "../normalize_csv.py")
            with self.assertRaises(ValueError):
                resolve_registered_script(root, "arbitrary.py")

    def test_run_preprocess_script_uses_whitelist_and_outputs_preprocessed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            source_script = Path(__file__).resolve().parents[1] / "scripts" / "normalize_csv.py"
            (scripts / "normalize_csv.py").write_text(
                source_script.read_text(encoding="utf-8"), encoding="utf-8"
            )
            raw = root / "data" / "batch_demo_001" / "spectra" / "s1_raman.csv"
            raw.parent.mkdir(parents=True)
            raw.write_text(" x , intensity \n 1 , 2 \n", encoding="utf-8")
            result = tool_run_preprocess_script(
                make_context(root),
                {
                    "script_name": "normalize_csv.py",
                    "input_path": "data/batch_demo_001/spectra/s1_raman.csv",
                    "output_path": "s1_raman_normalized.csv",
                    "batch_id": "batch_demo_001",
                },
            )
            self.assertTrue(result.ok)
            output = (
                root / "outputs" / "batch_demo_001" / "preprocessed" / "s1_raman_normalized.csv"
            )
            self.assertTrue(output.is_file())
            self.assertIn("x,intensity", output.read_text(encoding="utf-8"))
            self.assertEqual(raw.read_text(encoding="utf-8"), " x , intensity \n 1 , 2 \n")


if __name__ == "__main__":
    unittest.main()

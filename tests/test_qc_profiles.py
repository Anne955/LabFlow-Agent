from __future__ import annotations

import csv
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.tools.labflow import (
    DEFAULT_QC_PROFILE,
    QC_PROFILES,
    tool_generate_report,
    tool_quality_check,
)
from pico.workspace import resolve_in_workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
MOF_DATA = REPO_ROOT / "data" / "batch_public_mof_001"


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


def make_spectrum_batch(
    root: Path,
    *,
    sample_id: str = "s1",
    intensities: list[float],
    method: str = "raman",
) -> Path:
    """Create a minimal batch with one spectrum having the given intensities."""
    batch = root / "data" / "batch_x"
    spectra = batch / "spectra"
    spectra.mkdir(parents=True, exist_ok=True)
    write_csv(
        batch / "metadata.csv",
        [{"sample_id": sample_id, "method": method}],
        ["sample_id", "method"],
    )
    write_csv(
        spectra / f"{sample_id}_{method}.csv",
        [{"x": i, "intensity": v} for i, v in enumerate(intensities, start=1)],
        ["x", "intensity"],
    )
    return batch


def qc_rows(root: Path, batch_id: str = "batch_x") -> list[dict[str, str]]:
    path = root / "outputs" / batch_id / "qc_summary.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def negative_findings(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("check") == "negative_intensity"]


class QcProfileContractTests(unittest.TestCase):
    def test_default_profile_is_raw_spectrum(self):
        self.assertEqual(DEFAULT_QC_PROFILE, "raw_spectrum")
        self.assertIn("raw_spectrum", QC_PROFILES)
        self.assertIn("processed_spectrum", QC_PROFILES)
        self.assertIn("baseline_corrected", QC_PROFILES)

    def test_omitting_qc_profile_keeps_negative_intensity_critical(self):
        # Default behavior must be unchanged: a negative intensity is critical.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            make_spectrum_batch(root, intensities=[1.0, -3.0, 2.0, -5.0, 1.0])
            result = tool_quality_check(make_context(root), {"experiment_dir": "data/batch_x"})
            self.assertTrue(result.ok)
            self.assertEqual(result.metadata["qc_profile"], "raw_spectrum")
            neg = negative_findings(qc_rows(root))
            self.assertEqual(len(neg), 2)
            self.assertTrue(all(row["severity"] == "critical" for row in neg))
            # Per-point message preserved.
            self.assertTrue(all("negative intensity" in row["message"] for row in neg))

    def test_explicit_raw_spectrum_profile_keeps_critical(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            make_spectrum_batch(root, intensities=[1.0, -3.0, 2.0, -5.0, 1.0])
            result = tool_quality_check(
                make_context(root), {"experiment_dir": "data/batch_x", "qc_profile": "raw_spectrum"}
            )
            self.assertTrue(result.ok)
            neg = negative_findings(qc_rows(root))
            self.assertEqual(len(neg), 2)
            self.assertTrue(all(row["severity"] == "critical" for row in neg))

    def test_baseline_corrected_collapses_negatives_to_one_warning(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            make_spectrum_batch(root, intensities=[1.0, -3.0, 2.0, -5.0, 1.0, -0.5, 3.0])
            result = tool_quality_check(
                make_context(root),
                {"experiment_dir": "data/batch_x", "qc_profile": "baseline_corrected"},
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.metadata["qc_profile"], "baseline_corrected")
            neg = negative_findings(qc_rows(root))
            # Collapsed to a single warning, no criticals.
            self.assertEqual(len(neg), 1)
            self.assertEqual(neg[0]["severity"], "warning")
            self.assertIn("baseline-corrected", neg[0]["message"].lower())
            self.assertIn("3", neg[0]["message"])  # count reported
            self.assertIn("count=3", neg[0]["evidence"])

    def test_processed_spectrum_collapses_negatives_to_one_warning(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            make_spectrum_batch(root, intensities=[1.0, -3.0, 2.0, -5.0, 1.0])
            result = tool_quality_check(
                make_context(root),
                {"experiment_dir": "data/batch_x", "qc_profile": "processed_spectrum"},
            )
            self.assertTrue(result.ok)
            neg = negative_findings(qc_rows(root))
            self.assertEqual(len(neg), 1)
            self.assertEqual(neg[0]["severity"], "warning")
            self.assertIn("processed spectra", neg[0]["message"].lower())

    def test_baseline_corrected_still_records_zero_negatives_when_none(self):
        # No negatives -> no negative_intensity finding at all, even under baseline_corrected.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            make_spectrum_batch(root, intensities=[float(i) for i in range(1, 15)])
            tool_quality_check(
                make_context(root),
                {"experiment_dir": "data/batch_x", "qc_profile": "baseline_corrected"},
            )
            self.assertEqual(negative_findings(qc_rows(root)), [])

    def test_unknown_qc_profile_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            make_spectrum_batch(root, intensities=[1.0, -3.0, 2.0])
            result = tool_quality_check(
                make_context(root), {"experiment_dir": "data/batch_x", "qc_profile": "bogus"}
            )
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "invalid_args")

    def test_qc_profile_is_persisted_in_qc_summary_csv(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            make_spectrum_batch(root, intensities=[1.0, -3.0, 2.0])
            tool_quality_check(
                make_context(root),
                {"experiment_dir": "data/batch_x", "qc_profile": "processed_spectrum"},
            )
            rows = qc_rows(root)
            self.assertTrue(rows)  # has a header + at least the negative finding
            self.assertTrue(all(row.get("qc_profile") == "processed_spectrum" for row in rows))


class QcProfileReportTests(unittest.TestCase):
    def _run(self, root: Path, profile: str) -> None:
        make_spectrum_batch(root, intensities=[1.0, -3.0, 2.0, -5.0, 1.0, -0.5, 3.0])
        tool_quality_check(
            make_context(root),
            {"experiment_dir": "data/batch_x", "qc_profile": profile},
        )

    def test_report_displays_qc_profile_and_zh_note(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._run(root, "baseline_corrected")
            tool_generate_report(make_context(root), {"batch_id": "batch_x", "lang": "zh"})
            text = (root / "reports" / "batch_x_qc_report.md").read_text(encoding="utf-8")
            self.assertIn("QC profile: baseline_corrected", text)
            self.assertIn("基线噪声", text)

    def test_report_displays_en_note_for_processed_spectrum(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._run(root, "processed_spectrum")
            tool_generate_report(make_context(root), {"batch_id": "batch_x", "lang": "en"})
            text = (root / "reports" / "batch_x_qc_report.md").read_text(encoding="utf-8")
            self.assertIn("QC profile: processed_spectrum", text)
            self.assertIn("baseline subtraction", text)

    def test_report_omits_note_under_raw_spectrum(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._run(root, "raw_spectrum")
            tool_generate_report(make_context(root), {"batch_id": "batch_x", "lang": "zh"})
            text = (root / "reports" / "batch_x_qc_report.md").read_text(encoding="utf-8")
            self.assertIn("QC profile: raw_spectrum", text)
            self.assertNotIn("基线噪声", text)

    def test_report_falls_back_to_raw_spectrum_for_old_qc_summary(self):
        # A qc_summary.csv written before this feature (no qc_profile column)
        # must render as raw_spectrum (default), not crash.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            qc = root / "outputs" / "batch_x" / "qc_summary.csv"
            qc.parent.mkdir(parents=True, exist_ok=True)
            qc.write_text(
                "finding_id,batch_id,sample_id,file,check,severity,status,message,evidence\n"
                "F0001,batch_x,s1,data/batch_x/spectra/s1_raman.csv,"
                "negative_intensity,critical,fail,row 2 has negative intensity,-3\n",
                encoding="utf-8",
            )
            result = tool_generate_report(make_context(root), {"batch_id": "batch_x"})
            self.assertTrue(result.ok)
            self.assertEqual(result.metadata["qc_profile"], "raw_spectrum")
            text = (root / "reports" / "batch_x_qc_report.md").read_text(encoding="utf-8")
            self.assertIn("QC profile: raw_spectrum", text)


class RealMofDataProfileTests(unittest.TestCase):
    """Cross-validation against the real public MOF Raman batch (IBM uRaman-Dataset).

    Mg-MOF74 is baseline-corrected and has 989 negative intensities; HKUST-1 has none.
    """

    def setUp(self) -> None:
        if not MOF_DATA.is_dir():
            self.skipTest(f"real MOF data not present at {MOF_DATA}")
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        shutil.copytree(MOF_DATA, root / "data" / "batch_public_mof_001")
        self.root = root

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _count_negatives(self, sample_id: str) -> int:
        path = self.root / "data" / "batch_public_mof_001" / "spectra" / f"{sample_id}_raman.csv"
        with path.open("r", encoding="utf-8", newline="") as handle:
            return sum(1 for row in csv.DictReader(handle) if float(row["intensity"]) < 0)

    def _run(self, profile: str | None) -> list[dict[str, str]]:
        args = {"experiment_dir": "data/batch_public_mof_001", "batch_id": "batch_public_mof_001"}
        if profile is not None:
            args["qc_profile"] = profile
        result = tool_quality_check(make_context(self.root), args)
        self.assertTrue(result.ok, result.text)
        return qc_rows(self.root, "batch_public_mof_001")

    def test_baseline_corrected_does_not_explode_critical_negatives(self):
        rows = self._run("baseline_corrected")
        mg_neg = [
            r for r in rows if r["sample_id"] == "Mg-MOF74" and r["check"] == "negative_intensity"
        ]
        hk_neg = [
            r for r in rows if r["sample_id"] == "HKUST-1" and r["check"] == "negative_intensity"
        ]
        # No critical negative_intensity for Mg-MOF74; exactly one collapsed warning.
        self.assertEqual([r for r in mg_neg if r["severity"] == "critical"], [])
        self.assertEqual(len(mg_neg), 1)
        self.assertEqual(mg_neg[0]["severity"], "warning")
        self.assertIn("baseline-corrected", mg_neg[0]["message"].lower())
        # HKUST-1 has no negatives at all.
        self.assertEqual(hk_neg, [])

    def test_raw_spectrum_default_still_flags_real_negatives_as_critical(self):
        # Contrast: under the default raw profile, every real negative stays critical
        # (the rule still fires on real data; only the profile changes the severity).
        rows = self._run(None)
        mg_neg = [
            r for r in rows if r["sample_id"] == "Mg-MOF74" and r["check"] == "negative_intensity"
        ]
        self.assertTrue(mg_neg)
        self.assertTrue(all(r["severity"] == "critical" for r in mg_neg))
        self.assertEqual(len(mg_neg), self._count_negatives("Mg-MOF74"))


if __name__ == "__main__":
    unittest.main()

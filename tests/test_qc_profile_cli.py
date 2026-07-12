from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.cli import build_agent, build_arg_parser
from pico.providers import FakeModelClient
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.workspace import WorkspaceContext

VALID_PROFILES = ["raw_spectrum", "processed_spectrum", "baseline_corrected"]


class QcProfileArgParserTests(unittest.TestCase):
    def test_arg_parser_default_qc_profile_is_raw_spectrum(self):
        parser = build_arg_parser()
        args = parser.parse_args(["x"])
        self.assertEqual(args.qc_profile, "raw_spectrum")

    def test_arg_parser_accepts_each_valid_profile(self):
        parser = build_arg_parser()
        for profile in VALID_PROFILES:
            args = parser.parse_args(["--qc-profile", profile, "x"])
            self.assertEqual(args.qc_profile, profile)

    def test_arg_parser_rejects_unknown_qc_profile(self):
        parser = build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--qc-profile", "bogus", "x"])


class PicoQcProfileThreadingTests(unittest.TestCase):
    def _pico(self, root: Path, **kwargs) -> Pico:
        return Pico(
            workspace=WorkspaceContext.build(root),
            model_client=FakeModelClient([]),
            session_store=SessionStore(root),
            run_store=RunStore(root),
            **kwargs,
        )

    def test_qc_profile_threads_to_tool_context_default_qc_profile(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pico = self._pico(root, qc_profile="baseline_corrected")
            self.assertEqual(pico.qc_profile, "baseline_corrected")
            self.assertEqual(pico.tool_context().default_qc_profile, "baseline_corrected")

    def test_pico_default_qc_profile_is_raw_spectrum(self):
        # Backward compatibility: Pico without qc_profile defaults to "raw_spectrum".
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pico = self._pico(root)
            self.assertEqual(pico.qc_profile, "raw_spectrum")
            self.assertEqual(pico.tool_context().default_qc_profile, "raw_spectrum")

    def test_spawn_delegate_inherits_qc_profile(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pico = self._pico(
                root,
                qc_profile="processed_spectrum",
                approval="auto",
                max_steps=1,
            )
            result = pico.spawn_delegate("just say done", 1)
            self.assertTrue(result.ok)
            # The child Pico is not exposed, but the parent's qc_profile is unchanged.
            self.assertEqual(pico.qc_profile, "processed_spectrum")


class BuildAgentQcProfileThreadingTests(unittest.TestCase):
    def test_build_agent_threads_qc_profile_flag_to_pico(self):
        # End-to-end: --qc-profile baseline_corrected -> args.qc_profile -> build_agent
        # -> Pico.qc_profile -> tool_context().default_qc_profile == "baseline_corrected".
        with TemporaryDirectory() as directory:
            root = Path(directory)
            parser = build_arg_parser()
            args = parser.parse_args(
                [
                    "--cwd",
                    str(root),
                    "--provider",
                    "fake",
                    "--qc-profile",
                    "baseline_corrected",
                    "x",
                ]
            )
            agent = build_agent(args)
            self.assertEqual(agent.qc_profile, "baseline_corrected")
            self.assertEqual(agent.tool_context().default_qc_profile, "baseline_corrected")

    def test_build_agent_defaults_to_raw_spectrum_when_flag_omitted(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            parser = build_arg_parser()
            args = parser.parse_args(["--cwd", str(root), "--provider", "fake", "x"])
            agent = build_agent(args)
            self.assertEqual(agent.qc_profile, "raw_spectrum")


class QcProfileDefaultReachesQualityCheckTests(unittest.TestCase):
    """The CLI default must reach the quality_check tool when the LLM omits qc_profile,
    and an explicit tool qc_profile still wins (mirror of generate_report's lang)."""

    def _make_batch(self, root: Path) -> Path:
        batch = root / "data" / "batch_x"
        spectra = batch / "spectra"
        spectra.mkdir(parents=True, exist_ok=True)
        (batch / "metadata.csv").write_text("sample_id,method\ns1,raman\n", encoding="utf-8")
        (spectra / "s1_raman.csv").write_text(
            "x,intensity\n1,1\n2,-3\n3,2\n4,-5\n5,1\n", encoding="utf-8"
        )
        return batch

    def _run_quality_check(self, root: Path, *, qc_profile: str) -> list[dict[str, str]]:
        parser = build_arg_parser()
        args = parser.parse_args(
            ["--cwd", str(root), "--provider", "fake", "--qc-profile", qc_profile, "x"]
        )
        agent = build_agent(args)
        # LLM calls quality_check WITHOUT a qc_profile arg -> CLI default must apply.
        agent.model_client = FakeModelClient(
            [
                '<tool>{"name":"quality_check","args":{"experiment_dir":"data/batch_x","batch_id":"batch_x"}}</tool>',
                "<final>done</final>",
            ]
        )
        agent.ask("qc the batch")
        qc_path = root / "outputs" / "batch_x" / "qc_summary.csv"
        with qc_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_baseline_corrected_default_reaches_tool(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_batch(root)
            rows = self._run_quality_check(root, qc_profile="baseline_corrected")
            neg = [r for r in rows if r["check"] == "negative_intensity"]
            self.assertEqual(len(neg), 1)
            self.assertEqual(neg[0]["severity"], "warning")
            self.assertEqual(neg[0]["qc_profile"], "baseline_corrected")

    def test_raw_spectrum_default_stays_critical_in_tool(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_batch(root)
            rows = self._run_quality_check(root, qc_profile="raw_spectrum")
            neg = [r for r in rows if r["check"] == "negative_intensity"]
            self.assertEqual(len(neg), 2)  # one per negative point
            self.assertTrue(all(r["severity"] == "critical" for r in neg))
            self.assertTrue(all(r["qc_profile"] == "raw_spectrum" for r in neg))

    def test_explicit_tool_qc_profile_wins_over_cli_default(self):
        # CLI default is raw_spectrum, but the tool call passes baseline_corrected -> wins.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_batch(root)
            parser = build_arg_parser()
            args = parser.parse_args(
                ["--cwd", str(root), "--provider", "fake", "x"]  # default raw_spectrum
            )
            agent = build_agent(args)
            agent.model_client = FakeModelClient(
                [
                    '<tool>{"name":"quality_check","args":{"experiment_dir":"data/batch_x",'
                    '"batch_id":"batch_x","qc_profile":"baseline_corrected"}}</tool>',
                    "<final>done</final>",
                ]
            )
            agent.ask("qc the batch")
            qc_path = root / "outputs" / "batch_x" / "qc_summary.csv"
            with qc_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            neg = [r for r in rows if r["check"] == "negative_intensity"]
            self.assertEqual(len(neg), 1)
            self.assertEqual(neg[0]["severity"], "warning")
            self.assertEqual(neg[0]["qc_profile"], "baseline_corrected")


if __name__ == "__main__":
    unittest.main()

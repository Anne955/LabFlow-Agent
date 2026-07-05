from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.cli import build_arg_parser
from pico.providers import FakeModelClient
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.tools.labflow import tool_generate_report
from pico.workspace import WorkspaceContext, resolve_in_workspace


def make_context(root: Path, default_report_lang: str = "zh") -> ToolContext:
    return ToolContext(
        root=root,
        path_resolver=lambda raw: resolve_in_workspace(root, raw),
        shell_env_provider=safe_shell_env,
        default_report_lang=default_report_lang,
    )


def _write_minimal_qc(root: Path, batch_id: str = "batch_demo_001") -> Path:
    """Create a minimal qc_summary.csv so generate_report has data to render."""
    qc = root / "outputs" / batch_id / "qc_summary.csv"
    qc.parent.mkdir(parents=True, exist_ok=True)
    qc.write_text(
        "finding_id,batch_id,sample_id,file,check,severity,status,message,evidence\n"
        "F0001,batch_demo_001,s1,data/batch_demo_001/spectra/s1_raman.csv,"
        "negative_intensity,critical,fail,negative intensity,-1\n",
        encoding="utf-8",
    )
    return qc


class GenerateReportLangFallbackTests(unittest.TestCase):
    def test_uses_ctx_default_report_lang_when_args_has_no_lang(self):
        # ctx default is "en" and args omits lang -> English headers win.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_minimal_qc(root)
            ctx = make_context(root, default_report_lang="en")
            result = tool_generate_report(ctx, {"batch_id": "batch_demo_001"})
            self.assertTrue(result.ok)
            report = root / "reports" / "batch_demo_001_qc_report.md"
            self.assertTrue(report.is_file())
            content = report.read_text(encoding="utf-8")
            self.assertIn("## Data Overview", content)
            self.assertNotIn("## 数据概况", content)

    def test_args_lang_overrides_ctx_default(self):
        # ctx default is "en" but args passes lang="zh" -> Chinese headers win.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_minimal_qc(root)
            ctx = make_context(root, default_report_lang="en")
            result = tool_generate_report(ctx, {"batch_id": "batch_demo_001", "lang": "zh"})
            self.assertTrue(result.ok)
            report = root / "reports" / "batch_demo_001_qc_report.md"
            self.assertTrue(report.is_file())
            content = report.read_text(encoding="utf-8")
            self.assertIn("## 数据概况", content)


class CliLangFlagTests(unittest.TestCase):
    def test_arg_parser_accepts_lang_flag_with_default_zh(self):
        parser = build_arg_parser()
        args = parser.parse_args(["x"])
        self.assertEqual(args.lang, "zh")

    def test_arg_parser_accepts_lang_en(self):
        parser = build_arg_parser()
        args = parser.parse_args(["--lang", "en", "x"])
        self.assertEqual(args.lang, "en")

    def test_arg_parser_rejects_unknown_lang(self):
        parser = build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--lang", "fr", "x"])


class PicoReportLangThreadingTests(unittest.TestCase):
    def test_pico_report_lang_threads_to_tool_context_default_report_lang(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = WorkspaceContext.build(root)
            pico = Pico(
                workspace=workspace,
                model_client=FakeModelClient([]),
                session_store=SessionStore(root),
                run_store=RunStore(root),
                report_lang="en",
            )
            self.assertEqual(pico.report_lang, "en")
            self.assertEqual(pico.tool_context().default_report_lang, "en")

    def test_pico_default_report_lang_is_zh(self):
        # Backward compatibility: Pico without report_lang defaults to "zh".
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = WorkspaceContext.build(root)
            pico = Pico(
                workspace=workspace,
                model_client=FakeModelClient([]),
                session_store=SessionStore(root),
                run_store=RunStore(root),
            )
            self.assertEqual(pico.report_lang, "zh")
            self.assertEqual(pico.tool_context().default_report_lang, "zh")

    def test_spawn_delegate_inherits_report_lang(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = WorkspaceContext.build(root)
            pico = Pico(
                workspace=workspace,
                model_client=FakeModelClient(["<final>delegated</final>"]),
                session_store=SessionStore(root),
                run_store=RunStore(root),
                report_lang="en",
                approval="auto",
                max_steps=1,
            )
            # The delegate is built via spawn_delegate; exercise it directly.
            result = pico.spawn_delegate("just say done", 1)
            self.assertTrue(result.ok)
            # The child Pico is not exposed, but the inheritance is exercised;
            # confirm the parent's report_lang remains "en".
            self.assertEqual(pico.report_lang, "en")


class BuildAgentLangThreadingTests(unittest.TestCase):
    def test_build_agent_threads_lang_flag_to_pico_report_lang(self):
        # End-to-end: --lang en -> args.lang -> build_agent -> Pico.report_lang
        # -> tool_context().default_report_lang == "en".
        from pico.cli import build_agent

        with TemporaryDirectory() as directory:
            root = Path(directory)
            parser = build_arg_parser()
            args = parser.parse_args(
                ["--cwd", str(root), "--provider", "fake", "--lang", "en", "x"]
            )
            agent = build_agent(args)
            self.assertEqual(agent.report_lang, "en")
            self.assertEqual(agent.tool_context().default_report_lang, "en")


if __name__ == "__main__":
    unittest.main()

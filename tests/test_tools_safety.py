from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.tool_executor import ToolExecutor
from pico.tools import build_generic_tool_registry as build_legacy_tool_registry
from pico.workspace import resolve_in_workspace


def make_executor(tmp_path: Path, *, approval: str = "auto", read_only: bool = False) -> ToolExecutor:
    ctx = ToolContext(
        root=tmp_path,
        path_resolver=lambda raw: resolve_in_workspace(tmp_path, raw),
        shell_env_provider=safe_shell_env,
    )
    return ToolExecutor(build_legacy_tool_registry(ctx), context=ctx, approval=approval, read_only=read_only)


class ToolSafetyTests(unittest.TestCase):
    def test_path_escape_is_rejected(self):
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            executor = make_executor(tmp_path)
            result = executor.execute("read_file", {"path": "../outside.txt"})
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "path_escape")

    def test_read_only_blocks_write(self):
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            executor = make_executor(tmp_path, read_only=True)
            result = executor.execute("write_file", {"path": "a.txt", "content": "hello"})
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "read_only")

    def test_approval_never_blocks_shell(self):
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            executor = make_executor(tmp_path, approval="never")
            result = executor.execute("run_shell", {"command": "python --version"})
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "approval_denied")

    def test_patch_requires_exactly_one_match(self):
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / "a.txt").write_text("old old", encoding="utf-8")
            executor = make_executor(tmp_path)
            result = executor.execute("patch_file", {"path": "a.txt", "old_text": "old", "new_text": "new"})
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "ambiguous_patch")

    def test_repeated_identical_tool_call_is_rejected(self):
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
            executor = make_executor(tmp_path)
            self.assertTrue(executor.execute("read_file", {"path": "a.txt"}).ok)
            result = executor.execute("read_file", {"path": "a.txt"})
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "repeated_tool_call")

    def test_run_shell_uses_limited_environment(self):
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            old = os.environ.get("SECRET_TOKEN")
            os.environ["SECRET_TOKEN"] = "supersecretvalue"
            try:
                executor = make_executor(tmp_path)
                command = f"{sys.executable} -c \"import os; print(os.environ.get('SECRET_TOKEN', 'missing'))\""
                result = executor.execute("run_shell", {"command": command})
                self.assertTrue(result.ok)
                self.assertIn("missing", result.text)
                self.assertNotIn("supersecretvalue", result.text)
            finally:
                if old is None:
                    os.environ.pop("SECRET_TOKEN", None)
                else:
                    os.environ["SECRET_TOKEN"] = old

    @unittest.skipIf(sys.platform.startswith("win"), "symlink privileges vary on Windows")
    def test_symlink_escape_is_rejected(self):
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            outside = tmp_path.parent / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            (tmp_path / "link.txt").symlink_to(outside)
            executor = make_executor(tmp_path)
            result = executor.execute("read_file", {"path": "link.txt"})
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "path_escape")


if __name__ == "__main__":
    unittest.main()

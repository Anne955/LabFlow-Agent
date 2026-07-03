from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import DOC_FILENAMES, IGNORED_DIRS


def clip(text: str, limit: int, marker: str = "\n... [clipped] ...\n") -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    if limit <= len(marker) + 20:
        return text[:limit]
    head = (limit - len(marker)) // 2
    tail = limit - len(marker) - head
    return text[:head] + marker + text[-tail:]


def run_git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def discover_repo_root(cwd: Path) -> tuple[Path, bool]:
    output = run_git(cwd, "rev-parse", "--show-toplevel")
    if output:
        return Path(output).resolve(), True
    return cwd.resolve(), False


def resolve_in_workspace(root: Path, raw_path: str) -> Path:
    if not raw_path:
        raw_path = "."
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {raw_path}") from exc
    return resolved_candidate


def file_freshness(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return "missing"
    return hashlib.sha256(data).hexdigest()


@dataclass
class WorkspaceContext:
    cwd: Path
    repo_root: Path
    is_git_repo: bool
    branch: str = ""
    default_branch: str = ""
    status: str = ""
    recent_commits: list[str] = field(default_factory=list)
    project_docs: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, cwd: str | Path) -> "WorkspaceContext":
        requested = Path(cwd).resolve()
        repo_root, is_git_repo = discover_repo_root(requested)
        branch = run_git(repo_root, "branch", "--show-current") if is_git_repo else ""
        default_branch = ""
        if is_git_repo:
            default_ref = run_git(repo_root, "symbolic-ref", "refs/remotes/origin/HEAD")
            default_branch = default_ref.rsplit("/", 1)[-1] if default_ref else ""
        status = run_git(repo_root, "status", "--short") if is_git_repo else ""
        commits_text = run_git(repo_root, "log", "--oneline", "-5") if is_git_repo else ""
        recent_commits = [line for line in commits_text.splitlines() if line]
        project_docs = read_project_docs(requested, repo_root)
        return cls(
            cwd=requested,
            repo_root=repo_root,
            is_git_repo=is_git_repo,
            branch=branch,
            default_branch=default_branch,
            status=status,
            recent_commits=recent_commits,
            project_docs=project_docs,
        )

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        parts = [
            str(self.repo_root),
            str(self.cwd),
            str(self.is_git_repo),
            self.branch,
            self.default_branch,
            self.status,
            "\n".join(self.recent_commits),
        ]
        for name in sorted(self.project_docs):
            parts.append(name)
            parts.append(hashlib.sha256(self.project_docs[name].encode("utf-8")).hexdigest())
        digest.update("\0".join(parts).encode("utf-8"))
        return digest.hexdigest()

    def text(self, max_doc_chars: int = 1200) -> str:
        lines = [
            "# Workspace",
            f"cwd: {self.cwd}",
            f"repo_root: {self.repo_root}",
            f"git_repo: {self.is_git_repo}",
        ]
        if self.branch:
            lines.append(f"branch: {self.branch}")
        if self.default_branch:
            lines.append(f"default_branch: {self.default_branch}")
        if self.status:
            lines.append("\n## Git status")
            lines.append(clip(self.status, 1500))
        if self.recent_commits:
            lines.append("\n## Recent commits")
            lines.extend(self.recent_commits[:5])
        if self.project_docs:
            lines.append("\n## Project docs")
            for name, content in sorted(self.project_docs.items()):
                lines.append(f"\n### {name}")
                lines.append(clip(content, max_doc_chars))
        return "\n".join(lines)


def read_project_docs(cwd: Path, repo_root: Path) -> dict[str, str]:
    docs: dict[str, str] = {}
    for base in dict.fromkeys([repo_root.resolve(), cwd.resolve()]):
        for filename in DOC_FILENAMES:
            path = base / filename
            if not path.is_file():
                continue
            rel = os.path.relpath(path, repo_root)
            if rel in docs:
                continue
            try:
                docs[rel] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return docs


def iter_workspace_files(root: Path, start: Path):
    for current, dirs, files in os.walk(start):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for file_name in files:
            path = Path(current) / file_name
            try:
                path.relative_to(root)
            except ValueError:
                continue
            yield path

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..workspace import file_freshness


@dataclass
class FileSummary:
    path: str
    summary: str
    freshness: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "summary": self.summary, "freshness": self.freshness}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileSummary:
        return cls(str(data["path"]), str(data.get("summary", "")), str(data.get("freshness", "")))


@dataclass
class EpisodicNote:
    text: str
    tags: list[str] = field(default_factory=list)
    source: str = "runtime"

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "tags": self.tags, "source": self.source}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EpisodicNote:
        return cls(str(data.get("text", "")), list(data.get("tags", [])), str(data.get("source", "runtime")))


@dataclass
class LayeredMemory:
    task_summary: str = ""
    recent_files: list[str] = field(default_factory=list)
    file_summaries: dict[str, FileSummary] = field(default_factory=dict)
    episodic_notes: list[EpisodicNote] = field(default_factory=list)
    max_recent_files: int = 8
    max_notes: int = 20

    def set_task_summary(self, text: str) -> None:
        self.task_summary = text.strip()

    def remember_file(self, path: str) -> None:
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        del self.recent_files[self.max_recent_files :]

    def set_file_summary(self, path: str, summary: str, freshness: str) -> None:
        self.file_summaries[path] = FileSummary(path, summary.strip(), freshness)
        self.remember_file(path)

    def invalidate_file_summary(self, path: str) -> None:
        self.file_summaries.pop(path, None)
        self.remember_file(path)

    def append_note(self, text: str, tags: list[str] | None = None, source: str = "runtime") -> None:
        self.episodic_notes.insert(0, EpisodicNote(text.strip(), tags or [], source))
        del self.episodic_notes[self.max_notes :]

    def retrieval_candidates(self, query: str, limit: int = 3) -> list[EpisodicNote]:
        terms = {part.lower() for part in query.split() if len(part) >= 3}
        scored: list[tuple[int, EpisodicNote]] = []
        for note in self.episodic_notes:
            haystack = " ".join([note.text, *note.tags]).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, note))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [note for _, note in scored[:limit]]

    def render(self, root: Path, query: str = "") -> str:
        sections: list[str] = []
        if self.task_summary:
            sections.append(f"## Working task\n{self.task_summary}")
        if self.recent_files:
            sections.append("## Recent files\n" + "\n".join(f"- {path}" for path in self.recent_files[:5]))
        fresh_summaries = []
        for path, summary in sorted(self.file_summaries.items()):
            current = root / path
            if current.is_file() and file_freshness(current) == summary.freshness:
                fresh_summaries.append(f"- {path}: {summary.summary}")
        if fresh_summaries:
            sections.append("## File summaries\n" + "\n".join(fresh_summaries[:8]))
        candidates = self.retrieval_candidates(query) if query else self.episodic_notes[:3]
        if candidates:
            sections.append("## Relevant notes\n" + "\n".join(f"- {note.text}" for note in candidates))
        return "\n\n".join(sections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_summary": self.task_summary,
            "recent_files": self.recent_files,
            "file_summaries": {path: summary.to_dict() for path, summary in self.file_summaries.items()},
            "episodic_notes": [note.to_dict() for note in self.episodic_notes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LayeredMemory:
        if not data:
            return cls()
        memory = cls(task_summary=str(data.get("task_summary", "")))
        memory.recent_files = list(data.get("recent_files", []))
        memory.file_summaries = {
            str(path): FileSummary.from_dict(summary)
            for path, summary in dict(data.get("file_summaries", {})).items()
        }
        memory.episodic_notes = [EpisodicNote.from_dict(note) for note in data.get("episodic_notes", [])]
        return memory


class DurableMemoryStore:
    TOPICS = ("project-conventions.md", "key-decisions.md", "dependency-facts.md", "user-preferences.md")

    def __init__(self, root: Path):
        self.root = root / ".pico" / "memory"
        self.topics = self.root / "topics"

    def ensure(self) -> None:
        self.topics.mkdir(parents=True, exist_ok=True)
        index = self.root / "MEMORY.md"
        if not index.exists():
            index.write_text("# Pico memory\n\n", encoding="utf-8")
        for topic in self.TOPICS:
            path = self.topics / topic
            if not path.exists():
                path.write_text(f"# {topic.removesuffix('.md').replace('-', ' ').title()}\n\n", encoding="utf-8")

    def read_all(self, max_chars: int = 3000) -> str:
        self.ensure()
        chunks = []
        for path in [self.root / "MEMORY.md", *sorted(self.topics.glob("*.md"))]:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            chunks.append(f"## {path.relative_to(self.root)}\n{text.strip()}")
        joined = "\n\n".join(chunks)
        return joined[:max_chars]

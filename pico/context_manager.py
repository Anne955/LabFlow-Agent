from __future__ import annotations

from typing import Any, Protocol

from .config import DEFAULT_CONTEXT_BUDGET
from .prompt_prefix import PromptPrefix
from .workspace import clip


def build_prompt(
    prefix: PromptPrefix,
    memory_text: str,
    relevant_memory_text: str,
    history_text: str,
    user_message: str,
    budget: int = DEFAULT_CONTEXT_BUDGET,
    suggested_plan: str = "",
) -> tuple[str, dict[str, Any]]:
    sections: dict[str, str] = {
        "prefix": prefix.text,
        "suggested_plan": suggested_plan.strip(),
        "memory": memory_text.strip(),
        "relevant_memory": relevant_memory_text.strip(),
        "history": history_text.strip(),
        "current_request": user_message.strip(),
    }
    reductions: dict[str, int] = {}
    total = sum(len(text) for text in sections.values())
    if total > budget:
        strategy = PriorityTruncation()
        truncated = strategy.truncate(sections, budget)
        for key, text in truncated.items():
            if len(text) < len(sections[key]):
                reductions[key] = len(sections[key]) - len(text)
            sections[key] = text
    prompt = ""
    for section_name in [
        "prefix",
        "suggested_plan",
        "memory",
        "relevant_memory",
        "history",
        "current_request",
    ]:
        text = sections.get(section_name, "")
        if text:
            prompt += f"<{section_name}>\n{text}\n</{section_name}>\n\n"
    prompt = prompt.strip()
    section_chars = {name: len(text) for name, text in sections.items()}
    metadata = {
        "prompt_chars": len(prompt),
        "section_chars": section_chars,
        "budget_reductions": reductions,
        "prefix_hash": prefix.hash,
        "workspace_fingerprint": prefix.workspace_fingerprint,
        "tool_signature": prefix.tool_signature,
        "prompt_cache_key": f"pico:{prefix.hash}:{prefix.tool_signature}",
    }
    return prompt, metadata


class TruncationStrategy(Protocol):
    def truncate(self, sections: dict[str, str], budget: int) -> dict[str, str]: ...


class PriorityTruncation:
    """Trims sections in a fixed priority order (the original behavior)."""

    def truncate(self, sections: dict[str, str], budget: int) -> dict[str, str]:
        order = ["relevant_memory", "suggested_plan", "history", "memory", "prefix"]
        limits = {
            "relevant_memory": int(budget * 0.1),
            "suggested_plan": int(budget * 0.1),
            "history": int(budget * 0.2),
            "memory": int(budget * 0.13),
            "prefix": int(budget * 0.3),
        }
        total = sum(len(text) for text in sections.values())
        if total <= budget:
            return dict(sections)
        out = dict(sections)
        for key in order:
            if total <= budget:
                break
            text = out[key]
            limit = max(limits.get(key, 200), 80)
            if len(text) > limit:
                total -= len(text) - limit
                out[key] = clip(text, limit)
        return out


class SmartTruncation:
    """Adjusts trim priority by intent (e.g. keep more history for explanations)."""

    def __init__(self, intent: str = "") -> None:
        self.intent = intent

    def truncate(self, sections: dict[str, str], budget: int) -> dict[str, str]:
        if self.intent == "explain_finding":
            order = ["suggested_plan", "memory", "prefix", "relevant_memory", "history"]
        else:
            order = ["relevant_memory", "suggested_plan", "memory", "history", "prefix"]
        limits = {
            "relevant_memory": int(budget * 0.1),
            "suggested_plan": int(budget * 0.1),
            "history": int(budget * 0.25),
            "memory": int(budget * 0.13),
            "prefix": int(budget * 0.3),
        }
        total = sum(len(text) for text in sections.values())
        if total <= budget:
            return dict(sections)
        out = dict(sections)
        for key in order:
            if total <= budget:
                break
            text = out[key]
            limit = max(limits.get(key, 200), 80)
            if len(text) > limit:
                total -= len(text) - limit
                out[key] = clip(text, limit)
        return out

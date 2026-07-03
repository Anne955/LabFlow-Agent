from __future__ import annotations

from pathlib import Path
from typing import Any

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
) -> tuple[str, dict[str, Any]]:
    sections: dict[str, str] = {
        "prefix": prefix.text,
        "memory": memory_text.strip(),
        "relevant_memory": relevant_memory_text.strip(),
        "history": history_text.strip(),
        "current_request": user_message.strip(),
    }
    reductions: dict[str, int] = {}
    total = sum(len(text) for text in sections.values())
    if total > budget:
        order = ["relevant_memory", "history", "memory", "prefix"]
        limits = {
            "relevant_memory": int(budget * 0.1),
            "history": int(budget * 0.2),
            "memory": int(budget * 0.13),
            "prefix": int(budget * 0.3),
        }
        for key in order:
            if total <= budget:
                break
            text = sections[key]
            limit = max(limits.get(key, 200), 80)
            if len(text) > limit:
                reductions[key] = len(text) - limit
                sections[key] = clip(text, limit)
                total = sum(len(t) for t in sections.values())
    prompt = ""
    for section_name in ["prefix", "memory", "relevant_memory", "history", "current_request"]:
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
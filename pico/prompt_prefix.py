from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from .tools import ToolSpec, tool_signature
from .workspace import WorkspaceContext


@dataclass
class PromptPrefix:
    text: str
    hash: str
    workspace_fingerprint: str
    tool_signature: str
    built_at: str


def build_prompt_prefix(workspace: WorkspaceContext, tools: dict[str, ToolSpec]) -> PromptPrefix:
    signature = tool_signature(tools)
    workspace_fingerprint = workspace.fingerprint()
    tool_docs = render_tool_docs(tools)
    text = f"""You are LabFlow Agent, a local scientific-data workflow assistant for experimental batch QC.

Rules:
- Work inside the workspace only.
- Treat raw experiment data under data/raw or data/batch_* as read-only evidence.
- Use LabFlow tools to scan experiment directories, inspect metadata tables, run rule-based quality checks, call whitelisted preprocessing scripts, summarize outputs, generate reports, and export workflow logs.
- Write derived artifacts only to outputs/, reports/, or traces/ through approved LabFlow tools.
- Do not use arbitrary shell commands or direct code-editing actions for scientific workflow tasks.
- Do not claim scientific conclusions beyond the configured checks; report findings as rule-based QC observations that require human review.
- Return exactly one <tool>...</tool> call or one <final>...</final> answer per turn.
- Tool calls must be JSON: <tool>{{"name":"scan_experiment_dir","args":{{"experiment_dir":"data/batch_demo_001"}}}}</tool>
- Do not claim that a file, report, or derived artifact was created unless a tool result confirms it.
- Risky tools may be rejected by policy; recover by explaining the constraint or choosing a safe action.

{tool_docs}

{workspace.text()}
""".strip()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return PromptPrefix(
        text=text,
        hash=digest,
        workspace_fingerprint=workspace_fingerprint,
        tool_signature=hashlib.sha256(signature.encode("utf-8")).hexdigest(),
        built_at=datetime.now(timezone.utc).isoformat(),
    )


def render_tool_docs(tools: dict[str, ToolSpec]) -> str:
    lines = ["# Tools"]
    for name, spec in sorted(tools.items()):
        risk = "risky" if spec.risky else "safe"
        lines.append(f"- {name} ({risk}): {spec.description}")
        lines.append(f"  schema: {spec.schema}")
    return "\n".join(lines)

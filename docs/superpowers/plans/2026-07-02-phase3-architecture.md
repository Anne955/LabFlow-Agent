# Phase 3: 架构完善 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Prerequisite:** Phases 1 and 2 complete.

**Goal:** Put the already-implemented intent/planner to work as an optional guidance layer in the runtime, decouple report content from the evaluator via a template, make context truncation pluggable, and reorganize the tool modules into a focused `tools/` package.

**Architecture:** (1) `build_plan()` from `pico.agent.planner` renders a `<suggested_plan>` section injected per-turn into the prompt — the LLM still decides whether to follow it. (2) A new `pico/report_template.py` holds section definitions; `generate_report` renders from it and `evaluate_qc.py` derives its required sections from the same source. (3) `TruncationStrategy` protocol in `context_manager.py` with the current behavior as the default strategy. (4) `pico/tools.py`, `labflow_tools.py`, `tool_registry.py` relocate into a `pico/tools/` package with thin re-export shims emitting `DeprecationWarning`.

**Tech Stack:** Python 3.10+, stdlib, `unittest`, `ruff`, `pyyaml` is NOT a dependency (workflows are loaded elsewhere; this phase adds no YAML parsing).

## Global Constraints

- The planner is advisory only — `--no-planner` must reproduce the exact pre-phase behavior (no `<suggested_plan>` section, identical prompt).
- Default report language is `zh` so existing reports and `evaluate_qc.py` expectations are unchanged.
- Public import paths `pico.tools`, `pico.labflow_tools`, `pico.tool_registry` must keep working (via shims) so no test or caller breaks.
- `pytest tests/` green after every task; `ruff check .` clean.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `pico/report_template.py` | Create | Canonical report section definitions (key + zh + en titles). |
| `pico/labflow_tools.py` | Modify | `tool_generate_report` renders from the template; accepts `lang`. |
| `pico/tool_registry.py` | Modify | `GENERATE_REPORT_SCHEMA` adds optional `lang`. |
| `evaluate_qc.py` | Modify | `REQUIRED_REPORT_SECTIONS` derived from `report_template`. |
| `pico/context_manager.py` | Modify | `TruncationStrategy` protocol + `PriorityTruncation` (current behavior) + `SmartTruncation`. |
| `pico/config.py` | Modify | `PICO_TRUNCATION_STRATEGY` env + `load_truncation_strategy()`. |
| `pico/runtime.py` | Modify | Compute & inject `<suggested_plan>`; `use_planner` flag. |
| `pico/agent/planner.py` | Modify | Add `render_plan(plan) -> str`. |
| `pico/cli.py` | Modify | `--no-planner`, `--lang` flags. |
| `pico/tools/` | Create package | `base.py`, `generic.py`, `labflow.py`, `registry.py`, `__init__.py`. |
| `pico/tools.py`, `labflow_tools.py`, `tool_registry.py` | Become shims | Re-export from `pico/tools/` with `DeprecationWarning`. |

---

## Task 1: Report template + evaluator decoupling

**Files:**
- Create: `pico/report_template.py`
- Modify: `pico/labflow_tools.py` (`tool_generate_report`)
- Modify: `pico/tool_registry.py` (`GENERATE_REPORT_SCHEMA`)
- Modify: `evaluate_qc.py:10-19`

**Interfaces:**
- Produces: `REPORT_SECTIONS: list[dict]` with `key`, `title_zh`, `title_en`; `section_title(key, lang)`; `required_section_titles(lang="zh")`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase3_report_template.py`:

```python
from __future__ import annotations

import unittest

from pico.report_template import REPORT_SECTIONS, required_section_titles, section_title


class ReportTemplateTests(unittest.TestCase):
    def test_has_all_expected_keys(self):
        keys = {s["key"] for s in REPORT_SECTIONS}
        for expected in {"data_overview", "metadata_check", "file_consistency", "numeric_anomaly", "preprocess_results", "abnormal_samples", "output_paths", "review_advice", "severity_counts"}:
            self.assertIn(expected, keys)

    def test_zh_titles_match_legacy(self):
        titles = required_section_titles("zh")
        self.assertIn("数据概况", titles)
        self.assertIn("metadata 检查", titles)

    def test_en_titles_available(self):
        self.assertEqual(section_title("data_overview", "en"), "Data Overview")

    def test_default_lang_is_zh(self):
        self.assertEqual(section_title("data_overview"), "数据概况")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase3_report_template.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pico.report_template'`.

- [ ] **Step 3: Create `pico/report_template.py`**

```python
from __future__ import annotations

REPORT_SECTIONS: list[dict[str, str]] = [
    {"key": "data_overview", "title_zh": "数据概况", "title_en": "Data Overview"},
    {"key": "metadata_check", "title_zh": "metadata 检查", "title_en": "Metadata Check"},
    {"key": "file_consistency", "title_zh": "文件一致性检查", "title_en": "File Consistency Check"},
    {"key": "numeric_anomaly", "title_zh": "数值异常检查", "title_en": "Numeric Anomaly Check"},
    {"key": "preprocess_results", "title_zh": "预处理结果", "title_en": "Preprocessing Results"},
    {"key": "abnormal_samples", "title_zh": "异常样本列表", "title_en": "Abnormal Sample List"},
    {"key": "output_paths", "title_zh": "输出路径", "title_en": "Output Paths"},
    {"key": "review_advice", "title_zh": "复核建议", "title_en": "Review Advice"},
    {"key": "severity_counts", "title_zh": "Severity counts", "title_en": "Severity counts"},
]

_BY_KEY = {s["key"]: s for s in REPORT_SECTIONS}


def section_title(key: str, lang: str = "zh") -> str:
    entry = _BY_KEY[key]
    return entry["title_en"] if lang == "en" else entry["title_zh"]


def required_section_titles(lang: str = "zh") -> list[str]:
    """Section titles the evaluator expects to find in a generated report."""
    skip = {"severity_counts"}
    return [section_title(s["key"], lang) for s in REPORT_SECTIONS if s["key"] not in skip]
```

- [ ] **Step 4: Run the new test**

Run: `python -m pytest tests/test_phase3_report_template.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor `tool_generate_report` to render titles from the template**

In `pico/labflow_tools.py`, add import near the top:

```python
from .report_template import section_title
```

In `tool_generate_report`, accept a `lang` and replace the hardcoded Chinese headers. Change the function signature line:

```python
def tool_generate_report(ctx: ToolContext, args: dict[str, object]) -> ToolResult:
    batch_id = sanitize_batch_id(str(args["batch_id"]))
    lang = str(args.get("lang") or "zh")
```

Then replace the `sections = [...]` list's header strings with `section_title(key, lang)` calls. The header lines become:

```python
    sections = [
        f"# LabFlow QC Report: {batch_id}",
        "",
        f"## {section_title('data_overview', lang)}",
        f"- Batch ID: {batch_id}",
        f"- QC summary: {relpath(ctx, qc_path)}",
        f"- Total findings: {len(rows)}",
        f"- Abnormal samples: {len(abnormal_samples)}",
        "",
        f"## {section_title('metadata_check', lang)}",
        _format_checks(by_check, ["missing_metadata_file", "unsupported_metadata_format", "missing_metadata_field", "missing_sample_id", "missing_metadata_value", "duplicate_sample_id"]),
        "",
        f"## {section_title('file_consistency', lang)}",
        _format_checks(by_check, ["missing_spectra_dir", "missing_spectra_file", "file_without_metadata", "invalid_filename"]),
        "",
        f"## {section_title('numeric_anomaly', lang)}",
        _format_checks(by_check, ["missing_spectrum_column", "missing_intensity", "non_numeric_intensity", "negative_intensity", "non_numeric_x", "x_not_monotonic", "too_few_points", "extreme_intensity"]),
        "",
        f"## {section_title('preprocess_results', lang)}",
        f"- Preprocessed CSV files: {len(preprocessed)}",
        f"- Preprocess success: {preprocess_success}",
        f"- Preprocess failed: {preprocess_failed}",
        f"- Preprocess skipped: {preprocess_skipped}",
        *[f"- {relpath(ctx, path)}" for path in preprocessed[:20]],
        "",
        f"## {section_title('abnormal_samples', lang)}",
        *(f"- {sample_id}" for sample_id in abnormal_samples[:50]),
        "" if abnormal_samples else "- No abnormal samples recorded.",
        "",
        f"## {section_title('output_paths', lang)}",
        f"- outputs: outputs/{batch_id}/",
        f"- report: {relpath(ctx, report_path)}",
        f"- workflow log: traces/{batch_id}_workflow_log.json",
        "",
        f"## {section_title('review_advice', lang)}",
        "- Critical findings should be reviewed against the raw instrument export before interpretation.",
        "- Re-run preprocessing only with registered scripts and preserve raw data unchanged.",
        "- Treat this report as rule-based QC evidence, not an automated scientific conclusion.",
        "",
        f"## {section_title('severity_counts', lang)}",
        json.dumps(dict(sorted(by_severity.items())), ensure_ascii=False, indent=2),
    ]
```

Add `lang` to `GENERATE_REPORT_SCHEMA` in `pico/tool_registry.py`:

```python
GENERATE_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "batch_id": {"type": "string"},
        "findings_path": {"type": "string"},
        "lang": {"type": "string"},
    },
    "required": ["batch_id"],
}
```

- [ ] **Step 6: Derive evaluator sections from the template**

In `evaluate_qc.py`, replace lines 10-19 (`REQUIRED_REPORT_SECTIONS = [...]`) with:

```python
from pico.report_template import required_section_titles

REQUIRED_REPORT_SECTIONS = required_section_titles("zh")
```

- [ ] **Step 7: Run report + evaluator tests**

Run: `python -m pytest tests/test_phase3_report_template.py tests/test_labflow_reports.py tests/test_evaluate_qc.py tests/test_evaluate_multi_batch.py -v`
Expected: PASS (default `lang=zh` reproduces the old headers exactly).

- [ ] **Step 8: Lint and commit**

```bash
ruff check pico/report_template.py pico/labflow_tools.py pico/tool_registry.py evaluate_qc.py tests/test_phase3_report_template.py
git add pico/report_template.py pico/labflow_tools.py pico/tool_registry.py evaluate_qc.py tests/test_phase3_report_template.py
git commit -m "feat(report): templated section titles; evaluator derives from template"
```

---

## Task 2: Planner guidance layer in the runtime

**Files:**
- Modify: `pico/agent/planner.py` (add `render_plan`)
- Modify: `pico/context_manager.py` (`build_prompt` gains `suggested_plan`)
- Modify: `pico/runtime.py` (`use_planner`, `build_prompt_and_metadata`)
- Modify: `pico/cli.py` (`--no-planner`)

**Interfaces:**
- Produces: `render_plan(plan: ToolPlan) -> str`; `build_prompt(..., suggested_plan: str = "")` injects a `<suggested_plan>` section; `Pico.use_planner: bool = True`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase3_planner_integration.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.providers import FakeModelClient
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.workspace import WorkspaceContext


class PlannerIntegrationTests(unittest.TestCase):
    def test_planner_on_injects_suggested_plan(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "data").mkdir()
            captured = {}

            class CapturingClient(FakeModelClient):
                def complete(self, request):
                    captured["prompt"] = request.prompt
                    return super().complete(request)

            client = CapturingClient(script=["<final>ok</final>"])
            pico = Pico(
                workspace=WorkspaceContext(repo_root=root),
                model_client=client,
                session_store=SessionStore(root),
                run_store=RunStore(root),
                max_steps=1,
                use_planner=True,
            )
            pico.ask("对 data/batch_001 跑完整 QC")
            self.assertIn("<suggested_plan>", captured["prompt"])

    def test_planner_off_omits_suggested_plan(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "data").mkdir()
            captured = {}

            class CapturingClient(FakeModelClient):
                def complete(self, request):
                    captured["prompt"] = request.prompt
                    return super().complete(request)

            client = CapturingClient(script=["<final>ok</final>"])
            pico = Pico(
                workspace=WorkspaceContext(repo_root=root),
                model_client=client,
                session_store=SessionStore(root),
                run_store=RunStore(root),
                max_steps=1,
                use_planner=False,
            )
            pico.ask("对 data/batch_001 跑完整 QC")
            self.assertNotIn("<suggested_plan>", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase3_planner_integration.py -v`
Expected: FAIL — `Pico.__init__` does not accept `use_planner`; no `<suggested_plan>` injected.

- [ ] **Step 3: Add `render_plan` to `pico/agent/planner.py`**

Append to `pico/agent/planner.py`:

```python
def render_plan(plan: ToolPlan) -> str:
    """Render a ToolPlan as a concise suggested-step list for the prompt."""
    if not plan.steps:
        return ""
    lines = [f"Intent: {plan.intent}", "Suggested steps (advisory — you may deviate):"]
    for idx, step in enumerate(plan.steps, start=1):
        detail = step.description or step.name
        lines.append(f"{idx}. {step.kind}: {detail}")
    if plan.warnings:
        lines.append("Warnings: " + "; ".join(plan.warnings))
    return "\n".join(lines)
```

- [ ] **Step 4: Add `suggested_plan` to `build_prompt`**

In `pico/context_manager.py`, change the `build_prompt` signature and body. Add the parameter and a new section. Replace the function signature line:

```python
def build_prompt(
    prefix: PromptPrefix,
    memory_text: str,
    relevant_memory_text: str,
    history_text: str,
    user_message: str,
    budget: int = DEFAULT_CONTEXT_BUDGET,
    suggested_plan: str = "",
) -> tuple[str, dict[str, Any]]:
```

In the `sections` dict, add the suggested plan after `prefix`:

```python
    sections: dict[str, str] = {
        "prefix": prefix.text,
        "suggested_plan": suggested_plan.strip(),
        "memory": memory_text.strip(),
        "relevant_memory": relevant_memory_text.strip(),
        "history": history_text.strip(),
        "current_request": user_message.strip(),
    }
```

Update the truncation `order` list to include `suggested_plan` as the second-most-trimmable (after relevant_memory):

```python
        order = ["relevant_memory", "suggested_plan", "history", "memory", "prefix"]
        limits = {
            "relevant_memory": int(budget * 0.1),
            "suggested_plan": int(budget * 0.1),
            "history": int(budget * 0.2),
            "memory": int(budget * 0.13),
            "prefix": int(budget * 0.3),
        }
```

Update the final assembly loop to include `suggested_plan` between `prefix` and `memory`:

```python
    for section_name in ["prefix", "suggested_plan", "memory", "relevant_memory", "history", "current_request"]:
```

- [ ] **Step 5: Wire the planner into `Pico`**

In `pico/runtime.py`, add the import:

```python
from .agent.planner import build_plan, render_plan
```

Add a field to the `Pico` dataclass (after `current_batch_id`):

```python
    use_planner: bool = True
```

In `build_prompt_and_metadata`, compute and pass the plan. Replace the method body:

```python
    def build_prompt_and_metadata(self, user_message: str) -> tuple[str, dict[str, Any]]:
        self.refresh_prefix()
        memory_text = self.memory.render(self.workspace.repo_root, user_message)
        durable_text = DurableMemoryStore(self.workspace.repo_root).read_all(max_chars=1800)
        if durable_text:
            memory_text = (memory_text + "\n\n## Durable memory\n" + durable_text).strip()
        relevant = ""
        history_text = self.render_history()
        suggested_plan = ""
        if self.use_planner:
            suggested_plan = render_plan(build_plan(user_message))
        return build_prompt(self.prefix, memory_text, relevant, history_text, user_message, suggested_plan=suggested_plan)  # type: ignore[arg-type]
```

- [ ] **Step 6: Add `--no-planner` CLI flag**

In `pico/cli.py`, add to `build_arg_parser` (after `--fake-script`):

```python
    parser.add_argument("--no-planner", action="store_true", help="Disable the suggested-plan guidance layer")
```

In `build_agent`, pass `use_planner=not args.no_planner` to both `Pico.from_session(...)` and `Pico(...)` constructors (add the kwarg to each call).

- [ ] **Step 7: Run planner + runtime tests**

Run: `python -m pytest tests/test_phase3_planner_integration.py tests/test_agent_planner.py tests/test_agent_intent.py tests/test_runtime.py tests/test_context_manager.py -v`
Expected: PASS.

- [ ] **Step 8: Lint and commit**

```bash
ruff check pico/agent/planner.py pico/context_manager.py pico/runtime.py pico/cli.py tests/test_phase3_planner_integration.py
git add pico/agent/planner.py pico/context_manager.py pico/runtime.py pico/cli.py tests/test_phase3_planner_integration.py
git commit -m "feat(runtime): optional planner guidance layer (--no-planner to disable)"
```

---

## Task 3: Pluggable context truncation strategy

**Files:**
- Modify: `pico/context_manager.py`
- Modify: `pico/config.py`

**Interfaces:**
- Produces: `TruncationStrategy` protocol, `PriorityTruncation`, `SmartTruncation`, `load_truncation_strategy(name)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase3_truncation_strategy.py`:

```python
from __future__ import annotations

import unittest

from pico.context_manager import PriorityTruncation, SmartTruncation


class TruncationStrategyTests(unittest.TestCase):
    def test_priority_keeps_current_behavior(self):
        strat = PriorityTruncation()
        sections = {
            "prefix": "P" * 5000,
            "suggested_plan": "S" * 200,
            "memory": "M" * 2000,
            "relevant_memory": "R" * 2000,
            "history": "H" * 5000,
            "current_request": "U" * 100,
        }
        out = strat.truncate(sections, budget=8000)
        total = sum(len(v) for v in out.values())
        self.assertLessEqual(total, 8000)

    def test_smart_exists_and_is_strategy(self):
        strat = SmartTruncation(intent="explain_finding")
        sections = {"prefix": "P", "suggested_plan": "", "memory": "M", "relevant_memory": "R", "history": "H", "current_request": "U"}
        out = strat.truncate(sections, budget=1000)
        self.assertIn("history", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase3_truncation_strategy.py -v`
Expected: FAIL — `ImportError: cannot import name 'PriorityTruncation'`.

- [ ] **Step 3: Add the strategy classes to `context_manager.py`**

Append to `pico/context_manager.py`:

```python
from typing import Protocol


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
```

Refactor `build_prompt` to delegate truncation to `PriorityTruncation` by default. Replace the in-function truncation loop (the `order`/`limits`/`for key in order` block) with:

```python
    strategy = PriorityTruncation()
    total = sum(len(text) for text in sections.values())
    if total > budget:
        truncated = strategy.truncate(sections, budget)
        for key, text in truncated.items():
            if len(text) < len(sections[key]):
                reductions[key] = len(sections[key]) - len(text)
            sections[key] = text
```

- [ ] **Step 4: Add env-driven strategy selection in `config.py`**

Append to `pico/config.py`:

```python
def load_truncation_strategy():
    name = env_or("priority", "PICO_TRUNCATION_STRATEGY")
    if name == "smart":
        from .context_manager import SmartTruncation

        return SmartTruncation()
    from .context_manager import PriorityTruncation

    return PriorityTruncation()
```

- [ ] **Step 5: Run truncation + context tests**

Run: `python -m pytest tests/test_phase3_truncation_strategy.py tests/test_context_manager.py -v`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
ruff check pico/context_manager.py pico/config.py tests/test_phase3_truncation_strategy.py
git add pico/context_manager.py pico/config.py tests/test_phase3_truncation_strategy.py
git commit -m "feat(context): pluggable TruncationStrategy with priority and smart modes"
```

---

## Task 4: Reorganize tools into a `tools/` package

**Files:**
- Create: `pico/tools/__init__.py`, `pico/tools/base.py`, `pico/tools/generic.py`, `pico/tools/labflow.py`, `pico/tools/registry.py`
- Convert to shims: `pico/tools.py` → delete (replaced by package), `pico/labflow_tools.py`, `pico/tool_registry.py`

> **Note:** This task is mechanical but touches many import sites via the shims. Execute it as one commit. The shims guarantee no caller breaks.

**Interfaces:**
- Produces: `pico.tools.base.ToolSpec`/`ToolResult`/primitives; `pico.tools.generic` (generic tools + `build_tool_registry`); `pico.tools.labflow` (LabFlow tool functions); `pico.tools.registry.build_labflow_tool_registry`/`build_tool_registry`. The old module paths re-export these with a `DeprecationWarning`.

- [ ] **Step 1: Create the package files by moving content**

Create `pico/tools/base.py` with the primitives currently in `pico/tools.py`: `ToolResult`, `ToolSpec`, `validate_tool_args`, `relpath`, `tool_signature`, `shell_command_signature`, `workspace_snapshot`, and the `from .config import ...` / `from .tool_context import ...` / `from .workspace import ...` imports they need. Do **not** move the generic tool functions or schemas yet.

Create `pico/tools/generic.py` with the generic tool functions (`tool_list_files`, `tool_read_file`, `tool_search`, `tool_run_shell`, `tool_write_file`, `tool_patch_file`, `tool_delegate`) and their schemas (`LIST_FILES_SCHEMA`, etc.) and `build_tool_registry` (the generic one), importing primitives from `.base`.

Create `pico/tools/labflow.py` with the entire current contents of `pico/labflow_tools.py`, importing `ToolResult`, `relpath` from `.base` and the guard functions from `..safety.guard`.

Create `pico/tools/registry.py` with the entire current contents of `pico/tool_registry.py`, importing `ToolSpec` from `.base` and `from . import labflow` for the function references.

Create `pico/tools/__init__.py`:

```python
from __future__ import annotations

from .base import ToolResult, ToolSpec
from .generic import build_tool_registry as build_generic_tool_registry
from .registry import build_labflow_tool_registry, build_tool_registry

__all__ = [
    "ToolResult",
    "ToolSpec",
    "build_generic_tool_registry",
    "build_labflow_tool_registry",
    "build_tool_registry",
]
```

- [ ] **Step 2: Convert the old modules to deprecation shims**

Delete `pico/tools.py` (its content now lives in the package). Replace `pico/labflow_tools.py` with:

```python
from __future__ import annotations

import warnings

warnings.warn(
    "pico.labflow_tools is deprecated; import from pico.tools.labflow instead.",
    DeprecationWarning,
    stacklevel=2,
)
from .tools.labflow import *  # noqa: F401,F403
from .tools.labflow import __all__ as _all  # noqa: F401

__all__ = _all
```

(If `pico/tools/labflow.py` does not define `__all__`, add `__all__` listing the public `tool_*` functions and the module constants like `QC_COLUMNS`.)

Replace `pico/tool_registry.py` with:

```python
from __future__ import annotations

import warnings

warnings.warn(
    "pico.tool_registry is deprecated; import from pico.tools.registry instead.",
    DeprecationWarning,
    stacklevel=2,
)
from .tools.registry import build_labflow_tool_registry, build_tool_registry  # noqa: F401

__all__ = ["build_labflow_tool_registry", "build_tool_registry"]
```

- [ ] **Step 3: Add `pico.tools` to setuptools packages**

In `pyproject.toml`, change the `packages` line to include `pico.tools`:

```toml
packages = ["pico", "pico.providers", "pico.features", "pico.evaluation", "pico.safety", "pico.agent", "pico.tools"]
```

- [ ] **Step 4: Run the full suite (shims keep all old imports working)**

Run: `python -m pytest tests/ -q -W ignore::DeprecationWarning`
Expected: PASS — all tests green; old import paths still resolve via shims.

- [ ] **Step 5: Verify shims warn**

Run: `python -W error::DeprecationWarning -c "import pico.labflow_tools"` 
Expected: raises `DeprecationWarning` (proving the warning fires). Then run `python -c "import pico.labflow_tools; print('ok')"` → prints `ok`.

- [ ] **Step 6: Lint and commit**

```bash
ruff check pico/tools/ pico/labflow_tools.py pico/tool_registry.py pyproject.toml
git add pico/tools/ pico/labflow_tools.py pico/tool_registry.py pyproject.toml
git rm pico/tools.py
git commit -m "refactor(tools): reorganize into pico/tools/ package with deprecation shims"
```

---

## Phase 3 Acceptance

- [ ] `python -m pytest tests/ -q` fully green (with deprecation warnings tolerated).
- [ ] `ruff check .` clean.
- [ ] `pico --no-planner "对 data/batch_001 跑完整 QC"` produces a prompt with no `<suggested_plan>` section; without the flag it includes one.
- [ ] `required_section_titles("zh")` matches the legacy `REQUIRED_REPORT_SECTIONS` exactly.
- [ ] `pico.tools.labflow.tool_generate_report` with `lang="en"` produces English headers.
- [ ] `pico.tools.base`, `pico.tools.generic`, `pico.tools.labflow`, `pico.tools.registry` all import cleanly; old paths warn but still work.

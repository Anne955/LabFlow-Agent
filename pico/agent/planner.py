from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .intent import (
    COMPARE_BATCHES,
    EXPLAIN_FINDING,
    FULL_QC_WORKFLOW,
    METADATA_ONLY,
    PREPROCESS_ONLY,
    QC_ONLY,
    REPORT_ONLY,
    RESUME_FAILED_WORKFLOW,
    SHOW_SUMMARY,
    detect_intent,
)

BATCH_RE = re.compile(r"(?:data[/\\])?(batch[A-Za-z0-9_-]+)")
PATH_RE = re.compile(r"(?:\./)?data[/\\](batch[A-Za-z0-9_-]+)")
FINDING_RE = re.compile(r"\bF\d{4,}\b", re.IGNORECASE)
SAMPLE_RE = re.compile(r"\bsample_\d+\b", re.IGNORECASE)


@dataclass(frozen=True)
class PlannerInputs:
    prompt: str
    intent: str
    batch_id: str | None = None
    batch_ids: tuple[str, ...] = ()
    experiment_dir: str | None = None
    skip_critical: bool = True
    only_qc_passed: bool = False
    report_only: bool = False
    finding_id: str | None = None
    sample_id: str | None = None


@dataclass(frozen=True)
class PlanStep:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    kind: str = "tool"
    description: str = ""


@dataclass(frozen=True)
class ToolPlan:
    intent: str
    inputs: PlannerInputs
    steps: tuple[PlanStep, ...]
    warnings: tuple[str, ...] = ()


def parse_planner_inputs(prompt: str) -> PlannerInputs:
    intent = detect_intent(prompt).intent
    normalized = prompt.replace("\\", "/")
    path_matches = PATH_RE.findall(normalized)
    batch_matches = BATCH_RE.findall(normalized)
    batch_ids = tuple(dict.fromkeys(batch_matches))
    batch_id = batch_ids[0] if batch_ids else None
    experiment_dir = f"data/{path_matches[0]}" if path_matches else (f"data/{batch_id}" if batch_id else None)
    lower = prompt.lower()
    skip_critical = not any(term in lower for term in ("不要跳过 critical", "不要跳过严重异常", "处理所有样本", "include critical", "process all samples", "do not skip critical", "no skip"))
    only_qc_passed = any(term in lower for term in ("只处理 qc 通过", "只处理质控通过", "只预处理通过", "only qc passed", "only passed samples", "only samples that passed qc"))
    if only_qc_passed:
        skip_critical = True
    finding_match = FINDING_RE.search(prompt)
    sample_match = SAMPLE_RE.search(prompt)
    return PlannerInputs(
        prompt=prompt,
        intent=intent,
        batch_id=batch_id,
        batch_ids=batch_ids,
        experiment_dir=experiment_dir,
        skip_critical=skip_critical,
        only_qc_passed=only_qc_passed,
        report_only=intent == REPORT_ONLY,
        finding_id=finding_match.group(0).upper() if finding_match else None,
        sample_id=sample_match.group(0).lower() if sample_match else None,
    )


def build_plan(prompt: str) -> ToolPlan:
    inputs = parse_planner_inputs(prompt)
    batch_id = inputs.batch_id or "batch_unknown"
    experiment_dir = inputs.experiment_dir or f"data/{batch_id}"
    warnings: list[str] = []

    if inputs.intent == METADATA_ONLY:
        steps = [
            PlanStep("scan_experiment_dir", {"experiment_dir": experiment_dir, "batch_id": batch_id}),
            PlanStep("inspect_table", {"path": f"{experiment_dir}/metadata.csv", "max_rows": 5}),
        ]
    elif inputs.intent == QC_ONLY:
        steps = [
            PlanStep("scan_experiment_dir", {"experiment_dir": experiment_dir, "batch_id": batch_id}),
            PlanStep("quality_check", {"experiment_dir": experiment_dir, "batch_id": batch_id}),
            PlanStep("summarize_outputs", {"batch_id": batch_id}),
            PlanStep("export_workflow_log", {"batch_id": batch_id}),
        ]
    elif inputs.intent == PREPROCESS_ONLY:
        steps = [
            PlanStep("quality_check", {"experiment_dir": experiment_dir, "batch_id": batch_id}),
            _preprocess_step(batch_id, experiment_dir, inputs),
        ]
    elif inputs.intent == REPORT_ONLY:
        steps = [
            PlanStep("summarize_outputs", {"batch_id": batch_id}),
            PlanStep("generate_report", {"batch_id": batch_id}),
            PlanStep("export_workflow_log", {"batch_id": batch_id}),
        ]
    elif inputs.intent == SHOW_SUMMARY:
        steps = [PlanStep("summarize_outputs", {"batch_id": batch_id})]
    elif inputs.intent == COMPARE_BATCHES:
        ids = inputs.batch_ids or ((batch_id,) if batch_id else ())
        steps = [PlanStep("summarize_outputs", {"batch_id": item}) for item in ids]
        steps.append(PlanStep("compare_batch_summaries", {"batch_ids": list(ids)}, kind="internal"))
    elif inputs.intent == RESUME_FAILED_WORKFLOW:
        warnings.append("resume_failed_workflow is planned from existing outputs; this minimal planner does not inspect trace state yet.")
        steps = [
            PlanStep("summarize_outputs", {"batch_id": batch_id}),
            _preprocess_step(batch_id, experiment_dir, inputs),
            PlanStep("generate_report", {"batch_id": batch_id}),
            PlanStep("export_workflow_log", {"batch_id": batch_id}),
        ]
    elif inputs.intent == EXPLAIN_FINDING:
        selector = {"batch_id": batch_id, "path": f"outputs/{batch_id}/qc_summary.csv"}
        if inputs.finding_id:
            selector["finding_id"] = inputs.finding_id
        if inputs.sample_id:
            selector["sample_id"] = inputs.sample_id
        steps = [
            PlanStep("read_qc_summary", selector, kind="internal"),
            PlanStep("explain_finding", selector, kind="internal"),
        ]
    else:
        steps = _full_workflow_steps(batch_id, experiment_dir, inputs)

    return ToolPlan(intent=inputs.intent, inputs=inputs, steps=tuple(steps), warnings=tuple(warnings))


def _full_workflow_steps(batch_id: str, experiment_dir: str, inputs: PlannerInputs) -> list[PlanStep]:
    return [
        PlanStep("scan_experiment_dir", {"experiment_dir": experiment_dir, "batch_id": batch_id}),
        PlanStep("inspect_table", {"path": f"{experiment_dir}/metadata.csv", "max_rows": 5}),
        PlanStep("quality_check", {"experiment_dir": experiment_dir, "batch_id": batch_id}),
        _preprocess_step(batch_id, experiment_dir, inputs),
        PlanStep("summarize_outputs", {"batch_id": batch_id}),
        PlanStep("generate_report", {"batch_id": batch_id}),
        PlanStep("export_workflow_log", {"batch_id": batch_id}),
    ]


def _preprocess_step(batch_id: str, experiment_dir: str, inputs: PlannerInputs) -> PlanStep:
    return PlanStep(
        "run_preprocess_script",
        {
            "script_name": "normalize_csv.py",
            "batch_id": batch_id,
            "mode": "batch",
            "input_dir": f"{experiment_dir}/spectra",
            "input_glob": "*.csv",
            "output_suffix": "_normalized.csv",
            "skip_critical": inputs.skip_critical,
            "only_qc_passed": inputs.only_qc_passed,
        },
    )


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

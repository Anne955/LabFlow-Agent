from __future__ import annotations

from dataclasses import dataclass

FULL_QC_WORKFLOW = "full_qc_workflow"
METADATA_ONLY = "metadata_only"
QC_ONLY = "qc_only"
PREPROCESS_ONLY = "preprocess_only"
REPORT_ONLY = "report_only"
EXPLAIN_FINDING = "explain_finding"
COMPARE_BATCHES = "compare_batches"
RESUME_FAILED_WORKFLOW = "resume_failed_workflow"
SHOW_SUMMARY = "show_summary"


@dataclass(frozen=True)
class IntentResult:
    intent: str
    confidence: float
    matched_terms: tuple[str, ...] = ()
    language_hint: str = "unknown"


RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (EXPLAIN_FINDING, ("为什么异常", "为什么失败", "解释", "explain finding", "why failed", "finding", "f000", "sample_")),
    (COMPARE_BATCHES, ("对比", "比较", "两个批次", "compare batches", "compare batch", "compare")),
    (RESUME_FAILED_WORKFLOW, ("继续失败", "恢复 workflow", "从失败处继续", "重跑失败", "resume", "continue failed", "rerun failed")),
    (REPORT_ONLY, ("只生成报告", "重新生成", "生成报告", "报告即可", "report only", "just report", "generate report")),
    (METADATA_ONLY, ("只检查 metadata", "只看 metadata", "只看元数据", "检查元数据", "metadata only", "inspect metadata", "check metadata")),
    (PREPROCESS_ONLY, ("跳过 critical", "归一化", "只做预处理", "只归一化", "预处理", "normalize", "preprocess only", "run preprocessing", "preprocess")),
    (QC_ONLY, ("只跑 qc", "只做 qc", "只做质控", "只做质量检查", "qc only", "quality check only", "run qc")),
    (SHOW_SUMMARY, ("显示汇总", "看汇总", "输出汇总", "总结输出", "show summary", "summarize outputs", "summary")),
)


def detect_intent(prompt: str) -> IntentResult:
    normalized = prompt.strip().lower()
    language = "zh" if any("一" <= char <= "鿿" for char in prompt) else "en"
    if any(term in normalized for term in ("完整", "全流程", "跑完整", "full workflow", "run everything", "end to end")):
        return IntentResult(intent=FULL_QC_WORKFLOW, confidence=0.9, matched_terms=("full",), language_hint=language)
    if "metadata" in normalized and any(term in normalized for term in ("只", "only", "inspect", "check", "检查", "看")):
        return IntentResult(intent=METADATA_ONLY, confidence=0.9, matched_terms=("metadata",), language_hint=language)
    if any(term in normalized for term in ("预处理", "归一化", "preprocess", "normalize")):
        return IntentResult(intent=PREPROCESS_ONLY, confidence=0.9, matched_terms=("preprocess",), language_hint=language)
    if "qc" in normalized and any(term in normalized for term in ("只", "only")):
        return IntentResult(intent=QC_ONLY, confidence=0.9, matched_terms=("qc",), language_hint=language)
    for intent, terms in RULES:
        matched = tuple(term for term in terms if term in normalized)
        if matched:
            return IntentResult(intent=intent, confidence=0.9, matched_terms=matched, language_hint=language)
    return IntentResult(intent=FULL_QC_WORKFLOW, confidence=0.55, matched_terms=(), language_hint=language)

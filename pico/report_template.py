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

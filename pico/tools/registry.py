from __future__ import annotations

from ..tool_context import ToolContext
from .base import ToolSpec

SCAN_EXPERIMENT_DIR_SCHEMA = {
    "type": "object",
    "properties": {
        "experiment_dir": {"type": "string"},
        "batch_id": {"type": "string"},
    },
    "required": ["experiment_dir"],
}

INSPECT_TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "max_rows": {"type": "integer"},
    },
    "required": ["path"],
}

QUALITY_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "experiment_dir": {"type": "string"},
        "batch_id": {"type": "string"},
        "metadata_path": {"type": "string"},
        "spectra_dir": {"type": "string"},
        "instrument_log_path": {"type": "string"},
    },
    "required": ["experiment_dir"],
}

RUN_PREPROCESS_SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "script_name": {"type": "string"},
        "batch_id": {"type": "string"},
        "input_path": {"type": "string"},
        "output_path": {"type": "string"},
        "mode": {"type": "string"},
        "input_dir": {"type": "string"},
        "input_glob": {"type": "string"},
        "output_suffix": {"type": "string"},
        "only_qc_passed": {"type": "boolean"},
        "skip_critical": {"type": "boolean"},
        "max_files": {"type": "integer"},
    },
    "required": ["script_name", "batch_id"],
}

SUMMARIZE_OUTPUTS_SCHEMA = {
    "type": "object",
    "properties": {
        "batch_id": {"type": "string"},
    },
    "required": ["batch_id"],
}

GENERATE_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "batch_id": {"type": "string"},
        "findings_path": {"type": "string"},
        "lang": {"type": "string"},
    },
    "required": ["batch_id"],
}

EXPORT_WORKFLOW_LOG_SCHEMA = {
    "type": "object",
    "properties": {
        "batch_id": {"type": "string"},
    },
    "required": ["batch_id"],
}


def build_labflow_tool_registry(context: ToolContext) -> dict[str, ToolSpec]:
    from . import labflow

    return {
        "scan_experiment_dir": ToolSpec(
            "scan_experiment_dir",
            "Scan an experiment batch directory and identify metadata, spectra, logs,"
            " and suspicious filenames.",
            SCAN_EXPERIMENT_DIR_SCHEMA,
            False,
            labflow.tool_scan_experiment_dir,
        ),
        "inspect_table": ToolSpec(
            "inspect_table",
            "Inspect a CSV metadata table and summarize columns, types,"
            " missing values, and duplicate sample IDs.",
            INSPECT_TABLE_SCHEMA,
            False,
            labflow.tool_inspect_table,
        ),
        "quality_check": ToolSpec(
            "quality_check",
            "Run rule-based QC over metadata and spectra files, then write"
            " outputs/<batch_id>/qc_summary.csv.",
            QUALITY_CHECK_SCHEMA,
            False,
            labflow.tool_quality_check,
        ),
        "run_preprocess_script": ToolSpec(
            "run_preprocess_script",
            "Run a registered preprocessing script from the LabFlow whitelist;"
            " arbitrary shell is not allowed.",
            RUN_PREPROCESS_SCRIPT_SCHEMA,
            True,
            labflow.tool_run_preprocess_script,
        ),
        "summarize_outputs": ToolSpec(
            "summarize_outputs",
            "Summarize LabFlow QC and preprocessing outputs for a batch.",
            SUMMARIZE_OUTPUTS_SCHEMA,
            False,
            labflow.tool_summarize_outputs,
        ),
        "generate_report": ToolSpec(
            "generate_report",
            "Generate a Markdown QC report under reports/<batch_id>_qc_report.md.",
            GENERATE_REPORT_SCHEMA,
            False,
            labflow.tool_generate_report,
        ),
        "export_workflow_log": ToolSpec(
            "export_workflow_log",
            "Export a JSON workflow log under traces/<batch_id>_workflow_log.json.",
            EXPORT_WORKFLOW_LOG_SCHEMA,
            False,
            labflow.tool_export_workflow_log,
        ),
    }


def build_tool_registry(context: ToolContext) -> dict[str, ToolSpec]:
    return build_labflow_tool_registry(context)

# LabFlow Agent

LabFlow Agent 是一个面向实验数据处理的本地科研流程智能体。它基于本地 Agent Harness 的工具调用机制，把实验目录扫描、metadata 校验、数据质控、白名单预处理、结果汇总、Markdown 报告生成和 workflow trace 串成一条可复核的本地流程。

## Project Motivation

实验室或企业研发部门完成一批 Raman、FTIR、XRF、UV-Vis 等实验后，通常会得到 metadata 表、光谱 CSV、仪器日志和中间结果。人工整理时容易出现样本编号不一致、字段缺失、重复样本、文件缺失、命名不规范、数值异常和报告整理耗时等问题。LabFlow Agent 用于自动执行这些重复性检查，并保留可追溯证据链。

## What LabFlow Agent Is

- 本地科研数据流程助手。
- 面向实验批次目录的扫描、质控、预处理和报告生成工具。
- 通过工具注册层和 runtime trace 保证流程可复核。
- 派生结果统一写入 `outputs/`、`reports/`、`traces/`。

## What LabFlow Agent Is Not

- 不是 coding agent，不展示自动修代码能力。
- 不开放任意 shell。
- 不训练大模型。
- 不替代科研人员给出最终科学结论。
- 不做颜料数据库 CRUD。
- 不做 PostgreSQL 物质溯源系统。

## Architecture

```text
pico/
  cli.py               # CLI 与 REPL 装配
  runtime.py           # <tool>/<final> 主循环、trace 记录、workflow log 导出
  workflow_trace.py    # trace.jsonl -> LabFlow workflow log
  prompt_prefix.py     # LabFlow 身份与工具协议
  tool_registry.py     # LabFlow 工具注册层
  labflow_tools.py     # scan / inspect / QC / preprocess / report / log 工具
  safety/guard.py      # batch_id、输出目录、脚本白名单等安全边界
  providers/clients.py # Fake、Ollama、OpenAI-compatible、Anthropic-compatible
```

## Tool Registry

默认 LabFlow registry 暴露 7 个工具：

1. `scan_experiment_dir`
2. `inspect_table`
3. `quality_check`
4. `run_preprocess_script`
5. `summarize_outputs`
6. `generate_report`
7. `export_workflow_log`

默认不暴露：

- `run_shell`
- `write_file`
- `patch_file`

## Safety Boundaries

- `data/raw` 和 `data/batch_*` 作为原始数据输入，不允许被预处理脚本覆盖写入。
- 派生结果只能进入：
  - `outputs/<batch_id>/`
  - `reports/<batch_id>_qc_report.md`
  - `traces/<batch_id>_workflow_log.json`
- 预处理脚本必须在白名单中，目前支持 `normalize_csv.py`。
- `batch_id` 只允许安全字符，防止路径逃逸。

## Demo Dataset

可生成 5 个可复现 demo batch：

```bash
python scripts/generate_demo_batches.py --batches 5 --samples-per-batch 20 --seed 42
```

生成：

```text
data/batch_demo_001/ ... data/batch_demo_005/
labels/batch_demo_001_labels.json ... labels/batch_demo_005_labels.json
```

每个 batch 包含 `metadata.csv`、`instrument_log.txt` 和 `spectra/`。

## Public Data Validation: RRUFF Raman Fixture

LabFlow also includes a separate public-data compatibility validation path based on a small offline RRUFF-style Raman fixture set.

Raw local fixture files live under:

```text
data_public/rruff_raw/
```

These text files mimic public RRUFF Raman exports with header/comment lines plus numeric Raman shift and intensity pairs. They are included so the converter and LabFlow workflow can be verified without relying on external APIs or network access. Users may replace or extend them with locally downloaded public RRUFF Raman `.txt` files.

Convert the raw fixture into a LabFlow batch:

```bash
python scripts/convert_rruff_to_labflow_csv.py \
  --input-dir data_public/rruff_raw \
  --output-dir data/batch_public_rruff_001 \
  --batch-id batch_public_rruff_001 \
  --limit 20
```

The converter writes:

```text
data/batch_public_rruff_001/
├── metadata.csv
├── instrument_log.txt
└── spectra/
    ├── rruff_001_raman.csv
    └── ...
```

`metadata.csv` includes `sample_id`, `method`, `instrument`, `operator`, `file_path`, `source_dataset`, and `source_id`. Converted spectra use the LabFlow standard `x,intensity` CSV format.

Run the public RRUFF compatibility workflow:

```bash
python -m pico --approval auto --provider fake --max-steps 7 --fake-script '<tool>{"name":"scan_experiment_dir","args":{"experiment_dir":"data/batch_public_rruff_001","batch_id":"batch_public_rruff_001"}}</tool>||<tool>{"name":"inspect_table","args":{"path":"data/batch_public_rruff_001/metadata.csv","max_rows":5}}</tool>||<tool>{"name":"quality_check","args":{"experiment_dir":"data/batch_public_rruff_001","batch_id":"batch_public_rruff_001"}}</tool>||<tool>{"name":"run_preprocess_script","args":{"script_name":"normalize_csv.py","batch_id":"batch_public_rruff_001","mode":"batch","input_dir":"data/batch_public_rruff_001/spectra","input_glob":"*.csv","output_suffix":"_normalized.csv","skip_critical":true}}</tool>||<tool>{"name":"summarize_outputs","args":{"batch_id":"batch_public_rruff_001"}}</tool>||<tool>{"name":"generate_report","args":{"batch_id":"batch_public_rruff_001"}}</tool>||<tool>{"name":"export_workflow_log","args":{"batch_id":"batch_public_rruff_001"}}</tool>||<final>LabFlow public RRUFF compatibility workflow completed for batch_public_rruff_001.</final>' "Run full LabFlow workflow for data/batch_public_rruff_001"
```

Expected public-validation outputs:

```text
outputs/batch_public_rruff_001/qc_summary.csv
outputs/batch_public_rruff_001/preprocess_summary.csv
outputs/batch_public_rruff_001/preprocessed/
reports/batch_public_rruff_001_qc_report.md
traces/batch_public_rruff_001_workflow_log.json
```

This public batch is **not** mixed into the synthetic benchmark Precision / Recall / F1 numbers by default. It validates real-style text-file ingestion, conversion, workflow traceability, and report generation only. It does not claim Raman mineral identification accuracy, peak assignment correctness, calibration correctness, or scientific interpretation quality.

## Quality Check Rules

当前 CSV 质控规则包括：

- metadata 缺失值；
- 重复 `sample_id`；
- metadata 中有样本但缺少光谱文件；
- 光谱文件无 metadata 记录；
- 文件命名不符合 `sample_id_method.csv`；
- 光谱 CSV 缺少 `x` 或 `intensity`；
- `intensity` 缺失、非数值、负值、极端值；
- `x` 非单调递增；
- 光谱点数过少。

## Workflow Trace

一次完整 workflow 会记录 7 个核心事件：

```text
scan_experiment_dir -> inspect_table -> quality_check -> run_preprocess_script -> summarize_outputs -> generate_report -> export_workflow_log
```

Public workflow log 位于：

```text
traces/<batch_id>_workflow_log.json
```

每个事件包含 tool、input、output_paths、metadata、status、error_code、timestamp 和 duration_seconds。顶层包含 total_duration_seconds。

## How to Run Demo

单 batch 完整 fake-provider workflow：

```bash
python -m pico --approval auto --provider fake --max-steps 7 --fake-script '<tool>{"name":"scan_experiment_dir","args":{"experiment_dir":"data/batch_demo_001","batch_id":"batch_demo_001"}}</tool>||<tool>{"name":"inspect_table","args":{"path":"data/batch_demo_001/metadata.csv","max_rows":5}}</tool>||<tool>{"name":"quality_check","args":{"experiment_dir":"data/batch_demo_001","batch_id":"batch_demo_001"}}</tool>||<tool>{"name":"run_preprocess_script","args":{"script_name":"normalize_csv.py","batch_id":"batch_demo_001","mode":"batch","input_dir":"data/batch_demo_001/spectra","input_glob":"*.csv","output_suffix":"_normalized.csv","skip_critical":true}}</tool>||<tool>{"name":"summarize_outputs","args":{"batch_id":"batch_demo_001"}}</tool>||<tool>{"name":"generate_report","args":{"batch_id":"batch_demo_001"}}</tool>||<tool>{"name":"export_workflow_log","args":{"batch_id":"batch_demo_001"}}</tool>||<final>LabFlow full workflow completed for batch_demo_001.</final>' "Run full LabFlow workflow for data/batch_demo_001"
```

多 batch 评测：

```bash
python evaluate_qc.py \
  --pred-dir outputs \
  --labels-dir labels \
  --reports-dir reports \
  --traces-dir traces \
  --output evaluation_summary.json \
  --errors evaluation_errors.csv \
  --resume-metrics resume_metrics.json
```

## New CLI options (2026-07 improvements)

- `--no-planner` — disable the suggested-plan guidance layer (pure LLM-driven mode).
- `--stream` — stream the final answer to the terminal token-by-token.

Report language is selected via the `generate_report` tool's `lang` argument (the LLM passes `lang: "en"` or `lang: "zh"`, default `zh`); a `--lang` CLI flag is not yet exposed.

Environment variables:
- `PICO_MAX_RETRIES`, `PICO_RETRY_BASE_DELAY_MS`, `PICO_RETRY_MAX_DELAY_MS` — provider retry tuning.
- `PICO_TRUNCATION_STRATEGY` — `priority` (default) or `smart`.
- `PICO_RUN_INTEGRATION=1` — enable integration tests.

## Evaluation Metrics

`evaluate_qc.py` 支持单 batch 和多 batch：

- Precision / Recall / F1；
- expected / predicted / TP / FP / FN；
- end-to-end completion；
- report field coverage；
- raw data miswrite count；
- total / average processing seconds；
- `evaluation_errors.csv` 中的 FP/FN 明细；
- `resume_metrics.json` 中的简历指标。

## Current Results

请以实际运行生成的 `evaluation_summary.json` 和 `resume_metrics.json` 为准，不在 README 中硬编码未运行数字。当前验证命令会在本地生成这些文件。

## Development Verification

```bash
python -m compileall pico scripts evaluate_qc.py
python -m unittest discover -s tests
```

如果安装了 dev dependencies，也可以运行：

```bash
python -m pytest
python -m ruff check .
```

如果当前环境没有 `pytest` 或 `ruff`，这属于依赖未安装，不代表代码失败。

## Known Limitations

- demo 数据为合成光谱数据和人工注入异常。
- 当前质控基于规则，不是科学结论判定。
- 当前主要支持 CSV，不覆盖所有仪器私有格式。
- 预处理脚本为 demo 级别。
- workflow 使用 fake provider 可稳定演示，真实模型表现取决于模型输出是否遵守工具协议。

## Resume Description

**LabFlow Agent：面向实验数据处理的本地科研流程智能体**

基于本地 Agent Harness 二次开发科研数据流程助手，重构系统提示词与工具注册层，将代码仓库任务流改造为实验数据处理 workflow。系统默认不暴露 `run_shell`、`write_file`、`patch_file`，支持实验目录扫描、metadata 校验、CSV 光谱质控、白名单批量预处理、Markdown 报告生成和 JSON workflow trace。构建多批次合成 benchmark，基于 labels 计算 Precision、Recall、F1、报告字段覆盖率、耗时和误差诊断，并通过 `evaluation_summary.json` 与 `resume_metrics.json` 输出可复核指标。

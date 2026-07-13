# Benchmark

> All numbers below are produced by running the evaluation in this repository. They are not
> aspirational. To reproduce, see [Reproducing](#reproducing) at the bottom.

## Engineering quality

| Metric | Value | Source |
|---|---|---|
| Runtime dependencies | **0** (`dependencies = []`) | `pyproject.toml` |
| Python support | 3.10, 3.11, 3.12 | CI matrix |
| Tests collected | 144 | `pytest --co` |
| Tests passing | **140 passed** | `pytest` (4 skipped: gated integration) |
| Skipped | 4 (provider integration, gated) | `pytest` (set `PICO_RUN_INTEGRATION=1`) |
| `ruff check .` | **clean** | CI `lint` job |
| `ruff format --check .` | **clean** | CI `lint` job |
| Safety suite | green | CI `safety` job |
| CI jobs | `lint` + `test` (3-version matrix) + `safety` | `.github/workflows/ci.yml` |

The 4 skipped tests are real-provider contract tests under `tests/integration/`, gated by
`PICO_RUN_INTEGRATION=1` and provider credentials. They are not failures.

## QC detection benchmark

The synthetic benchmark seeds known anomalies into `batch_demo_001..005` and compares the
predicted findings (`outputs/<batch>/qc_summary.csv`) against ground-truth labels
(`labels/<batch>_labels.json`). Findings are keyed on `(sample_id, check)`, so a finding is
a true positive only if both the sample and the anomaly type match.

| Metric | Value |
|---|---|
| Batches | 5 |
| Samples (metadata rows) | 105 |
| Labeled findings | 55 |
| Predicted findings | 55 |
| True positives | 55 |
| **Precision** | **1.000** |
| **Recall** | **1.000** |
| **F1** | **1.000** |
| False positives | 0 |
| False negatives | 0 |
| Report field coverage | 1.000 (8/8 required sections) |
| Raw-data miswrite count | **0** |
| End-to-end completion | True (qc_summary + report + workflow log present) |
| Average processing seconds | ~0.018 (fake provider; measures tool execution, not LLM latency) |

> `average_processing_seconds` reflects the deterministic fake-provider run and measures
> tool/pipeline execution time per batch, not real-model latency. It is intentionally tiny
> because the fake provider returns scripted responses instantly.

### Anomaly types covered

The benchmark exercises every QC rule across the batches: `missing_metadata_value`,
`duplicate_sample_id`, `missing_spectra_file`, `missing_spectrum_column`,
`negative_intensity`, `x_not_monotonic`, `too_few_points`, `extreme_intensity`,
`file_without_metadata`, and `invalid_filename`.

### The `extreme_intensity` regression

A single extreme outlier (intensity `100000` among ~`125`s) used to inflate population
stdev enough to mask itself (recall dropped to `0.909`, 5 false negatives). v0.2.1 switched
to the **median absolute deviation (MAD)**, which is immune to the outlier, recovering
recall to `1.0`. The old stdev test is kept as a fallback for tiny series.

## Real-data cross-validation

Real public MOF Raman spectra (IBM uRaman-Dataset, CDLA-Sharing-1.0) are **not** part of the
P/R/F1 benchmark - they validate real-data workflow behavior and rule calibration. See
[real-data-validation.md](real-data-validation.md).

| Compound | Points | Negatives | Default findings | `baseline_corrected` findings |
|---|---|---|---|---|
| HKUST-1 | 1806 | 0 | 1 × `extreme_intensity` (warning) | 1 × `extreme_intensity` (warning) |
| Mg-MOF74 | 2768 | 989 (35.8%) | 989 × `negative_intensity` (critical) + 1 × `extreme_intensity` | 1 × `negative_intensity` (warning) + 1 × `extreme_intensity` |

The key result: a configurable QC profile collapses 989 baseline-noise criticals into a
single auditable warning without changing default raw-data behavior.

## Reproducing

```bash
pip install -e ".[dev]"

# Lint
ruff check .
ruff format --check .

# Tests
pytest

# QC benchmark (multi-batch) - writes evaluation_summary.json,
# evaluation_errors.csv, resume_metrics.json
python evaluate_qc.py --pred-dir outputs --labels-dir labels \
  --reports-dir reports --traces-dir traces \
  --output evaluation_summary.json --errors evaluation_errors.csv \
  --resume-metrics resume_metrics.json --with-runtime-metrics
```

`evaluate_qc.py` lives at the repository root (it is also imported by the test suite as
`tests/test_evaluate_qc.py` / `tests/test_evaluate_multi_batch.py`).

## What is not measured

- No RAG / retrieval benchmark exists in this repository; `Recall@5` / `MRR` / retrieval
  latency are **not** reported because there is no retrieval subsystem to measure. The
  memory layer is in-context + durable-file based, not vector retrieval.
- No real-model latency benchmark is committed (provider latency is environment-dependent).
  DeepSeek provider integration tests exist but are gated and not part of the committed
  numbers.
- No scientific-accuracy claim (peak assignment, calibration correctness, interpretation).
  Findings are rule-based QC evidence.

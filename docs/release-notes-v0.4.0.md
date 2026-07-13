# Release v0.4.0 — CLI Workflow & Documentation Polish

**Tag:** `v0.4.0` · **Date:** 2026-07-13

> Copy the block below into the GitHub **Releases → Draft a new release** page, selecting
> the `v0.4.0` tag. This file is a convenience for publishing; the authoritative changelog
> remains [`CHANGELOG.md`](../CHANGELOG.md).

---

## LabFlow Agent v0.4.0

A local-first, **zero-runtime-dependency** agent that turns messy experimental batches into
auditable QC reports. This release surfaces the configurable QC profile at the CLI and
refreshes the project documentation for public/portfolio presentation.

### Highlights

- **`--qc-profile` CLI flag.** The QC profile (introduced in v0.3) is now settable from the
  command line, threading `CLI → Pico.qc_profile → ToolContext.default_qc_profile →
  quality_check` default — mirroring the existing `--lang` path. `argparse` `choices`
  reject unknown profiles at parse time; an explicit tool `qc_profile` still wins.
- **Documentation refresh.** Restructured README with a 30-second pitch (what / why /
  why-not-LangChain / why-XML / why-scientific-data) and Mermaid diagrams for
  architecture, agent loop, QC workflow, and the release timeline. New `docs/` technical
  deep-dives: `architecture.md`, `agent-loop.md`, `workflow.md`,
  `real-data-validation.md`, `benchmark.md`, `release-history.md`.
- **Backward compatible.** No runtime, tool, provider, QC-rule, XML-protocol, or test
  changes. Default `raw_spectrum` behavior is unchanged; the synthetic benchmark stays
  P=R=F1=1.0.

### What's in the box

| Area | Status |
|---|---|
| Runtime dependencies | **0** (`dependencies = []`, stdlib only) |
| Tests | 140 passed, 4 skipped (gated provider integration) |
| Lint / format | `ruff check .` and `ruff format --check .` clean |
| CI | lint + 3.10/3.11/3.12 test matrix + safety gate |
| QC benchmark | Precision = Recall = F1 = **1.000** (TP 55, FP 0, FN 0) |
| Raw-data miswrite count | **0** |
| Real-data cross-validation | IBM uRaman-Dataset MOF Raman (CDLA-Sharing-1.0) |

### Quick start

```bash
git clone <repo> && cd labflow-agent
pip install -e ".[dev]"        # dev adds pytest + ruff; runtime has 0 dependencies

# Deterministic offline demo (fake provider, no model needed)
python -m pico --approval auto --provider fake --max-steps 7 --fake-script '<tool>{"name":"quality_check","args":{"experiment_dir":"data/batch_demo_001","batch_id":"batch_demo_001"}}</tool>||<final>done</final>' "QC demo batch"

# With a real model, baseline-corrected profile
python -m pico --provider openai-compatible --qc-profile baseline_corrected "QC data/batch_demo_001"
```

### The v0.3 → v0.4 story (one paragraph)

Real public MOF Raman data (Mg-MOF74, baseline-corrected) has 989/2768 negative intensity
points — expected baseline noise, not a defect. The default `raw_spectrum` rule correctly
flagged each as `critical`, producing 989 false alarms. v0.3 added configurable QC profiles
that collapse them into one auditable warning under `baseline_corrected`; v0.4 now lets you
set that profile from the CLI, so a whole batch of processed spectra can be QC'd without
re-reporting baseline noise as critical.

### Documentation

- [README](../README.md) — overview, quick start, benchmark, roadmap
- [docs/architecture.md](../docs/architecture.md) — module layout and layers
- [docs/agent-loop.md](../docs/agent-loop.md) — `Pico.ask()` control flow
- [docs/workflow.md](../docs/workflow.md) — the 7-step QC workflow and rules
- [docs/real-data-validation.md](../docs/real-data-validation.md) — real MOF cross-validation
- [docs/benchmark.md](../docs/benchmark.md) — all metrics and how to reproduce
- [docs/release-history.md](../docs/release-history.md) — version timeline
- [CHANGELOG.md](../CHANGELOG.md) — full change history

### Upgrade notes

No breaking changes. Existing `quality_check` calls without `qc_profile` behave exactly as
before (default `raw_spectrum`). `qc_summary.csv` gains a `qc_profile` column; old CSVs
without it render as `raw_spectrum` in reports.

### Known limitations

- `qc_profile` is configurable via tool arg and `--qc-profile`; no env var
  (`PICO_QC_PROFILE`) or metadata auto-inference yet.
- `complete_stream()` is provisional; the `--stream` flag replays the assembled final
  answer rather than parsing a live token stream.
- Preprocessing script (`normalize_csv.py`) is demo-level.
- CSV-centric for spectra; private instrument binary formats are out of scope.

### Artifacts

Source only (pure Python, no build step). Install with `pip install -e .`.

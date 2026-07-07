# Real Public-Data Cross-Validation Report

**Date:** 2026-07-06
**Purpose:** Validate the LabFlow Agent QC framework against real (non-synthetic) public
Raman data, in addition to the synthetic `batch_demo_*` regression batches.

## Data source

- **Dataset:** IBM/uRaman-Dataset (Metal-Organic Framework Raman spectra)
- **URL:** https://github.com/IBM/uRaman-Dataset
- **License:** Community Data License Agreement – Sharing v1.0 (CDLA-Sharing-1.0).
  Permits use, modification, and redistribution.
- **Compounds imported:** HKUST-1, Mg-MOF74 (2 of 4 available; the other two were
  rate-limited on download — sufficient for a cross-validation sample).
- **Converted to LabFlow format:** `data/batch_public_mof_001/`
  (`metadata.csv` + `spectra/<sample>_raman.csv` + `instrument_log.txt`).

This is the **first real (non-synthetic) data** in the project. The synthetic
`batch_demo_001..005` remain as controlled regression fixtures; this batch tests
whether the framework behaves sensibly on real-world data shapes.

## Results

| Compound   | Points | Intensity range      | Negative points | QC findings                          |
|------------|--------|----------------------|------------------|-------------------------------------|
| HKUST-1    | 1806   | [0, 1] (normalized)  | 0                | 1 × `extreme_intensity` (warning)   |
| Mg-MOF74   | 2768   | [-0.162, 1]          | 989 (35.8%)      | 989 × `negative_intensity` (critical), 1 × `extreme_intensity` (warning) |

End-to-end workflow completes cleanly: `quality_check` → `generate_report` →
`export_workflow_log` all succeed; `qc_summary.csv`, `*_qc_report.md`, and
`*_workflow_log.json` are produced.

## Honest finding: the `negative_intensity` rule is too strict for real research data

The QC rule `negative_intensity` flags any `intensity < 0` as `critical`. On the
synthetic batches this is correct (a negative intensity is physically impossible
for raw instrument output). On **real** Mg-MOF74 data, 35.8% of points are
negative — because the published spectrum has been **baseline-corrected**, which
routinely drives noise-region intensities below zero. This is normal and expected
in processed Raman data; it is not a data-integrity defect.

This is exactly the kind of issue that **synthetic data cannot surface**: the
synthetic generator only emits physically-clean values, so the rule looked correct
under unit tests, but it over-reports on real processed spectra.

## Recommended follow-ups

1. **Configurable negative-intensity policy.** ✅ Done (2026-07-06) — see
   [Resolution](#resolution-2026-07-06-configurable-qc-profiles) below. `quality_check`
   gained an optional `qc_profile` argument (`raw_spectrum` | `processed_spectrum` |
   `baseline_corrected`, default `raw_spectrum`).
2. **Intensity-range sniffing / collapse.** ✅ Done — under `processed_spectrum` /
   `baseline_corrected`, a spectrum's negative points collapse into a single per-spectrum
   `warning` (auditable count + min value), rather than N critical findings. (Implemented as
   per-spectrum collapse rather than a batch-level advisory; the rule engine was kept minimal.)
3. Import the remaining two MOFs (HKUST-1 already imported; fetch MeMOF-74,
   ZIF-8) once GitHub raw rate limits clear, to widen the cross-validation.

These are QC-rule tuning items, not framework bugs — the framework correctly
ran the real data through the full pipeline; the rule itself needs a
research-data calibration that synthetic fixtures could not reveal.

## Resolution (2026-07-06): configurable QC profiles

The calibration gap surfaced above is now addressed with a minimal, opt-in QC-profile
mechanism (no agent-loop change, no new dependencies, default behavior preserved).

- `quality_check` accepts `qc_profile` ∈ {`raw_spectrum` (default), `processed_spectrum`,
  `baseline_corrected`}.
- `raw_spectrum` keeps the historical behavior: every `intensity < 0` is a per-point
  `critical` finding. This stays the default, so the synthetic `batch_demo_*` benchmark
  remains P=R=F1=1.0.
- `processed_spectrum` / `baseline_corrected` collapse a spectrum's negative points into a
  single per-spectrum `warning` with a profile-aware message (baseline subtraction can drive
  noise below zero). The negatives are still recorded — `evidence` carries `count` and `min`
  — so the record stays auditable; only severity and explanation change.
- `qc_summary.csv` gains a `qc_profile` column; the QC report shows `QC profile: <name>` and
  adds a profile-aware advisory note when negatives are recorded under a non-raw profile.

### Effect on the Mg-MOF74 batch

| `qc_profile` | Mg-MOF74 `negative_intensity` findings |
|---|---|
| `raw_spectrum` (default) | 989 × `critical` (unchanged) |
| `baseline_corrected` | 1 × `warning` (collapsed, profile-aware message, `count=989` in evidence) |
| `processed_spectrum` | 1 × `warning` (collapsed, profile-aware message) |

HKUST-1 (0 negatives) produces no `negative_intensity` finding under any profile. The
`extreme_intensity` warning behavior is unchanged. Running the Mg-MOF74 batch under
`baseline_corrected` therefore removes the 989-critical explosion while keeping an auditable,
reviewable record — exactly the calibration this cross-validation recommended.

## What this validates

- The LabFlow Agent framework **runs end-to-end on real public Raman data**
  (not just synthetic fixtures): ingestion, CSV parsing, rule-based QC, report
  generation, and workflow-log export all succeed.
- The CDLA-Sharing-1.0 license is compatible with inclusion in the repo.
- The cross-validation surfaced a real calibration gap (`negative_intensity`
  on baseline-corrected data) that the synthetic-only test suite could not —
  which is the point of cross-validating against real data.

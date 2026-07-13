# Real-Data Validation

> Validating the framework against real (non-synthetic) public Raman data. For the full
> cross-validation report with before/after numbers, see
> [real-data-cross-validation.md](real-data-cross-validation.md).

Synthetic fixtures (`batch_demo_001..005`) give perfect, controlled regression signals but
cannot surface calibration gaps that only appear on real-world data shapes. To test the
framework against genuine research spectra, LabFlow includes two real
Metal-Organic-Framework Raman spectra imported from a public dataset.

## Data source

- **Dataset:** [IBM/uRaman-Dataset](https://github.com/IBM/uRaman-Dataset) (MOF Raman spectra)
- **License:** Community Data License Agreement - Sharing v1.0 (CDLA-Sharing-1.0) -
  permits use, modification, and redistribution.
- **Imported compounds:** HKUST-1, Mg-MOF74 (2 of 4 available; the remaining two were
  rate-limited on download).
- **Location:** `data/batch_public_mof_001/` (`metadata.csv` + `spectra/<sample>_raman.csv`
  + `instrument_log.txt`), converted to the LabFlow `x,intensity` CSV format.

This is the **first real (non-synthetic) data** in the project. It is intentionally **not**
mixed into the synthetic Precision/Recall/F1 benchmark - it validates workflow behavior on
realistic data, not benchmark numbers.

## End-to-end run

The real batch runs through the full LabFlow pipeline like any synthetic batch:
`quality_check` -> `generate_report` -> `export_workflow_log` all succeed; `qc_summary.csv`,
`*_qc_report.md`, and `*_workflow_log.json` are produced.

## Observed data shapes

| Compound | Points | Intensity range | Negatives | Default-QC findings |
|---|---|---|---|---|
| HKUST-1 | 1806 | [0, 1] (normalized) | 0 | 1 × `extreme_intensity` (warning) |
| Mg-MOF74 | 2768 | [-0.162, 1] | 989 (35.8%) | 989 × `negative_intensity` (critical) + 1 × `extreme_intensity` (warning) |

## The calibration gap this surfaced

Under the default `raw_spectrum` profile, `negative_intensity` flags every `intensity < 0`
as `critical` - correct for raw instrument output (a raw spectrum cannot be negative). But
Mg-MOF74's published spectrum is **baseline-corrected**, which routinely drives
noise-region intensities below zero. Reporting 989 critical findings for expected baseline
noise is a false alarm, not a data-integrity defect.

This is exactly the kind of issue **synthetic data cannot surface**: the synthetic
generator only emits physically-clean values, so the rule looked correct under unit tests
but over-reports on real processed spectra.

## Resolution: configurable QC profiles (v0.3)

The gap is addressed with a minimal, opt-in profile mechanism (no agent-loop change, default
preserved):

| `qc_profile` | Mg-MOF74 `negative_intensity` findings |
|---|---|
| `raw_spectrum` (default) | 989 × `critical` (unchanged) |
| `baseline_corrected` | 1 × `warning` (collapsed, profile-aware message, `count=989` in evidence) |
| `processed_spectrum` | 1 × `warning` (collapsed, profile-aware message) |

HKUST-1 (0 negatives) produces no `negative_intensity` finding under any profile. The
`extreme_intensity` warning behavior is unchanged. Running Mg-MOF74 under
`baseline_corrected` removes the 989-critical explosion while keeping an auditable,
reviewable record - exactly the calibration this cross-validation recommended. See
[real-data-cross-validation.md](real-data-cross-validation.md) for the full report.

## What this validates

- The framework **runs end-to-end on real public Raman data** (not just synthetic
  fixtures): ingestion, CSV parsing, rule-based QC, report generation, and workflow-log
  export all succeed.
- The CDLA-Sharing-1.0 license is compatible with inclusion in the repo.
- The cross-validation surfaced a real calibration gap (`negative_intensity` on
  baseline-corrected data) that the synthetic-only test suite could not - which is the
  point of cross-validating against real data.

## Scope note

This validates workflow behavior and rule calibration on real data. It does **not** claim
Raman mineral identification accuracy, peak assignment correctness, instrument calibration
correctness, or scientific interpretation quality.

# LabFlow QC Report: batch_demo_003

## 数据概况
- Batch ID: batch_demo_003
- QC summary: outputs/batch_demo_003/qc_summary.csv
- Total findings: 10
- Abnormal samples: 9

## metadata 检查
- missing_metadata_value: 1
- duplicate_sample_id: 1

## 文件一致性检查
- missing_spectra_file: 1
- file_without_metadata: 2
- invalid_filename: 1

## 数值异常检查
- missing_spectrum_column: 1
- negative_intensity: 1
- x_not_monotonic: 1
- too_few_points: 1

## 预处理结果
- Preprocessed CSV files: 15
- Preprocess success: 15
- Preprocess failed: 0
- Preprocess skipped: 6
- outputs/batch_demo_003/preprocessed/sample_001_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_002_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_003_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_005_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_010_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_011_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_012_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_013_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_014_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_015_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_016_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_017_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_018_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_019_raman_normalized.csv
- outputs/batch_demo_003/preprocessed/sample_020_raman_normalized.csv

## 异常样本列表
- badname
- sample_003
- sample_004
- sample_006
- sample_007
- sample_008
- sample_009
- sample_010
- sample_021


## 输出路径
- outputs: outputs/batch_demo_003/
- report: reports/batch_demo_003_qc_report.md
- workflow log: traces/batch_demo_003_workflow_log.json

## 复核建议
- Critical findings should be reviewed against the raw instrument export before interpretation.
- Re-run preprocessing only with registered scripts and preserve raw data unchanged.
- Treat this report as rule-based QC evidence, not an automated scientific conclusion.

## Severity counts
{
  "critical": 7,
  "warning": 3
}
# LabFlow QC Report: batch_public_mof_001

## 数据概况
- Batch ID: batch_public_mof_001
- QC summary: outputs/batch_public_mof_001/qc_summary.csv
- Total findings: 7
- Abnormal samples: 3

## metadata 检查
- No findings in this section.

## 文件一致性检查
- missing_spectra_file: 2
- file_without_metadata: 1
- invalid_filename: 1

## 数值异常检查
- missing_spectrum_column: 2
- too_few_points: 1

## 预处理结果
- Preprocessed CSV files: 0
- Preprocess success: 0
- Preprocess failed: 0
- Preprocess skipped: 0

## 异常样本列表
- HKUST-1
- Mg-MOF74
- metadata


## 输出路径
- outputs: outputs/batch_public_mof_001/
- report: reports/batch_public_mof_001_qc_report.md
- workflow log: traces/batch_public_mof_001_workflow_log.json

## 复核建议
- Critical findings should be reviewed against the raw instrument export before interpretation.
- Re-run preprocessing only with registered scripts and preserve raw data unchanged.
- Treat this report as rule-based QC evidence, not an automated scientific conclusion.

## Severity counts
{
  "critical": 5,
  "warning": 2
}
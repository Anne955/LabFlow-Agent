from __future__ import annotations

import unittest

from pico.agent.intent import (
    COMPARE_BATCHES,
    EXPLAIN_FINDING,
    FULL_QC_WORKFLOW,
    METADATA_ONLY,
    PREPROCESS_ONLY,
    QC_ONLY,
    REPORT_ONLY,
    RESUME_FAILED_WORKFLOW,
    SHOW_SUMMARY,
    detect_intent,
)


class AgentIntentTests(unittest.TestCase):
    def test_chinese_acceptance_intents(self):
        cases = {
            "完整检查 batch_demo_001 并生成报告": FULL_QC_WORKFLOW,
            "只检查 batch_demo_001 的 metadata": METADATA_ONLY,
            "只跑 batch_demo_001 的 QC": QC_ONLY,
            "重新生成 batch_demo_001 的报告": REPORT_ONLY,
            "跳过 critical 样本，对 batch_demo_001 做归一化": PREPROCESS_ONLY,
            "sample_008 为什么异常": EXPLAIN_FINDING,
            "对比 batch_demo_001 和 batch_demo_002": COMPARE_BATCHES,
            "继续失败的 batch_demo_003 workflow": RESUME_FAILED_WORKFLOW,
            "显示 batch_demo_001 的输出汇总": SHOW_SUMMARY,
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(detect_intent(prompt).intent, expected)

    def test_explain_priority_over_qc_and_report(self):
        result = detect_intent("解释 batch_demo_001 的 F0001 QC finding 并生成报告")
        self.assertEqual(result.intent, EXPLAIN_FINDING)


if __name__ == "__main__":
    unittest.main()

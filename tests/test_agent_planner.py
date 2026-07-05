from __future__ import annotations

import json
import unittest
from pathlib import Path

from pico.agent.intent import (
    COMPARE_BATCHES,
    EXPLAIN_FINDING,
    FULL_QC_WORKFLOW,
    METADATA_ONLY,
    PREPROCESS_ONLY,
    REPORT_ONLY,
)
from pico.agent.planner import build_plan


class AgentPlannerTests(unittest.TestCase):
    def test_full_workflow_plan_has_seven_steps(self):
        plan = build_plan("完整检查 data/batch_demo_001 并生成报告")
        self.assertEqual(plan.intent, FULL_QC_WORKFLOW)
        self.assertEqual(plan.inputs.batch_id, "batch_demo_001")
        self.assertEqual(plan.inputs.experiment_dir, "data/batch_demo_001")
        self.assertEqual(
            [step.name for step in plan.steps],
            [
                "scan_experiment_dir",
                "inspect_table",
                "quality_check",
                "run_preprocess_script",
                "summarize_outputs",
                "generate_report",
                "export_workflow_log",
            ],
        )
        preprocess = plan.steps[3]
        self.assertTrue(preprocess.args["skip_critical"])
        self.assertFalse(preprocess.args["only_qc_passed"])
        self.assertEqual(preprocess.args["input_dir"], "data/batch_demo_001/spectra")

    def test_metadata_only_plan(self):
        plan = build_plan("只检查 batch_demo_001 的 metadata")
        self.assertEqual(plan.intent, METADATA_ONLY)
        self.assertEqual(
            [step.name for step in plan.steps], ["scan_experiment_dir", "inspect_table"]
        )

    def test_report_only_plan(self):
        plan = build_plan("重新生成 batch_demo_001 的报告")
        self.assertEqual(plan.intent, REPORT_ONLY)
        self.assertEqual(
            [step.name for step in plan.steps],
            ["summarize_outputs", "generate_report", "export_workflow_log"],
        )

    def test_preprocess_plan_with_critical_skip(self):
        plan = build_plan("跳过 critical 样本，对 batch_demo_001 做归一化")
        self.assertEqual(plan.intent, PREPROCESS_ONLY)
        self.assertEqual(
            [step.name for step in plan.steps], ["quality_check", "run_preprocess_script"]
        )
        self.assertTrue(plan.steps[1].args["skip_critical"])

    def test_only_qc_passed_and_no_skip_parsing(self):
        plan = build_plan("只预处理 batch_demo_001，只处理 QC 通过的样本")
        self.assertTrue(plan.inputs.only_qc_passed)
        self.assertTrue(plan.steps[1].args["only_qc_passed"])
        no_skip = build_plan("Preprocess batch_demo_001 and do not skip critical samples")
        self.assertFalse(no_skip.inputs.skip_critical)

    def test_explain_finding_internal_steps(self):
        plan = build_plan("解释 batch_demo_001 里的 F0003 是什么问题")
        self.assertEqual(plan.intent, EXPLAIN_FINDING)
        self.assertEqual([step.name for step in plan.steps], ["read_qc_summary", "explain_finding"])
        self.assertTrue(all(step.kind == "internal" for step in plan.steps))
        self.assertEqual(plan.steps[0].args["finding_id"], "F0003")

    def test_explain_sample_internal_steps(self):
        plan = build_plan("sample_008 为什么异常")
        self.assertEqual(plan.intent, EXPLAIN_FINDING)
        self.assertEqual(plan.inputs.sample_id, "sample_008")
        self.assertEqual([step.name for step in plan.steps], ["read_qc_summary", "explain_finding"])

    def test_compare_batches(self):
        plan = build_plan("对比 batch_demo_001 和 batch_demo_002 的 QC 结果")
        self.assertEqual(plan.intent, COMPARE_BATCHES)
        self.assertEqual(plan.inputs.batch_ids, ("batch_demo_001", "batch_demo_002"))
        self.assertEqual(
            [step.name for step in plan.steps],
            ["summarize_outputs", "summarize_outputs", "compare_batch_summaries"],
        )
        self.assertEqual(plan.steps[-1].kind, "internal")

    def test_templates_exist_and_are_json_parseable(self):
        root = Path(__file__).resolve().parents[1]
        for name in [
            "full_qc",
            "metadata_only",
            "qc_only",
            "preprocess_only",
            "report_only",
            "explain_finding",
        ]:
            path = root / "workflows" / f"{name}.yaml"
            self.assertTrue(path.is_file())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("intent", data)
            self.assertIn("steps", data)


if __name__ == "__main__":
    unittest.main()

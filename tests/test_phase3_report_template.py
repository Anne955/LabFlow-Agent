from __future__ import annotations

import unittest

from pico.report_template import REPORT_SECTIONS, required_section_titles, section_title


class ReportTemplateTests(unittest.TestCase):
    def test_has_all_expected_keys(self):
        keys = {s["key"] for s in REPORT_SECTIONS}
        expected_keys = {
            "data_overview",
            "metadata_check",
            "file_consistency",
            "numeric_anomaly",
            "preprocess_results",
            "abnormal_samples",
            "output_paths",
            "review_advice",
            "severity_counts",
        }
        for expected in expected_keys:
            self.assertIn(expected, keys)

    def test_zh_titles_match_legacy(self):
        titles = required_section_titles("zh")
        self.assertIn("数据概况", titles)
        self.assertIn("metadata 检查", titles)

    def test_en_titles_available(self):
        self.assertEqual(section_title("data_overview", "en"), "Data Overview")

    def test_default_lang_is_zh(self):
        self.assertEqual(section_title("data_overview"), "数据概况")


if __name__ == "__main__":
    unittest.main()

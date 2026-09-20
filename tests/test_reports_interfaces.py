import json
import tempfile
import unittest
from pathlib import Path

from analysis import analyze_log
from reports import build_report, export_claude_generated_md, export_report_json, export_report_md
from reports.exporters import ARTIFACT_ALLOWLIST
from schemas import Report


class ReportInterfaceTests(unittest.TestCase):
    def make_report(self):
        return build_report(analyze_log('{"unrelated":1}'), analysis_id="a-1",
                            session_id="s-1", llm_enabled=False)

    def test_export_artifacts_are_allowlisted(self):
        self.assertEqual(set(ARTIFACT_ALLOWLIST), {"report.md", "report.json", "CLAUDE.generated.md"})

    def test_builder_returns_valid_report(self):
        report = self.make_report()
        self.assertEqual(Report.model_validate_json(report.model_dump_json()), report)
        self.assertEqual(report.status, "insufficient_data")

    def test_exporters_write_actual_report(self):
        report = self.make_report()
        with tempfile.TemporaryDirectory() as folder:
            for exporter, name in ((export_report_json, "report.json"),
                                   (export_report_md, "report.md"),
                                   (export_claude_generated_md, "CLAUDE.generated.md")):
                path = exporter(report, Path(folder) / "nested" / name)
                self.assertTrue(path.read_text())
                if name.endswith(".json"):
                    self.assertEqual(json.loads(path.read_text()), report.model_dump(mode="json"))
                elif name == "report.md":
                    self.assertIn(report.summary, path.read_text())

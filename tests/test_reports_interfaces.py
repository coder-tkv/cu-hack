import unittest

from reports import (
    build_report,
    export_claude_generated_md,
    export_report_json,
    export_report_md,
)
from reports.exporters import ARTIFACT_ALLOWLIST


class ReportInterfaceTests(unittest.TestCase):
    def test_export_artifacts_are_allowlisted(self) -> None:
        self.assertEqual(
            ARTIFACT_ALLOWLIST,
            {"report.md", "report.json", "CLAUDE.generated.md"},
        )

    def test_builder_interface_exists(self) -> None:
        with self.assertRaises(NotImplementedError):
            build_report(
                analysis_id="a-1",
                session_id="s-1",
                status="assembling",
                session_info=None,
            )

    def test_exporter_interfaces_exist(self) -> None:
        for exporter in (
            export_report_md,
            export_report_json,
            export_claude_generated_md,
        ):
            with self.subTest(exporter=exporter.__name__):
                with self.assertRaises(NotImplementedError):
                    exporter({}, "/tmp/report")


if __name__ == "__main__":
    unittest.main()

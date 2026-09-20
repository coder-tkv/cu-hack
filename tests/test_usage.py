import unittest
from pathlib import Path

from analysis import extract_usage_records, summarize_usage


FIXTURE = Path(__file__).parent / "fixtures" / "claude_code_real_excerpt.jsonl"


class UsageTests(unittest.TestCase):
    def test_deduplicates_original_agent_usage_by_request_id(self) -> None:
        with FIXTURE.open(encoding="utf-8") as lines:
            extraction = extract_usage_records(lines)
        summary = summarize_usage(extraction.records)

        self.assertEqual(len(extraction.records), 2)
        self.assertEqual(
            [record.request_id for record in extraction.records],
            ["req_011Ce1Eub4ycLnrGd7475eLP", "req_011Ce1EuxgjmA4XZkfq56taT"],
        )
        self.assertEqual(extraction.records[0].source_lines, [1, 2, 3])
        self.assertEqual(extraction.records[1].source_lines, [5, 6])
        self.assertEqual(summary.request_count, 2)
        self.assertEqual(summary.input_tokens, 6)
        self.assertEqual(summary.output_tokens, 264)
        self.assertEqual(summary.cache_creation_input_tokens, 8041)
        self.assertEqual(summary.cache_read_input_tokens, 30718)

    def test_reports_conflicting_values_for_duplicate_request(self) -> None:
        extraction = extract_usage_records(
            [
                '{"requestId":"req-1","message":{"id":"msg-1",'
                '"usage":{"input_tokens":3,"output_tokens":10}}}\n',
                '{"requestId":"req-1","message":{"id":"msg-1",'
                '"usage":{"input_tokens":3,"output_tokens":11}}}\n',
            ]
        )

        self.assertEqual(len(extraction.records), 1)
        self.assertEqual(extraction.records[0].output_tokens, 11)
        self.assertEqual(
            extraction.records[0].warnings,
            ["request_id=req-1: conflicting output_tokens: 10 != 11"],
        )

    def test_summarize_merges_records_with_missing_first_value(self) -> None:
        from schemas import UsageRecord

        summary = summarize_usage(
            [
                UsageRecord(request_id="req-1", input_tokens=None),
                UsageRecord(request_id="req-1", input_tokens=10),
            ]
        )

        self.assertEqual(summary.input_tokens, 10)

    def test_known_sum_reports_partial_coverage(self) -> None:
        from schemas import UsageRecord

        summary = summarize_usage(
            [
                UsageRecord(request_id="req-1", input_tokens=10),
                UsageRecord(request_id="req-2"),
            ]
        )

        self.assertEqual(summary.input_tokens, 10)
        self.assertTrue(any("1 из 2" in item for item in summary.limitations))

    def test_accepts_snake_case_request_id(self) -> None:
        extraction = extract_usage_records(
            ['{"request_id":"req-1","message":{"usage":{"input_tokens":10}}}\n']
        )

        self.assertEqual([record.request_id for record in extraction.records], ["req-1"])

    def test_returns_none_when_token_category_is_absent(self) -> None:
        extraction = extract_usage_records(
            ['{"requestId":"req-1","message":{"id":"msg-1","usage":{}}}\n']
        )

        summary = summarize_usage(extraction.records)

        self.assertEqual(summary.request_count, 1)
        self.assertIsNone(summary.input_tokens)
        self.assertIn("input_tokens отсутствуют во всех записях usage", summary.limitations)


if __name__ == "__main__":
    unittest.main()

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


class IntegratedUsageTests(unittest.TestCase):
    def test_api_uses_final_usage_once_and_keeps_missing_category_unknown(self):
        from analysis import analyze_log
        from reports import build_report
        from reports.builder import to_steps
        import json
        rows = [{"type": "assistant", "sessionId": "s", "requestId": "req",
                 "message": {"id": "msg", "content": [{"type": "text", "text": "working"}],
                             "usage": {"input_tokens": 3, "output_tokens": output},
                             "stop_reason": stop}}
                for output, stop in [(1, None), (9, "tool_use"), (2, None)]]
        raw = analyze_log("\n".join(json.dumps(row) for row in rows))
        self.assertEqual(raw["kpi"]["tokensOut"], 9)
        steps = to_steps(raw, "server-session")
        self.assertEqual(sum(s.usage is not None for s in steps), 1)
        self.assertTrue(all(s.usage_ref == "req" for s in steps))
        report = build_report(raw, analysis_id="a", session_id="s", llm_enabled=False)
        metrics = {m.key: m for m in report.metrics}
        self.assertEqual(metrics["tokensOut"].value, 9)
        self.assertIsNone(metrics["cacheRead"].value)
        self.assertTrue(metrics["tokensOut"].limitations)

    def test_identical_request_ids_in_different_sessions_are_not_merged(self):
        import json
        lines = [json.dumps({"sessionId": sid, "requestId": "req", "message": {
            "usage": {"input_tokens": 3}}}) for sid in ("a", "b")]
        extraction = extract_usage_records(lines)
        self.assertEqual(len(extraction.records), 2)
        self.assertEqual(summarize_usage(extraction.records).input_tokens, 6)

    def test_message_id_fallback_and_invalid_token_values(self):
        extraction = extract_usage_records(['{"message":{"id":"m","usage":'
            '{"input_tokens":true,"output_tokens":-1,"cache_read_input_tokens":5}}}'])
        self.assertEqual(extraction.records[0].request_id, "m")
        self.assertIsNone(extraction.records[0].input_tokens)
        self.assertIsNone(extraction.records[0].output_tokens)

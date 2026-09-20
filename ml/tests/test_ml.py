import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

import httpx2 as httpx
from openai import OpenAI
from pydantic import ValidationError

from agent_review.prepare import open_log, prepare_stream
from agent_review.redaction import redact
from agent_review.reviewer import preview, review
from agent_review.schemas import Judgment, ReviewInput


EXAMPLE = Path(__file__).parents[1] / "examples" / "packet.json"


def packet():
    return ReviewInput.model_validate_json(EXAMPLE.read_text())


def judgment(candidate_id="repeated-test-command", refs=None):
    return Judgment(
        candidate_id=candidate_id, assessment="inefficient",
        evidence_step_ids=refs if refs is not None else ["step-1", "step-2"],
        explanation="Команда повторялась после одинаковой ошибки.",
        likely_cause=None, action="Проверить scripts в package.json.",
        verification="Проверить следующую сессию.", rule_text="Проверь доступную команду до запуска.",
        limitations=[],
    )


def fake_client(result=None, status="completed", error=None):
    def parse(**kwargs):
        if error:
            raise error
        return SimpleNamespace(status=status, output_parsed=result, usage=SimpleNamespace(
            input_tokens=100, output_tokens=20, total_tokens=120))
    return SimpleNamespace(responses=SimpleNamespace(parse=parse))


class MLTests(unittest.TestCase):
    def test_preview_works_without_key_and_does_not_mutate_input(self):
        data = packet()
        data.task = "password=EXAMPLE_SECRET"
        with patch.dict(os.environ, {}, clear=True), patch("agent_review.reviewer.OpenAI") as client:
            output = preview(data)
            client.assert_not_called()
        self.assertEqual(output["mode"], "preview_only_no_model_called")
        self.assertNotIn("EXAMPLE_SECRET", json.dumps(output))
        self.assertIn("EXAMPLE_SECRET", data.task)

    def test_valid_result_and_analysis_usage(self):
        report = review(packet(), client=fake_client(judgment()))
        self.assertEqual(report.status, "complete")
        self.assertEqual(report.candidates_reviewed, 1)
        self.assertEqual(report.analysis_usage["total_tokens"], 120)
        self.assertEqual(report.findings[0].candidate.facts, packet().candidates[0].facts)

    def test_hallucinated_reference_is_rejected(self):
        report = review(packet(), client=fake_client(judgment(refs=["invented-step"])))
        self.assertEqual(report.status, "partial")
        self.assertIsNone(report.findings[0].judgment)
        self.assertEqual(report.analysis_usage["total_tokens"], 120)

    def test_empty_reference_and_wrong_candidate_are_rejected(self):
        for result in [judgment(refs=[]), judgment(candidate_id="made-up")]:
            with self.subTest(result=result):
                self.assertEqual(review(packet(), client=fake_client(result)).status, "partial")

    def test_inefficient_requires_action(self):
        answer = judgment()
        answer.action = None
        self.assertEqual(review(packet(), client=fake_client(answer)).status, "partial")

    def test_reasonable_does_not_need_artificial_recommendation(self):
        answer = judgment()
        answer.assessment = "reasonable"
        answer.action = answer.rule_text = answer.verification = None
        self.assertEqual(review(packet(), client=fake_client(answer)).status, "complete")

    def test_refused_and_incomplete_results(self):
        for client in [fake_client(None), fake_client(judgment(), status="incomplete")]:
            report = review(packet(), client=client)
            self.assertEqual(report.findings[0].error, "incomplete_or_refused")

    def test_api_exception_does_not_expose_raw_content(self):
        report = review(packet(), client=fake_client(error=RuntimeError("PRIVATE RAW CONTENT")))
        self.assertEqual(report.status, "partial")
        self.assertNotIn("PRIVATE RAW CONTENT", report.model_dump_json())

    def test_budget_preserves_unexplained_candidates(self):
        data = packet()
        data.candidates.append(data.candidates[0].model_copy(update={"candidate_id": "second"}))
        report = review(data, max_calls=1, client=fake_client(judgment()))
        self.assertEqual(report.api_calls, 1)
        self.assertEqual(report.findings[1].error, "call_budget_exceeded")
        self.assertEqual(report.candidates_total, 2)
        self.assertEqual(len(preview(data, max_calls=1)["skipped"]), 1)

    def test_oversized_packet_is_not_silently_truncated(self):
        data = packet()
        data.candidates[0].facts = ["Ж" * 30_000]
        result = review(data, client=fake_client(judgment()))
        self.assertEqual(result.api_calls, 0)
        self.assertEqual(result.findings[0].error, "request_too_large")

    def test_no_candidates_no_paid_request(self):
        with patch.dict(os.environ, {}, clear=True), patch("agent_review.reviewer.OpenAI") as client:
            report = review(ReviewInput(source_id="empty", candidates=[]))
            client.assert_not_called()
        self.assertEqual(report.status, "no_candidates")

    def test_duplicate_ids_fail_at_contract_boundary(self):
        data = packet().model_dump()
        data["candidates"].append(data["candidates"][0])
        with self.assertRaises(ValidationError):
            ReviewInput.model_validate(data)

    def test_missing_key_has_clear_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                review(packet())

    def test_redaction_common_patterns(self):
        text = 'api_key="demo-secret" password=hunter2 Bearer example.token /Users/alice/project'
        clean = redact(text)
        for secret in ["demo-secret", "hunter2", "example.token", "alice"]:
            self.assertNotIn(secret, clean)
        self.assertIn("project", clean)

    def test_real_sdk_serializes_schema_and_parses_response_without_network(self):
        def respond(request):
            sent = json.loads(request.content)
            self.assertFalse(sent["store"])
            self.assertEqual(sent["text"]["format"]["type"], "json_schema")
            self.assertTrue(sent["text"]["format"]["strict"])
            self.assertNotIn("tools", sent)
            return httpx.Response(200, json={
                "id": "resp_test", "object": "response", "created_at": 0,
                "status": "completed", "model": sent["model"],
                "output": [{"type": "message", "id": "msg_test", "role": "assistant",
                            "status": "completed", "content": [{"type": "output_text",
                            "text": judgment().model_dump_json(), "annotations": []}]}],
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                "error": None, "incomplete_details": None,
            })
        with OpenAI(api_key="test-only", http_client=httpx.Client(
                transport=httpx.MockTransport(respond)), max_retries=0) as client:
            report = review(packet(), client=client)
        self.assertEqual(report.status, "complete")


class PreparationTests(unittest.TestCase):
    def records(self):
        return [
            {"type": "user", "sessionId": "s", "message": {"content": "Проверь тесты"}},
            {"type": "assistant", "sessionId": "s", "message": {"content": [
                {"type": "thinking", "thinking": "DO NOT EXPORT"},
                {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "npm test"}}]}},
            {"type": "assistant", "sessionId": "s", "message": {"content": [
                {"type": "text", "text": "Другой шаг между вызовом и ответом"}]}},
            {"type": "user", "sessionId": "s", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "tool-1", "is_error": True, "content": "Missing script"}]}},
        ]

    def encode(self, records):
        return b"\n".join(json.dumps(r).encode() for r in records) + b"\n"

    def test_explicit_error_links_call_by_id_and_ignores_thinking(self):
        result, counts = prepare_stream(io.BytesIO(self.encode(self.records())))
        self.assertEqual(counts["tool_calls"], 1)
        self.assertEqual(counts["explicit_error_results"], 1)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.task, "Проверь тесты")
        self.assertNotIn("DO NOT EXPORT", result.model_dump_json())
        self.assertIn("line-2-block-1", [e.step_id for e in result.candidates[0].evidence])

    def test_error_word_is_not_explicit_failure(self):
        records = self.records()
        records[-1]["message"]["content"][0].update(is_error=False, content="error_handler.py")
        result, _ = prepare_stream(io.BytesIO(self.encode(records)))
        self.assertEqual(result.candidates, [])

    def test_truncated_last_line_and_service_records(self):
        source = self.encode(self.records() + [{"type": "future-event"}]) + b'{"broken"'
        result, counts = prepare_stream(io.BytesIO(source))
        self.assertEqual(counts["invalid_lines"], 1)
        self.assertEqual(counts["service_or_unknown_records"], 1)
        self.assertEqual(len(result.candidates), 1)

    def test_missing_call_is_a_limitation_not_a_crash(self):
        result, _ = prepare_stream(io.BytesIO(self.encode([self.records()[-1]])))
        self.assertTrue(any("missing" in s for s in result.candidates[0].limitations))

    def test_mixed_sessions_are_not_combined(self):
        records = self.records()
        records[-1]["sessionId"] = "another"
        with self.assertRaisesRegex(ValueError, "one session"):
            prepare_stream(io.BytesIO(self.encode(records)))

    def test_zip_member_read_never_extracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("../unexpected.jsonl", self.encode(self.records()))
            with open_log(path, "../unexpected.jsonl") as source:
                result, _ = prepare_stream(source)
            self.assertEqual(len(result.candidates), 1)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["logs.zip"])


if __name__ == "__main__":
    unittest.main()

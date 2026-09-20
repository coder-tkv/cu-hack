import asyncio
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

import httpx2 as httpx
from openai import AsyncOpenAI, AuthenticationError
from pydantic import ValidationError
from agent_review.grounding import GroundingError, render_judgment
from agent_review.prepare import open_log, prepare_stream
from agent_review.redaction import redact
from agent_review.reviewer import preview, review, review_async
from agent_review.schemas import Candidate, Citation, ModelDecision, ReviewInput

EXAMPLE = Path(__file__).parents[1] / "examples" / "packet.json"
FAIL = ("Bash", {"command": "npm test"}, "Missing script: test", True)
READS = [("Read", {"file_path": f"src/{n}.py"}, f"content of {n}", False) for n in "abc"]


def packet():
    return ReviewInput.model_validate_json(EXAMPLE.read_text())


def decision(c=None, assessment="inefficient", advice="change_approach", alternative=None):
    c = c or packet().candidates[0]
    return ModelDecision(candidate_id=c.candidate_id, assessment=assessment,
        fact_ids=[f.fact_id for f in c.facts], citations=[Citation(step_id=e.step_id, quote=e.text[:150]) for e in c.evidence],
        advice=advice, alternative_id=alternative)


def fake(result=None, status="completed", error=None):
    async def parse(**kwargs):
        if error: raise error
        return SimpleNamespace(status=status, output_parsed=result, usage=SimpleNamespace(input_tokens=100, output_tokens=20, total_tokens=120))
    return SimpleNamespace(responses=SimpleNamespace(parse=parse))


def two():
    p = packet()
    p.candidates.append(p.candidates[0].model_copy(update={"candidate_id": "second"}))
    return p


def trace(actions):
    records = []
    def add(role, content):
        n = len(records)
        records.append({"type": role, "uuid": f"e{n}", "parentUuid": f"e{n-1}" if n else None,
            "sessionId": "s", "message": {"id": f"m{n}", "content": content}})
    add("user", "Проверь проект и запусти тесты")
    for action in actions:
        if isinstance(action, str): add("user", action); continue
        name, args, result, error = action
        cid = f"call-{len(records)}"
        add("assistant", [{"type": "tool_use", "id": cid, "name": name, "input": args}])
        add("user", [{"type": "tool_result", "tool_use_id": cid, "is_error": error, "content": result}])
    return records


def encoded(records):
    return b"\n".join(json.dumps(r).encode() for r in records) + b"\n"


def prepare(records):
    return prepare_stream(io.BytesIO(encoded(records)))


class GroundingTests(unittest.TestCase):
    def test_only_backend_facts_become_problem_text(self):
        c = packet().candidates[0]
        r = render_judgment(c, decision())
        self.assertEqual(r.explanation, "\n".join(f.text for f in c.facts))
        self.assertIsNone(r.likely_cause)

    def test_arbitrary_problem_cause_and_command_forbidden(self):
        for field in ("explanation", "likely_cause", "command", "action"):
            d = decision().model_dump(); d[field] = "Invented context"
            with self.subTest(field=field), self.assertRaises(ValidationError): ModelDecision.model_validate(d)

    def test_hallucinated_quote_rejected_even_with_real_step_id(self):
        d = decision(); d.citations[0].quote = "npm run invented-command"
        with self.assertRaisesRegex(GroundingError, "quote_not_supported"): render_judgment(packet().candidates[0], d)

    def test_unknown_step_fact_and_candidate(self):
        for field in ("step", "fact", "candidate"):
            d = decision()
            if field == "step": d.citations[0].step_id = "fake"
            if field == "fact": d.fact_ids = ["fake"]
            if field == "candidate": d.candidate_id = "fake"
            with self.subTest(field=field), self.assertRaises(GroundingError): render_judgment(packet().candidates[0], d)

    def test_missing_fact_evidence(self):
        d = decision(); d.citations.pop()
        with self.assertRaisesRegex(GroundingError, "missing_fact_evidence"): render_judgment(packet().candidates[0], d)

    def test_cycle_needs_all_facts(self):
        d = decision(); d.fact_ids = d.fact_ids[:1]
        with self.assertRaisesRegex(GroundingError, "incomplete_cycle_evidence"): render_judgment(packet().candidates[0], d)

    def test_lone_error_cannot_be_inefficient(self):
        p, _ = prepare(trace([FAIL])); c = p.candidates[0]
        with self.assertRaisesRegex(GroundingError, "insufficient_basis"): render_judgment(c, decision(c, advice="inspect_failure"))

    def test_incomplete_context_only_uncertain_or_reasonable(self):
        c = packet().candidates[0]; c.context_complete = False
        with self.assertRaisesRegex(GroundingError, "insufficient_basis"): render_judgment(c, decision(c))
        self.assertIsNone(render_judgment(c, decision(c, "uncertain")).rule_text)

    def test_reasonable_needs_no_rule(self):
        r = render_judgment(packet().candidates[0], decision(assessment="reasonable", advice="none"))
        self.assertIsNone(r.action)

    def test_unobserved_utility_rejected(self):
        p, _ = prepare(trace(READS)); c = p.candidates[0]
        with self.assertRaisesRegex(GroundingError, "unobserved_alternative"):
            render_judgment(c, decision(c, "uncertain", "reuse_observed_tool", "imaginary-rg"))

    def test_observed_alternative_requires_quotes_and_is_only_conditional(self):
        p, _ = prepare(trace([("Bash", {"command": "rg TODO src"}, "src/a.py: TODO", False), *READS]))
        c = next(c for c in p.candidates if c.kind == "read_many_files")
        self.assertEqual(c.alternatives[0].tool_name, "rg")
        d = decision(c, "uncertain", "reuse_observed_tool", c.alternatives[0].alternative_id)
        self.assertIn("не доказана", render_judgment(c, d).action)
        d.citations = [q for q in d.citations if q.step_id not in c.alternatives[0].evidence_step_ids]
        with self.assertRaisesRegex(GroundingError, "missing_alternative_evidence"): render_judgment(c, d)


class ReviewerTests(unittest.TestCase):
    def test_preview_without_key_masks_secrets_and_preserves_original(self):
        p = packet(); p.task = "password=EXAMPLE_SECRET"
        with patch.dict(os.environ, {}, clear=True), patch("agent_review.reviewer.AsyncOpenAI") as client:
            r = preview(p); client.assert_not_called()
        self.assertNotIn("EXAMPLE_SECRET", json.dumps(r))
        self.assertIn("EXAMPLE_SECRET", p.task)
        self.assertEqual(r["requests"][0]["text_format"]["title"], "ModelDecision")

    def test_valid_result_and_usage(self):
        r = review(packet(), client=fake(decision()))
        self.assertEqual(r.status, "complete")
        self.assertEqual(r.analysis_usage["total_tokens"], 120)

    def test_bad_quote_is_partial_and_billed_usage_preserved(self):
        d = decision(); d.citations[0].quote = "not in source"
        r = review(packet(), client=fake(d))
        self.assertEqual(r.status, "partial")
        self.assertEqual(r.findings[0].error, "grounding:quote_not_supported")
        self.assertEqual(r.analysis_usage["total_tokens"], 120)

    def test_invented_context_does_not_reach_report(self):
        d = decision().model_dump(); d["explanation"] = "Agent deleted a database"
        r = review(packet(), client=fake(d))
        self.assertEqual(r.status, "partial")
        self.assertNotIn("deleted a database", r.model_dump_json())

    def test_request_budget(self):
        r = review(two(), max_calls=1, client=fake(decision()))
        self.assertEqual(r.api_calls, 1)
        self.assertEqual(r.findings[1].error, "call_budget_exceeded")

    def test_priority_shared_by_preview_and_review(self):
        p = two(); p.candidates[0].priority = "low"
        self.assertEqual(json.loads(preview(p, max_calls=1)["requests"][0]["input"])["candidate"]["candidate_id"], "second")
        r = review(p, max_calls=1, client=fake(decision(p.candidates[1])))
        self.assertEqual(r.findings[0].candidate.candidate_id, "second")
        self.assertEqual(r.candidates_reviewed, 1)

    def test_empty_and_oversized_inputs_never_call_model(self):
        with patch.dict(os.environ, {}, clear=True): self.assertEqual(review(ReviewInput(source_id="empty")).status, "no_candidates")
        p = packet(); p.warnings = ["Ж" * 30_000]
        r = review(p, client=fake(decision()))
        self.assertEqual(r.api_calls, 0)
        self.assertEqual(r.findings[0].error, "request_too_large")

    def test_refusal_incomplete_and_private_exception(self):
        for client in [fake(None), fake(decision(), "incomplete")]:
            self.assertEqual(review(packet(), client=client).findings[0].error, "incomplete_or_refused")
        self.assertNotIn("PRIVATE RAW CONTENT", review(packet(), client=fake(error=RuntimeError("PRIVATE RAW CONTENT"))).model_dump_json())

    def test_deadline_cancels_hung_call_and_skips_remaining(self):
        cancelled = []
        async def parse(**kwargs):
            try: await asyncio.sleep(60)
            finally: cancelled.append(True)
        start = time.monotonic()
        r = review(two(), deadline_seconds=0.03, client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(cancelled, [True])
        self.assertEqual(r.api_calls, 1)
        self.assertTrue(all(f.error == "analysis_deadline_exceeded" for f in r.findings))

    def test_external_cancel_propagates(self):
        async def parse(**kwargs): raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError): review(packet(), client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))

    def test_bad_key_stops_remaining_calls(self):
        err = AuthenticationError("private", response=httpx.Response(401, request=httpx.Request("POST", "https://example.invalid")), body=None)
        r = review(two(), client=fake(error=err))
        self.assertEqual(r.api_calls, 1)
        self.assertTrue(all(f.error == "provider_unavailable:AuthenticationError" for f in r.findings))

    def test_missing_key_and_sync_inside_async_errors(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"): review(packet())
        async def run():
            with self.assertRaisesRegex(RuntimeError, "review_async"): review(packet())
        asyncio.run(run())

    def test_real_async_sdk_with_mock_http(self):
        def respond(request):
            sent = json.loads(request.content)
            self.assertFalse(sent["store"])
            self.assertTrue(sent["text"]["format"]["strict"])
            self.assertNotIn("tools", sent)
            if sent["model"] == "gpt-5.6-sol":
                self.assertEqual(sent["reasoning"], {"effort": "low"})
            else:
                self.assertNotIn("reasoning", sent)
            return httpx.Response(200, json={"id": "resp_test", "object": "response", "created_at": 0,
                "status": "completed", "model": sent["model"], "output": [{"type": "message", "id": "msg_test",
                "role": "assistant", "status": "completed", "content": [{"type": "output_text",
                "text": decision().model_dump_json(), "annotations": []}]}],
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}, "error": None, "incomplete_details": None})
        async def run(model):
            async with AsyncOpenAI(api_key="test-only", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))) as client:
                return await review_async(packet(), client=client, model=model)
        for model in ("gpt-5.6-sol", "gpt-4.1-2025-04-14"):
            with self.subTest(model=model):
                self.assertEqual(asyncio.run(run(model)).status, "complete")


class PreparationTests(unittest.TestCase):
    def test_three_failures_form_one_high_priority_group(self):
        p, n = prepare(trace([FAIL] * 3)); c = p.candidates[0]
        self.assertEqual(len(p.candidates), 1)
        self.assertEqual(c.kind, "repeated_tool_call")
        self.assertEqual(len(c.evidence), 6)
        self.assertEqual(c.priority, "high")
        self.assertTrue(c.context_complete)
        self.assertEqual(n["explicit_error_results"], 3)
        self.assertIsNone(render_judgment(c, decision(c)).likely_cause)

    def test_successful_repeats_are_not_errors(self):
        p, _ = prepare(trace([READS[0]] * 3)); c = p.candidates[0]
        self.assertEqual(c.priority, "medium")
        self.assertNotIn("explicit_errors", [f.fact_id for f in c.facts])

    def test_edit_and_user_message_break_retry_series(self):
        edit = ("Edit", {"file_path": "test.py"}, "success", False)
        for separator in (edit, "Повтори ещё раз"):
            p, _ = prepare(trace([FAIL, separator, FAIL, separator, FAIL]))
            self.assertFalse(any(c.kind == "repeated_tool_call" for c in p.candidates))

    def test_agent_retry_rationale_is_in_model_context(self):
        records = trace([FAIL] * 3)
        records[3]["message"]["content"].insert(0, {"type": "text", "text": "Сервис запускается; ожидаю изменения статуса и проверяю снова."})
        p, _ = prepare(records)
        c = next(c for c in p.candidates if c.kind == "repeated_tool_call")
        self.assertTrue(any("Сервис запускается" in e.text for e in c.evidence))

    def test_omitted_agent_rationale_disables_complete_context(self):
        records = trace([FAIL] * 3)
        records[3]["message"]["content"][:0] = [{"type": "text", "text": f"Пояснение {n}"} for n in range(21)]
        p, _ = prepare(records)
        self.assertFalse(p.candidates[0].context_complete)

    def test_malformed_metadata_does_not_crash_parser(self):
        records = trace([FAIL] * 3)
        records[1]["message"]["id"] = {"unexpected": "object"}
        records[2]["message"]["content"][0]["tool_use_id"] = ["not", "an", "id"]
        records.insert(3, {"type": [], "message": {}})
        records[4]["message"]["content"].insert(0, {"type": []})
        p, counts = prepare(records)
        self.assertGreater(counts["unknown_blocks"], 0)
        self.assertTrue(all(not c.context_complete for c in p.candidates))

    def test_new_task_context_is_not_the_first_prompt(self):
        p, _ = prepare(trace([FAIL, "Новая задача", FAIL]))
        self.assertEqual(p.candidates[-1].task_context, "Новая задача")
        self.assertIsNone(p.task)

    def test_different_outputs_or_secret_arguments_are_not_same_cycle(self):
        for actions in [[("Bash", {"command": "status"}, f"progress {i}", False) for i in range(3)],
                        [("Bash", {"command": f"api_key=secret{i}"}, "failed", True) for i in range(3)]]:
            p, _ = prepare(trace(actions))
            self.assertFalse(any(c.kind == "repeated_tool_call" for c in p.candidates))

    def test_concurrent_calls_and_forks_are_not_retries(self):
        records = trace([FAIL] * 3)
        records = [records[i] for i in [0, 1, 3, 5, 2, 4, 6]]
        for r in records: r.pop("uuid"); r.pop("parentUuid")
        p, _ = prepare(records)
        self.assertFalse(any(c.kind == "repeated_tool_call" for c in p.candidates))
        records = trace([FAIL] * 3); records[3]["parentUuid"] = records[0]["uuid"]
        p, _ = prepare(records)
        self.assertFalse(any(c.kind == "repeated_tool_call" for c in p.candidates))

    def test_unknown_record_breaks_series(self):
        records = trace([FAIL] * 3); records.insert(3, {"type": "future-tool-format"})
        p, _ = prepare(records)
        self.assertFalse(any(c.kind == "repeated_tool_call" for c in p.candidates))

    def test_duplicate_records_do_not_invent_attempts(self):
        records = trace([FAIL]); p, n = prepare(records + records[1:] + records[1:])
        self.assertEqual(n["tool_calls"], 1)
        self.assertEqual(p.candidates[0].kind, "explicit_tool_error")

    def test_long_and_damaged_logs_mark_context_incomplete(self):
        p, _ = prepare(trace([("Bash", {"command": "npm test"}, "x" * 5000, True)] * 3))
        self.assertFalse(p.candidates[0].context_complete)
        p, n = prepare_stream(io.BytesIO(encoded(trace([FAIL] * 3)) + b'{"broken"'))
        self.assertEqual(n["invalid_lines"], 1)
        self.assertFalse(p.candidates[0].context_complete)

    def test_many_reads_are_only_an_opportunity(self):
        p, _ = prepare(trace(READS)); c = p.candidates[0]
        self.assertEqual(c.kind, "read_many_files")
        self.assertEqual(c.alternatives, [])
        with self.assertRaisesRegex(GroundingError, "insufficient_basis"): render_judgment(c, decision(c, advice="narrow_read_scope"))

    def test_failed_search_not_an_alternative(self):
        p, _ = prepare(trace([("Bash", {"command": "rg TODO src"}, "command not found", True), *READS]))
        self.assertEqual(next(c for c in p.candidates if c.kind == "read_many_files").alternatives, [])

    def test_missing_args_or_output_not_a_cycle(self):
        for field in ("input", "content"):
            records = trace([FAIL] * 3)
            for r in records[1:]:
                b = r["message"]["content"][0]
                if (field == "input" and b["type"] == "tool_use") or (field == "content" and b["type"] == "tool_result"): b.pop(field)
            p, _ = prepare(records)
            self.assertFalse(any(c.kind == "repeated_tool_call" for c in p.candidates))

    def test_thinking_not_exported_and_missing_call_is_explicit(self):
        records = trace([FAIL]); records[1]["message"]["content"].insert(0, {"type": "thinking", "thinking": "PRIVATE REASONING"})
        p, _ = prepare(records); self.assertNotIn("PRIVATE REASONING", p.model_dump_json())
        p, _ = prepare([records[0], records[-1]])
        self.assertTrue(any("отсутствует" in s for s in p.candidates[0].limitations))

    def test_mixed_sessions_rejected(self):
        records = trace([FAIL]); records[-1]["sessionId"] = "other"
        with self.assertRaisesRegex(ValueError, "one session"): prepare(records)

    def test_zip_is_read_without_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.zip"
            with ZipFile(path, "w") as z: z.writestr("../unexpected.jsonl", encoded(trace([FAIL])))
            with open_log(path, "../unexpected.jsonl") as f: p, _ = prepare_stream(f)
            self.assertEqual(len(p.candidates), 1)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["logs.zip"])


class ContractTests(unittest.TestCase):
    def test_v1_missing_fact_evidence_and_duplicates_rejected(self):
        data = packet().model_dump(); data["schema_version"] = "1"
        with self.assertRaises(ValidationError): ReviewInput.model_validate(data)
        data = packet().candidates[0].model_dump(); data["facts"][0]["evidence_step_ids"] = ["missing"]
        with self.assertRaises(ValidationError): Candidate.model_validate(data)
        data = packet().model_dump(); data["candidates"].append(data["candidates"][0])
        with self.assertRaises(ValidationError): ReviewInput.model_validate(data)

    def test_secret_patterns(self):
        clean = redact('api_key="demo-secret" password=hunter2 Bearer example.token /Users/alice/project')
        for secret in ("demo-secret", "hunter2", "example.token", "alice"): self.assertNotIn(secret, clean)


if __name__ == "__main__": unittest.main()

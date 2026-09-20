import json
import random
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent_review.compression import compress_input
from agent_review.grounding import GroundingError, render_judgment
from agent_review.reviewer import MAX_REQUEST_BYTES, get_prompt, preview, review
from agent_review.schemas import (Citation, Evidence, Fact, ModelDecision,
                                  ObservedAlternative, ReviewInput)


def example():
    return ReviewInput.model_validate_json(
        (Path(__file__).parents[1] / "examples" / "packet.json").read_text())


def unpack_steps(payload):
    """Independent consumer of the documented text/text_ref wire format."""
    texts, result = {}, []
    for step in payload["candidate"]["evidence"]:
        text = step["text"] if "text" in step else texts[step["text_ref"]]
        texts[step["step_id"]] = text
        result.append((step["step_id"], step["kind"], text))
    return result


def cited_decision(candidate):
    return ModelDecision(candidate_id=candidate.candidate_id, assessment="uncertain",
        fact_ids=[f.fact_id for f in candidate.facts], advice="none", alternative_id=None,
        citations=[Citation(step_id=e.step_id, quote=e.text[:100]) for e in candidate.evidence])


class CompressionTests(unittest.TestCase):
    def test_repeated_error_keeps_each_attempt_and_quotes_still_validate(self):
        p = example(); c = p.candidates[0]
        original = p.model_dump_json()
        raw, stats = compress_input(p, c)
        payload = json.loads(raw)
        self.assertEqual(unpack_steps(payload), [(e.step_id, e.kind, e.text) for e in c.evidence])
        self.assertGreater(stats.reused_texts, 0)
        self.assertEqual(stats.evidence_steps, 6)
        self.assertEqual(p.model_dump_json(), original)
        self.assertEqual(stats.compressed_input_bytes, len(raw.encode("utf-8")))
        self.assertEqual(stats.saved_input_bytes, stats.original_input_bytes - stats.compressed_input_bytes)
        d = cited_decision(c)
        self.assertEqual(len(render_judgment(c, d).citations), 6)
        referenced_steps = {e["step_id"] for e in payload["candidate"]["evidence"] if "text_ref" in e}
        d.citations = [q for q in d.citations if q.step_id not in referenced_steps]
        with self.assertRaisesRegex(GroundingError, "missing_fact_evidence"):
            render_judgment(c, d)

    def test_all_context_facts_and_alternatives_survive(self):
        p = example(); p.task = "Old task"
        c = p.candidates[0]; c.task_context = "New task with exact constraints"
        c.limitations.append("Do not infer success from the result alone")
        c.alternatives = [ObservedAlternative(alternative_id="observed", tool_name="Bash",
                                              evidence_step_ids=["step-1", "step-2"])]
        payload = json.loads(compress_input(p, c)[0])
        self.assertEqual(payload["task"], c.task_context)
        self.assertEqual(payload["warnings"], p.warnings)
        for key in ("candidate_id", "kind", "facts", "alternatives", "context_complete", "limitations"):
            self.assertEqual(payload["candidate"][key], c.model_dump()[key])
        self.assertNotIn("Old task", json.dumps(payload))
        self.assertNotIn("source_id", payload)
        self.assertNotIn("priority", payload["candidate"])
        self.assertNotIn("task_context", payload["candidate"])
        self.assertTrue(all("source_line" not in step for step in payload["candidate"]["evidence"]))

    def test_random_texts_roundtrip_without_normalizing_whitespace_or_unicode(self):
        rng = random.Random(42)
        texts = ["", "x", "\n", "  error  ", "  error \n", "text_ref=step-0",
                 "Вывод\n  с отступами\tи кавычками: \"файл\" 😀" * 20]
        for _ in range(20):
            p = example(); c = p.candidates[0]
            c.evidence = [Evidence(step_id=f"step-{n}", kind=rng.choice(["tool_call", "tool_result", "assistant_text"]),
                          text=rng.choice(texts), source_line=n + 1) for n in range(30)]
            c.facts = [Fact(fact_id="has_steps", text="В логе есть эти шаги.",
                           evidence_step_ids=[e.step_id for e in c.evidence])]
            raw, stats = compress_input(p, c)
            self.assertEqual(unpack_steps(json.loads(raw)), [(e.step_id, e.kind, e.text) for e in c.evidence])
            self.assertLessEqual(stats.compressed_input_bytes, stats.original_input_bytes)

    def test_unique_success_changes_and_error_are_not_removed(self):
        p = example(); c = p.candidates[0]
        texts = ["Read before edit", "old value", "Edit new value", "success", "Run tests", "error: new failure"]
        for step, text in zip(c.evidence, texts): step.text = text
        raw, stats = compress_input(p, c)
        self.assertEqual([e[2] for e in unpack_steps(json.loads(raw))], texts)
        self.assertEqual(stats.reused_texts, 0)

    def test_existing_truncation_and_incomplete_context_are_not_hidden(self):
        p = example(); c = p.candidates[0]; c.context_complete = False
        c.evidence[0].text = "начало\n[TRUNCATED]\nконец"
        c.limitations.append("Часть текста отсутствует")
        payload = json.loads(compress_input(p, c)[0])
        self.assertFalse(payload["candidate"]["context_complete"])
        self.assertIn("[TRUNCATED]", unpack_steps(payload)[0][2])
        self.assertIn("Часть текста отсутствует", payload["candidate"]["limitations"])

    def test_budget_is_applied_after_compression(self):
        p = example(); c = p.candidates[0]
        for e in c.evidence: e.text = "Повторяющийся результат с сохранением всего текста. " * 100
        raw, stats = compress_input(p, c)
        self.assertGreater(stats.original_input_bytes, MAX_REQUEST_BYTES)
        self.assertLess(stats.compressed_input_bytes, MAX_REQUEST_BYTES)
        result = preview(p)
        self.assertEqual(len(result["requests"]), 1)
        self.assertEqual(result["requests"][0]["input"], raw)
        self.assertEqual(len(unpack_steps(json.loads(raw))), 6)

    def test_unique_oversized_evidence_is_skipped_without_cutting(self):
        p = example(); c = p.candidates[0]
        for n, e in enumerate(c.evidence): e.text = str(n) + "Уникальный результат сохранён целиком. " * 140
        raw, _ = compress_input(p, c)
        self.assertEqual(unpack_steps(json.loads(raw)), [(e.step_id, e.kind, e.text) for e in c.evidence])
        result = preview(p)
        self.assertEqual(result["requests"], [])
        self.assertEqual(result["skipped"][0]["reason"], "request_too_large")

    def test_preview_and_api_get_same_input_report_keeps_originals(self):
        p = example(); expected = preview(p); c = p.candidates[0]
        async def parse(**kwargs):
            self.assertEqual(kwargs["input"], expected["requests"][0]["input"])
            self.assertEqual(kwargs["instructions"], get_prompt())
            self.assertNotIn("compression", kwargs)
            return SimpleNamespace(status="completed", output_parsed=cited_decision(c), usage=None)
        report = review(p, client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
        self.assertEqual(report.status, "complete")
        self.assertEqual(report.findings[0].candidate, c)
        self.assertEqual(report.source_id, p.source_id)
        stats = expected["compression"][0].copy(); stats.pop("candidate_id")
        self.assertEqual(report.findings[0].compression.model_dump(), stats)


if __name__ == "__main__":
    unittest.main()

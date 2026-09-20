"""The ML part: build bounded requests, call the model, validate evidence."""

import hashlib
import json
import os
from importlib.resources import files

from openai import OpenAI

from .redaction import clean_packet, redact
from .schemas import Candidate, Judgment, ReviewInput, ReviewReport, ReviewedCandidate

DEFAULT_MODEL = "gpt-4.1-mini-2025-04-14"
# Conservative byte cap for prompt + JSON + output schema, not a token estimate.
MAX_REQUEST_BYTES = 48_000
MAX_CALLS = 8


def get_prompt() -> str:
    return files("agent_review").joinpath("prompt.md").read_text(encoding="utf-8")


def make_request(packet: ReviewInput, candidate: Candidate, model: str) -> dict:
    payload = {
        "source_id": packet.source_id,
        "task": packet.task,
        "warnings": packet.warnings,
        "candidate": candidate.model_dump(),
    }
    return {
        "model": model,
        "instructions": get_prompt(),
        "input": json.dumps(payload, ensure_ascii=False),
        "text_format": Judgment,
        "max_output_tokens": 2000,
        "store": False,
    }


def request_bytes(request: dict) -> int:
    return len((request["instructions"] + request["input"] +
                json.dumps(Judgment.model_json_schema(), ensure_ascii=False)).encode("utf-8"))


def validate_judgment(candidate: Candidate, judgment: Judgment) -> None:
    if judgment.candidate_id != candidate.candidate_id:
        raise ValueError("unknown_candidate_id")
    allowed = {s.step_id for s in candidate.evidence}
    refs = judgment.evidence_step_ids
    if not refs or len(refs) != len(set(refs)) or not set(refs) <= allowed:
        raise ValueError("invalid_evidence_step_ids")
    if not judgment.explanation.strip():
        raise ValueError("empty_explanation")
    if judgment.assessment == "inefficient":
        if not all(t and t.strip() for t in
                   [judgment.action, judgment.verification, judgment.rule_text]):
            raise ValueError("missing_actionable_recommendation")
    if len(judgment.model_dump_json()) > 16_000:
        raise ValueError("response_too_large")


def preview(packet: ReviewInput, *, model: str | None = None, max_calls: int = MAX_CALLS) -> dict:
    """Exactly the bounded, masked requests, without creating an API client."""
    if not 1 <= max_calls <= MAX_CALLS:
        raise ValueError(f"max_calls must be between 1 and {MAX_CALLS}")
    packet = clean_packet(packet)
    model = model or os.getenv("LLM_MODEL") or DEFAULT_MODEL
    requests, skipped = [], []
    for candidate in packet.candidates:
        request = make_request(packet, candidate, model)
        reason = None
        if request_bytes(request) > MAX_REQUEST_BYTES:
            reason = "request_too_large"
        elif len(requests) >= max_calls:
            reason = "call_budget_exceeded"
        if reason:
            skipped.append({"candidate_id": candidate.candidate_id, "reason": reason})
            continue
        request["text_format"] = Judgment.model_json_schema()
        requests.append(request)
    return {"mode": "preview_only_no_model_called", "requests": requests, "skipped": skipped}


def review(packet: ReviewInput, *, model: str | None = None,
           max_calls: int = MAX_CALLS, client=None) -> ReviewReport:
    """Called by the backend worker. Synchronous; do not block its async loop."""
    if not 1 <= max_calls <= MAX_CALLS:
        raise ValueError(f"max_calls must be between 1 and {MAX_CALLS}")
    packet = clean_packet(packet)
    model = model or os.getenv("LLM_MODEL") or DEFAULT_MODEL
    prompt_version = hashlib.sha256(get_prompt().encode()).hexdigest()[:12]
    findings, calls, reviewed = [], 0, 0
    usage: dict[str, int] = {}
    owns_client = False
    try:
        for candidate in packet.candidates:
            item = ReviewedCandidate(candidate=candidate)
            findings.append(item)
            request = make_request(packet, candidate, model)
            if request_bytes(request) > MAX_REQUEST_BYTES:
                item.error = "request_too_large"
                continue
            if calls >= max_calls:
                item.error = "call_budget_exceeded"
                continue
            if client is None:
                if not os.getenv("OPENAI_API_KEY"):
                    raise ValueError("Set OPENAI_API_KEY on the server; never paste it into a log")
                client = OpenAI(timeout=30.0, max_retries=0)
                owns_client = True
            calls += 1
            try:
                response = client.responses.parse(**request)
                if response.usage:
                    for key in ("input_tokens", "output_tokens", "total_tokens"):
                        value = getattr(response.usage, key, None)
                        if isinstance(value, int):
                            usage[key] = usage.get(key, 0) + value
                if response.status != "completed" or response.output_parsed is None:
                    item.error = "incomplete_or_refused"
                    continue
                judgment = Judgment.model_validate(response.output_parsed)
                validate_judgment(candidate, judgment)
                for field in ("explanation", "likely_cause", "action", "verification", "rule_text"):
                    value = getattr(judgment, field)
                    if value is not None:
                        setattr(judgment, field, redact(value))
                judgment.limitations = [redact(t) for t in judgment.limitations]
                item.judgment = judgment
                reviewed += 1
            except Exception as exc:
                # Provider exceptions may echo input; retain only the class name.
                item.error = f"model_or_validation_error:{type(exc).__name__}"
    finally:
        if owns_client:
            client.close()
    status = "no_candidates" if not findings else (
        "complete" if reviewed == len(findings) else "partial")
    return ReviewReport(
        source_id=packet.source_id, status=status, model=model,
        prompt_version=prompt_version, candidates_total=len(findings),
        candidates_reviewed=reviewed, api_calls=calls, analysis_usage=usage,
        findings=findings, warnings=packet.warnings,
    )

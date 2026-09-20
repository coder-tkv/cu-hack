"""Bounded model selection followed by deterministic, evidence-based reporting."""

import asyncio
import hashlib
import json
import math
import os
from importlib.resources import files
from time import monotonic

from openai import (AsyncOpenAI, AuthenticationError, PermissionDeniedError,
                    RateLimitError, APIConnectionError)

from .compression import compress_input
from .grounding import GroundingError, render_judgment
from .redaction import clean_packet
from .schemas import (Candidate, CompressionStats, ModelDecision, ReviewInput,
                      ReviewReport, ReviewedCandidate)

DEFAULT_MODEL = "gpt-4.1-mini-2025-04-14"
MAX_REQUEST_BYTES = 48_000
MAX_CALLS = 8
MAX_ANALYSIS_SECONDS = 120.0
REQUEST_TIMEOUT_SECONDS = 30.0


def get_prompt() -> str:
    return files("agent_review").joinpath("prompt.md").read_text(encoding="utf-8")


def make_request(packet: ReviewInput, candidate: Candidate, model: str,
                 prompt: str | None = None) -> tuple[dict, CompressionStats]:
    payload, stats = compress_input(packet, candidate)
    return {
        "model": model,
        "instructions": prompt if prompt is not None else get_prompt(),
        "input": payload,
        "text_format": ModelDecision,
        "max_output_tokens": 4000,
        "store": False,
    }, stats


def request_bytes(request: dict) -> int:
    return len((request["instructions"] + request["input"] +
                json.dumps(ModelDecision.model_json_schema(), ensure_ascii=False)).encode("utf-8"))


def ordered_candidates(packet: ReviewInput) -> list[Candidate]:
    # Stable order: confirmed repeated outcomes before optional simplifications.
    priority = {"high": 0, "medium": 1, "low": 2}
    return sorted(packet.candidates, key=lambda candidate: priority[candidate.priority])


def checked_packet(packet: ReviewInput, max_calls: int) -> ReviewInput:
    if not 1 <= max_calls <= MAX_CALLS:
        raise ValueError(f"max_calls must be between 1 and {MAX_CALLS}")
    # Also catches invalid mutations made after Pydantic construction.
    return clean_packet(ReviewInput.model_validate(packet.model_dump()))


def preview(packet: ReviewInput, *, model: str | None = None, max_calls: int = MAX_CALLS) -> dict:
    """The bounded, masked requests. No API client, requests or paid tokens."""
    packet = checked_packet(packet, max_calls)
    model = model or os.getenv("LLM_MODEL") or DEFAULT_MODEL
    prompt = get_prompt()
    requests, skipped, compression = [], [], []
    for candidate in ordered_candidates(packet):
        request, stats = make_request(packet, candidate, model, prompt)
        compression.append({"candidate_id": candidate.candidate_id, **stats.model_dump()})
        reason = None
        if request_bytes(request) > MAX_REQUEST_BYTES:
            reason = "request_too_large"
        elif len(requests) >= max_calls:
            reason = "call_budget_exceeded"
        if reason:
            skipped.append({"candidate_id": candidate.candidate_id, "reason": reason})
            continue
        request["text_format"] = ModelDecision.model_json_schema()
        requests.append(request)
    return {"mode": "preview_only_no_model_called", "requests": requests,
            "skipped": skipped, "compression": compression}


async def review_async(packet: ReviewInput, *, model: str | None = None,
                       max_calls: int = MAX_CALLS, client=None,
                       deadline_seconds: float = MAX_ANALYSIS_SECONDS) -> ReviewReport:
    """Native async interface for backend workers and API handlers."""
    if not math.isfinite(deadline_seconds) or not 0 < deadline_seconds <= MAX_ANALYSIS_SECONDS:
        raise ValueError(f"deadline_seconds must be positive and <= {MAX_ANALYSIS_SECONDS}")
    deadline = monotonic() + deadline_seconds
    packet = checked_packet(packet, max_calls)
    model = model or os.getenv("LLM_MODEL") or DEFAULT_MODEL
    prompt = get_prompt()
    prompt_version = hashlib.sha256(prompt.encode()).hexdigest()[:12]
    findings, calls, reviewed = [], 0, 0
    usage: dict[str, int] = {}
    owns_client = False
    provider_failure = None
    try:
        for candidate in ordered_candidates(packet):
            item = ReviewedCandidate(candidate=candidate)
            findings.append(item)
            if provider_failure:
                item.error = provider_failure
                continue
            if monotonic() >= deadline:
                item.error = "analysis_deadline_exceeded"
                continue
            request, item.compression = make_request(packet, candidate, model, prompt)
            if request_bytes(request) > MAX_REQUEST_BYTES:
                item.error = "request_too_large"
                continue
            if calls >= max_calls:
                item.error = "call_budget_exceeded"
                continue
            if client is None:
                if not os.getenv("OPENAI_API_KEY"):
                    raise ValueError("Set OPENAI_API_KEY on the server; never paste it into a log")
                client = AsyncOpenAI(timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0)
                owns_client = True
            remaining = deadline - monotonic()
            if remaining <= 0:
                item.error = "analysis_deadline_exceeded"
                continue
            timeout = min(REQUEST_TIMEOUT_SECONDS, remaining)
            api = client.with_options(max_retries=0) if isinstance(client, AsyncOpenAI) else client
            calls += 1
            try:
                # wait_for bounds total elapsed request time, unlike a read timeout alone.
                response = await asyncio.wait_for(
                    api.responses.parse(**request, timeout=timeout), timeout=timeout)
                if response.usage:
                    for key in ("input_tokens", "output_tokens", "total_tokens"):
                        value = getattr(response.usage, key, None)
                        if isinstance(value, int):
                            usage[key] = usage.get(key, 0) + value
                if response.status != "completed" or response.output_parsed is None:
                    item.error = "incomplete_or_refused"
                    continue
                decision = ModelDecision.model_validate(response.output_parsed)
                item.judgment = render_judgment(candidate, decision)
                reviewed += 1
            except TimeoutError:
                item.error = "analysis_deadline_exceeded" if monotonic() >= deadline else "request_timeout"
            except GroundingError as exc:
                item.error = f"grounding:{exc}"
            except (AuthenticationError, PermissionDeniedError, RateLimitError, APIConnectionError) as exc:
                provider_failure = f"provider_unavailable:{type(exc).__name__}"
                item.error = provider_failure
            except Exception as exc:
                # Never print response bodies, log data or authentication headers.
                item.error = f"model_or_validation_error:{type(exc).__name__}"
    finally:
        if owns_client:
            try:
                await asyncio.wait_for(client.close(), timeout=1.0)
            except Exception:
                pass
    status = "no_candidates" if not findings else (
        "complete" if reviewed == len(findings) else "partial")
    return ReviewReport(
        source_id=packet.source_id, status=status, model=model,
        prompt_version=prompt_version, candidates_total=len(findings),
        candidates_reviewed=reviewed, api_calls=calls, analysis_usage=usage,
        findings=findings, warnings=packet.warnings,
    )


def review(packet: ReviewInput, **kwargs) -> ReviewReport:
    """Synchronous CLI/worker wrapper. Async backends must await review_async."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(review_async(packet, **kwargs))
    raise RuntimeError("Inside an async handler use: await review_async(packet)")

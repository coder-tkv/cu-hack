"""Usage extraction for the original Claude Code agent.

This module reads usage independently from parsing Steps. A Claude response can
have several content blocks or streaming updates with the same request_id; its
usage must be counted once, never once per block or Step.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from schemas import UsageRecord


class _UsageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UsageExtraction(_UsageModel):
    records: list[UsageRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class UsageSummary(_UsageModel):
    request_count: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cache_creation_input_tokens: int | None = Field(default=None, ge=0)
    cache_read_input_tokens: int | None = Field(default=None, ge=0)
    limitations: list[str] = Field(default_factory=list)


def extract_usage_records(lines: Iterable[str]) -> UsageExtraction:
    """Read original-agent usage from raw JSONL lines and deduplicate request IDs.

    Invalid or unrelated lines are ignored here: the parser owns their warnings.
    A record without a request ID cannot be safely deduplicated, so it is not
    included and is reported as a limitation instead of being guessed.
    """
    records: dict[str, UsageRecord] = {}
    warnings: list[str] = []

    for source_line, raw_line in enumerate(lines, start=1):
        try:
            event = json.loads(raw_line)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            continue
        if not isinstance(event, dict):
            continue

        message = event.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue

        request_id = (
            _string(event.get("requestId"))
            or _string(event.get("request_id"))
            or _string(message.get("requestId"))
            or _string(message.get("request_id"))
        )
        if request_id is None:
            warnings.append(f"line_{source_line}: usage_without_request_id")
            continue

        candidate = UsageRecord(
            request_id=request_id,
            message_id=_string(message.get("id")),
            model=_string(message.get("model")),
            input_tokens=_non_negative_int(usage.get("input_tokens")),
            output_tokens=_non_negative_int(usage.get("output_tokens")),
            cache_creation_input_tokens=_non_negative_int(usage.get("cache_creation_input_tokens")),
            cache_read_input_tokens=_non_negative_int(usage.get("cache_read_input_tokens")),
            source_lines=[source_line],
            step_ids=_step_ids_for_event(event, source_line),
            is_final=_is_final(message),
        )

        existing = records.get(request_id)
        if existing is None:
            records[request_id] = candidate
        else:
            records[request_id] = _merge_duplicate(existing, candidate)

    return UsageExtraction(records=list(records.values()), warnings=warnings)


def summarize_usage(records: Iterable[UsageRecord]) -> UsageSummary:
    """Return token totals, deduplicating defensively by request_id once again."""
    unique: dict[str, UsageRecord] = {}
    for record in records:
        current = unique.get(record.request_id)
        unique[record.request_id] = (
            record if current is None else _merge_duplicate(current, record)
        )

    all_records = list(unique.values())
    totals = {
        "input_tokens": _sum_known(all_records, "input_tokens"),
        "output_tokens": _sum_known(all_records, "output_tokens"),
        "cache_creation_input_tokens": _sum_known(all_records, "cache_creation_input_tokens"),
        "cache_read_input_tokens": _sum_known(all_records, "cache_read_input_tokens"),
    }
    limitations: list[str] = []
    for field, value in totals.items():
        known_count = sum(
            getattr(record, field) is not None for record in all_records
        )
        if value is None:
            limitations.append(f"{field} отсутствуют во всех записях usage")
        elif known_count < len(all_records):
            limitations.append(
                f"{field}: сумма по {known_count} из {len(all_records)} запросов; "
                "итог неполный"
            )
    limitations.extend(
        warning
        for record in all_records
        for warning in record.warnings
        if warning not in limitations
    )
    if not all_records:
        limitations.append("в логе не найден usage исходного агента")

    return UsageSummary(request_count=len(all_records), limitations=limitations, **totals)


def _merge_duplicate(current: UsageRecord, candidate: UsageRecord) -> UsageRecord:
    """Keep one request and preserve values while reporting conflicts."""
    merged = current.model_copy(deep=True)
    conflict_warnings: list[str] = []
    for field in (
        "message_id",
        "model",
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "is_final",
    ):
        current_value = getattr(current, field)
        value = getattr(candidate, field)
        if current_value is not None and value is not None and current_value != value:
            conflict_warnings.append(
                f"request_id={current.request_id}: conflicting {field}: "
                f"{current_value} != {value}"
            )
        if value is not None:
            setattr(merged, field, value)
    merged.source_lines = _unique(current.source_lines + candidate.source_lines)
    merged.step_ids = _unique(current.step_ids + candidate.step_ids)
    merged.warnings = _unique(current.warnings + candidate.warnings + conflict_warnings)
    return merged


def _step_ids_for_event(event: dict[str, Any], source_line: int) -> list[str]:
    session_id = _string(event.get("sessionId"))
    if session_id is None:
        return []
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    block_count = len(content) if isinstance(content, list) and content else 1
    return [f"{session_id}:line_{source_line}:block_{index}" for index in range(block_count)]


def _sum_known(records: list[UsageRecord], field: str) -> int | None:
    values = [getattr(record, field) for record in records]
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _is_final(message: dict[str, Any]) -> bool | None:
    stop_reason = message.get("stop_reason")
    return stop_reason == "end_turn" if isinstance(stop_reason, str) else None


def _non_negative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))

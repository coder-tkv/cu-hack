"""Usage extraction for the original Claude Code agent.

Usage can be extracted separately or collected during the shared parser pass. A Claude response can
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


class UsageCollector:
    """Accumulate already decoded events; the API never parses a file twice."""

    def __init__(self):
        self.records: dict[tuple[str, str], UsageRecord] = {}
        self.warnings: list[str] = []

    def add_event(self, event: dict, source_line: int) -> None:
        message = event.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
            return
        usage = message["usage"]
        request_id = usage_id(event)
        if request_id is None:
            if len(self.warnings) < 200:
                self.warnings.append(f"line_{source_line}: usage_without_request_or_message_id")
            return
        cache = usage.get("cache_creation")
        cache = {k: v for k, v in cache.items() if _non_negative_int(v) is not None} if isinstance(cache, dict) else None
        candidate = UsageRecord(
            request_id=request_id,
            session_id=_string(event.get("sessionId")) or "unknown",
            message_id=_string(message.get("id")),
            model=_string(message.get("model")),
            input_tokens=_non_negative_int(usage.get("input_tokens")),
            output_tokens=_non_negative_int(usage.get("output_tokens")),
            cache_creation_input_tokens=_non_negative_int(usage.get("cache_creation_input_tokens")),
            cache_read_input_tokens=_non_negative_int(usage.get("cache_read_input_tokens")),
            cache_creation=cache,
            source_lines=[source_line], step_ids=_step_ids_for_event(event, source_line),
            is_final=_is_final(message),
        )
        key = candidate.session_id, request_id
        existing = self.records.get(key)
        self.records[key] = candidate if existing is None else _merge_duplicate(existing, candidate)

    def finish(self) -> UsageExtraction:
        return UsageExtraction(records=list(self.records.values()), warnings=self.warnings)


def usage_id(event: dict) -> str | None:
    message = event.get("message")
    message = message if isinstance(message, dict) else {}
    return (_string(event.get("requestId")) or _string(event.get("request_id"))
            or _string(message.get("requestId")) or _string(message.get("request_id"))
            or _string(message.get("id")))


def extract_usage_records(lines: Iterable[str]) -> UsageExtraction:
    """Convenience interface for usage-only callers; request ID or message ID is required."""
    collector = UsageCollector()
    for source_line, raw_line in enumerate(lines, start=1):
        try:
            event = json.loads(raw_line)
        except (ValueError, TypeError, UnicodeDecodeError):
            continue
        if isinstance(event, dict):
            collector.add_event(event, source_line)
    return collector.finish()


def summarize_usage(records: Iterable[UsageRecord]) -> UsageSummary:
    """Return token totals, deduplicating defensively by request_id once again."""
    unique: dict[tuple[str, str], UsageRecord] = {}
    for record in records:
        key = record.session_id, record.request_id
        current = unique.get(key)
        unique[key] = (
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
        "cache_creation",
        "is_final",
    ):
        current_value = getattr(current, field)
        value = getattr(candidate, field)
        if current_value is not None and value is not None and current_value != value:
            conflict_warnings.append(
                f"request_id={current.request_id}: conflicting {field}: "
                f"{current_value} != {value}"
            )
        if value is not None and not (current.is_final is True and candidate.is_final is not True):
            setattr(merged, field, value)
        elif current_value is None:
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
    return bool(stop_reason) if isinstance(stop_reason, str) else None


def _non_negative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))

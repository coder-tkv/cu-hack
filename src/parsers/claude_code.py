"""Fault-tolerant streaming parser for Claude Code JSONL transcripts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from schemas import Actor, SourceRef, Step, StepKind, ToolCall, ToolCallStatus


_TEXT_BLOCK_TYPES = {"text", "thinking"}
_SYSTEM_TYPES = {"system", "mode", "permission-mode", "file-history-snapshot", "attachment", "progress", "summary", "ai-title"}


def parse_claude_code_log(
    source: str | Path | TextIO,
    *,
    session_id: str | None = None,
) -> Iterator[Step]:
    """Yield normalized steps without aborting on a bad line or block.

    ``source`` is read line by line. The function deliberately returns an
    iterator so large transcripts are never loaded into memory as a whole.
    """
    if hasattr(source, "read"):
        yield from parse_claude_code_lines(source, session_id=session_id)
        return

    with Path(source).open("r", encoding="utf-8", errors="replace") as handle:
        yield from parse_claude_code_lines(handle, session_id=session_id)


def parse_claude_code_lines(
    lines: Iterable[str],
    *,
    session_id: str | None = None,
) -> Iterator[Step]:
    """Parse an iterable of JSONL lines, preserving line and block positions."""
    ordinal = 0
    for source_line, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            yield _unknown_step(
                session_id=session_id or "unknown",
                ordinal=ordinal,
                source_line=source_line,
                warning="empty_line",
            )
            ordinal += 1
            continue

        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            yield _unknown_step(
                session_id=session_id or "unknown",
                ordinal=ordinal,
                source_line=source_line,
                warning="invalid_json",
            )
            ordinal += 1
            continue

        if not isinstance(event, dict):
            yield _unknown_step(
                session_id=session_id or "unknown",
                ordinal=ordinal,
                source_line=source_line,
                warning="event_is_not_object",
            )
            ordinal += 1
            continue

        event_session_id = _string(event.get("sessionId")) or session_id or "unknown"
        blocks = _content_blocks(event)
        if not blocks:
            blocks = [(None, event)]

        for block_index, block in enumerate(blocks):
            step = _step_from_block(
                event,
                block,
                session_id=event_session_id,
                ordinal=ordinal,
                source_line=source_line,
                block_index=block_index,
            )
            yield step
            ordinal += 1


def _content_blocks(event: dict[str, Any]) -> list[tuple[str | None, Any]]:
    message = event.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, list):
        return [
            (_string(block.get("type")) if isinstance(block, dict) else None, block)
            for block in content
        ] or [(None, content)]
    if content is not None:
        return [("text", content)]
    return []


def _step_from_block(
    event: dict[str, Any],
    block_info: tuple[str | None, Any],
    *,
    session_id: str,
    ordinal: int,
    source_line: int,
    block_index: int,
) -> Step:
    block_type, block = block_info
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    event_type = _string(event.get("type"))
    event_id = _string(event.get("uuid"))
    message_id = _string(message.get("id"))
    source = SourceRef(
        source_line=source_line,
        block_index=block_index,
        source_event_id=event_id,
        source_message_id=message_id,
    )

    warnings: list[str] = []
    malformed_block_type = isinstance(block, dict) and not isinstance(block.get("type"), str)
    kind, actor = _classify(event_type, block_type, block, message)
    if malformed_block_type:
        kind, actor = StepKind.UNKNOWN, Actor.UNKNOWN
        warnings.append("invalid_content_block_type")
    tool_call_id = None
    tool_name = None
    arguments = None
    text = None
    is_error: bool | None = None

    if isinstance(block, dict):
        if block_type == "tool_use":
            tool_call_id = _string(block.get("id"))
            tool_name = _string(block.get("name"))
            arguments = block.get("input")
        elif block_type == "tool_result":
            tool_call_id = _string(block.get("tool_use_id"))
            is_error = _tool_result_error(block)
            text = _content_text(block.get("content"))
        elif block_type == "text":
            text = _string(block.get("text"))
        elif block_type == "thinking":
            text = _string(block.get("thinking"))
        elif block_type is not None:
            warnings.append("unknown_content_block")
            text = _content_text(block)
    elif isinstance(block, str):
        text = block
    elif block is not None:
        warnings.append("malformed_content_block")

    # A user envelope containing tool_result is a tool event, never a human message.
    if block_type == "tool_result":
        actor = Actor.TOOL
        kind = StepKind.TOOL_RESULT

    if kind == StepKind.UNKNOWN:
        warnings.append("unknown_event_type" if event_type not in _SYSTEM_TYPES else "unknown_content_block")

    usage_ref = (
        _string(event.get("requestId"))
        or _string(event.get("request_id"))
        or _string(message.get("requestId"))
        or _string(message.get("request_id"))
    )
    timestamp = _timestamp(event.get("timestamp"))
    step_id = f"{session_id}:line_{source_line}:block_{block_index}"

    return Step(
        step_id=step_id,
        session_id=session_id,
        ordinal=ordinal,
        source=source,
        parent_event_id=_string(event.get("parentUuid")),
        branch_id="main",
        timestamp=timestamp,
        kind=kind,
        actor=actor,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        text=text,
        is_error=is_error,
        usage_ref=usage_ref,
        warnings=warnings,
    )


def link_tool_calls(steps: Iterable[Step]) -> list[ToolCall]:
    """Match tool calls and results by ID, never by neighboring steps.

    Calls without a result are returned with ``unfinished=True`` and
    ``status=unknown``. Results whose call is absent are not attached to a
    made-up call; the original result Step remains available to callers.
    """
    steps = list(steps)
    calls: dict[str, ToolCall] = {}
    for step in steps:
        if step.kind == StepKind.TOOL_CALL and step.tool_call_id:
            calls.setdefault(
                step.tool_call_id,
                ToolCall(
                    tool_call_id=step.tool_call_id,
                    call_step_id=step.step_id,
                    tool_name=step.tool_name,
                    arguments=step.arguments,
                    started_at=step.timestamp,
                ),
            )

    for step in steps:
        if step.kind != StepKind.TOOL_RESULT or not step.tool_call_id:
            continue
        call = calls.get(step.tool_call_id)
        if call is None:
            continue
        call.result_step_ids.append(step.step_id)
        call.finished_at = step.timestamp or call.finished_at
        call.unfinished = False
        if step.is_error is True:
            call.status = ToolCallStatus.ERROR
        elif call.status != ToolCallStatus.ERROR and step.is_error is False:
            call.status = ToolCallStatus.SUCCESS

    return list(calls.values())


def _classify(event_type: str | None, block_type: str | None, block: Any, message: dict[str, Any]) -> tuple[StepKind, Actor]:
    if block_type == "tool_use":
        return StepKind.TOOL_CALL, Actor.ASSISTANT
    if block_type == "tool_result":
        return StepKind.TOOL_RESULT, Actor.TOOL
    if block_type in _TEXT_BLOCK_TYPES:
        if event_type == "assistant":
            return StepKind.ASSISTANT_TEXT, Actor.ASSISTANT
        if event_type == "user":
            return StepKind.HUMAN_MESSAGE, Actor.HUMAN
        return StepKind.UNKNOWN, Actor.UNKNOWN
    if event_type == "user":
        return StepKind.HUMAN_MESSAGE, Actor.HUMAN
    if event_type == "assistant":
        return StepKind.ASSISTANT_TEXT, Actor.ASSISTANT
    if event_type in _SYSTEM_TYPES:
        return StepKind.SYSTEM_EVENT, Actor.SYSTEM
    return StepKind.UNKNOWN, Actor.UNKNOWN


def _unknown_step(*, session_id: str, ordinal: int, source_line: int, warning: str) -> Step:
    return Step(
        step_id=f"{session_id}:line_{source_line}:block_0",
        session_id=session_id,
        ordinal=ordinal,
        source=SourceRef(source_line=source_line, block_index=0),
        kind=StepKind.UNKNOWN,
        actor=Actor.UNKNOWN,
        warnings=[warning],
    )


def _content_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_content_text(item) for item in value]
        text = "\n".join(part for part in parts if part)
        return text or None
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        return json.dumps(value, ensure_ascii=False, default=str)
    return None


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _tool_result_error(block: dict[str, Any]) -> bool | None:
    explicit_error = _bool_or_none(block.get("is_error"))
    exit_code = block.get("exit_code", block.get("exitCode"))
    if isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0:
        return True
    return explicit_error


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

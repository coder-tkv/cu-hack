"""Public typed interface to the shared Claude Code parser.

The input is read once, line by line. Normalized steps are retained until usage
updates have been combined. JSON decoding and classification live in analysis.parser.
"""

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TextIO

from analysis.parser import Parser
from reports.builder import to_steps
from schemas import Actor, SourceRef, Step, StepKind, ToolCall, ToolCallStatus


def parse_claude_code_log(source: str | Path | TextIO, *, session_id: str | None = None) -> Iterator[Step]:
    if hasattr(source, "read"):
        yield from parse_claude_code_lines(source, session_id=session_id)
    else:
        with Path(source).open(encoding="utf-8", errors="replace") as handle:
            yield from parse_claude_code_lines(handle, session_id=session_id)


def parse_claude_code_lines(lines: Iterable[str], *, session_id: str | None = None) -> Iterator[Step]:
    parser = Parser()
    order: list[int | Step] = []
    for line_no, line in enumerate(lines, 1):
        before, bad = len(parser.steps), parser.stats["badJson"]
        parser.add_line(line_no, line)
        if parser.stats["badJson"] > bad:
            order.append(Step(step_id="pending", session_id=session_id or "unknown", ordinal=0,
                source=SourceRef(source_line=line_no), kind=StepKind.unknown, actor=Actor.unknown,
                warnings=["invalid_json"]))
        else:
            order.extend(range(before, len(parser.steps)))
    normalized = to_steps(parser.finish(), session_id or "unknown")
    for ordinal, entry in enumerate(order):
        step = entry if isinstance(entry, Step) else normalized[entry]
        source_session = None if isinstance(entry, Step) else parser.steps[entry].get("sessionId")
        step.session_id = session_id or source_session or "unknown"
        step.ordinal = ordinal
        step.step_id = f"{step.session_id}:line_{step.source.source_line}:block_{step.source.block_index}"
        yield step


def link_tool_calls(steps: Iterable[Step]) -> list[ToolCall]:
    """Link only unambiguous prior calls in the same session and branch."""
    steps = list(steps)
    groups: dict[tuple[str, str, str], list[Step]] = {}
    results_by_key: dict[tuple[str, str, str], list[Step]] = {}
    for step in steps:
        if step.kind == StepKind.tool_result and step.tool_call_id:
            results_by_key.setdefault((step.session_id, step.branch_id, step.tool_call_id), []).append(step)
        if step.kind == StepKind.tool_call and step.tool_call_id:
            groups.setdefault((step.session_id, step.branch_id, step.tool_call_id), []).append(step)
    calls = []
    for key, group in groups.items():
        for step in group:
            results = [s for s in results_by_key.get(key, []) if s.ordinal > step.ordinal] if len(group) == 1 else []
            status = ToolCallStatus.unknown
            if any(s.is_error is True for s in results):
                status = ToolCallStatus.error
            elif results and all(s.is_error is False for s in results):
                status = ToolCallStatus.success
            calls.append(ToolCall(tool_call_id=step.tool_call_id, session_id=step.session_id,
                tool_name=step.tool_name, arguments=step.arguments, call_step_id=step.step_id,
                result_step_ids=[s.step_id for s in results], status=status,
                started_at=step.timestamp, finished_at=results[-1].timestamp if results else None,
                unfinished=not results))
    return calls

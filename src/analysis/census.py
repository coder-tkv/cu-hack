"""Пересчёт того, что вообще есть в логе.

Один источник правды для KPI и для покрытия направлений: если знаменатель
считать в двух местах по-разному, отчёт начнёт противоречить сам себе.

Статус вызова: success | error | unknown. Вызов без результата — это unknown,
а не успех и не ошибка (иначе доля ошибок врёт).
"""

from __future__ import annotations

from .detectors.util import MUTATING_TOOLS


def census(steps: list[dict]) -> dict:
    tool_calls = 0
    calls_error = 0
    calls_success = 0
    calls_unknown = 0
    file_edits = 0
    human_messages = 0
    interruptions = 0
    steps_with_usage = 0
    steps_with_time = 0
    turns = 0

    results_by_call: dict[int, dict] = {}
    for s in steps:
        if s.get("kind") == "tool_result" and s.get("resultOf"):
            results_by_call[s["resultOf"]] = s

    for s in steps:
        if s.get("ts") is not None:
            steps_with_time += 1
        if isinstance(s.get("usage"), dict):
            steps_with_usage += 1
        kind = s.get("kind")
        if kind == "tool_call":
            tool_calls += 1
            if s.get("tool") in MUTATING_TOOLS:
                file_edits += 1
            r = results_by_call.get(s["id"])
            if r is None or r.get("isError") is None:
                calls_unknown += 1
            elif r.get("isError"):
                calls_error += 1
            else:
                calls_success += 1
        elif kind == "human" and not s.get("synthetic"):
            human_messages += 1
            turns += 1
        if s.get("interrupted"):
            interruptions += 1

    known = calls_success + calls_error
    return {
        "steps": len(steps),
        "toolCalls": tool_calls,
        "callsSuccess": calls_success,
        "callsError": calls_error,
        "callsWithKnownStatus": known,
        "unknownStatusCount": calls_unknown,
        "errorRate": round(calls_error / known, 3) if known else None,  # None != 0
        "fileEdits": file_edits,
        "humanMessages": human_messages,
        "interruptions": interruptions,
        "stepsWithUsage": steps_with_usage,
        "stepsWithTime": steps_with_time,
        "turns": max(1, turns) if steps else 0,
    }

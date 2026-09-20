"""KPI сессии: только то, что можно посчитать кодом.

Отсутствие поля с токенами означает «данных нет», а не «потрачено 0»:
поэтому cost = None, если ни одной известной модели в логе не встретилось.
"""

from __future__ import annotations

from .parser import session_timing
from .pricing import step_cost


def compute_kpi(steps: list[dict]) -> dict:
    tin = tout = cread = cwrite = 0
    cost = 0.0
    cost_known = False
    failures = human_messages = interruptions = tool_calls = 0
    unknown_models: set[str] = set()

    for s in steps:
        u = s.get("usage")
        if isinstance(u, dict):
            tin += u.get("in", 0)
            tout += u.get("out", 0)
            cread += u.get("cacheRead", 0)
            cwrite += u.get("cacheWrite", 0)
            c = step_cost(s)
            if c is None:
                if isinstance(s.get("model"), str):
                    unknown_models.add(s["model"])
            else:
                cost += c
                cost_known = True
        if s.get("kind") == "tool_call":
            tool_calls += 1
        if s.get("kind") == "tool_result" and s.get("isError"):
            failures += 1
        if s.get("kind") == "human" and not s.get("synthetic"):
            human_messages += 1
        if s.get("interrupted"):
            interruptions += 1

    timing = session_timing(steps)
    return {
        "tokensIn": tin,
        "tokensOut": tout,
        "cacheRead": cread,
        "cacheWrite": cwrite,
        "cost": round(cost, 4) if cost_known else None,
        "costPartial": bool(unknown_models) and cost_known,
        "unknownModels": sorted(unknown_models),
        "durationMin": timing["activeMin"],  # активное время: span врёт на возобновлённых сессиях
        "spanMin": timing["spanMin"],
        "idleGaps": len(timing["idleGaps"]),
        "toolCalls": tool_calls,
        "failures": failures,
        "humanMessages": human_messages,
        "interruptions": interruptions,
    }

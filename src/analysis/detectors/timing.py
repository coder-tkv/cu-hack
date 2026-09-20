"""Интервалы между шагами: простои и долгие вызовы инструментов.

Пауза не обязательно означает потерю: человек мог отойти, команда могла выполняться.
Поэтому severity держим низкой, а в объяснении это оговариваем.
"""

from __future__ import annotations

from collections import defaultdict

from ..parser import session_timing
from .util import build_index, describe_tool_call, finding, fmt_minutes, plural

IDLE_MS = 10 * 60 * 1000  # пауза, начиная с которой считаем простоем
SLOW_CALL_MS = 60 * 1000  # вызов инструмента дольше минуты


def detect_idle_and_slow(steps: list[dict]) -> list[dict]:
    out: list[dict] = []
    timed = [s for s in steps if isinstance(s.get("ts"), int)]
    timed.sort(key=lambda s: (s["ts"], s["id"]))

    # (1) простои между шагами
    gaps = []
    for prev, cur in zip(timed, timed[1:]):
        d = cur["ts"] - prev["ts"]
        if d > IDLE_MS:
            gaps.append({"minutes": round(d / 60000), "fromStepId": prev["id"], "toStepId": cur["id"]})
    if gaps:
        t = session_timing(steps)
        idle_min = sum(g["minutes"] for g in gaps)
        top = sorted(gaps, key=lambda g: -g["minutes"])[:5]
        share = idle_min / t["spanMin"] if t["spanMin"] else 0
        out.append(
            finding(
                "idle_gaps",
                severity=min(0.45, 0.15 + share * 0.3),
                title=(
                    f"{len(gaps)} {plural(len(gaps), ('пауза', 'паузы', 'пауз'))} дольше 10 минут, "
                    f"суммарно {fmt_minutes(idle_min)} (активной работы {fmt_minutes(t['activeMin'])})"
                ),
                step_ids=[i for g in top for i in (g["fromStepId"], g["toStepId"])],
                metrics={
                    "gaps": len(gaps),
                    "idleMinutes": idle_min,
                    "activeMinutes": t["activeMin"],
                    "spanMinutes": t["spanMin"],
                },
                evidence={"topGaps": top},
                explanation=(
                    "Между этими шагами лог молчал. Это может быть ожидание человека, а не "
                    "потеря агента: сравнивайте активное время со span сессии."
                ),
            )
        )

    # (2) долгие вызовы инструментов
    idx = build_index(steps)
    result_by_call = idx["resultByCall"]
    slow = []
    for s in steps:
        if s.get("kind") != "tool_call":
            continue
        r = result_by_call.get(s["id"])
        if not r or not isinstance(s.get("ts"), int) or not isinstance(r.get("ts"), int):
            continue
        d = r["ts"] - s["ts"]
        if d >= SLOW_CALL_MS:
            slow.append({"step": s, "ms": d})
    if len(slow) >= 3:
        by_tool: dict[str, int] = defaultdict(int)
        for x in slow:
            by_tool[x["step"].get("tool") or "?"] += 1
        worst = sorted(slow, key=lambda x: -x["ms"])[:6]
        total_min = round(sum(x["ms"] for x in slow) / 60000)
        out.append(
            finding(
                "slow_tool_calls",
                severity=min(0.5, 0.2 + len(slow) * 0.02),
                title=(
                f"{len(slow)} {plural(len(slow), ('вызов', 'вызова', 'вызовов'))} инструментов "
                f"дольше минуты, суммарно {fmt_minutes(total_min)}"
            ),
                step_ids=[x["step"]["id"] for x in worst],
                metrics={"slowCalls": len(slow), "totalMinutes": total_min, "byTool": dict(by_tool)},
                evidence={
                    "worst": [
                        {
                            "stepId": x["step"]["id"],
                            "line": x["step"].get("line"),
                            "seconds": round(x["ms"] / 1000),
                            "call": describe_tool_call(x["step"]),
                        }
                        for x in worst
                    ]
                },
                explanation=(
                    "Долгие вызовы — это либо тяжёлые команды, либо ожидание таймаутов. "
                    "Проверьте, не ждал ли агент того, что можно было не запускать."
                ),
            )
        )

    return out

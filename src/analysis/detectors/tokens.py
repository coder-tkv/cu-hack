"""Расход токенов по участкам сессии.

Считаем по «ходам» (участок между репликами человека). Кэш учитываем отдельно:
чтение кэша в 10 раз дешевле обычного входа, запись — дороже входа.
Дорогой участок сам по себе не проблема, поэтому отдельно отмечаем участки,
где много потратили и при этом ни одного файла не изменили.
"""

from __future__ import annotations

from statistics import median

from ..pricing import step_cost
from .util import MUTATING_TOOLS, build_index, by_id, finding, snippet

MIN_SESSION_TOKENS = 20_000  # на крошечных сессиях разбор по участкам смысла не имеет
MIN_TURNS = 3  # если ход всего один, его доля равна 100% по определению — это не находка


def detect_token_hotspots(steps: list[dict]) -> list[dict]:
    idx = build_index(steps)
    turns = idx["turns"]
    steps_by_id = by_id(steps)
    if not turns:
        return []

    per_turn = []
    for t in turns:
        tin = tout = cread = cwrite = 0
        cost = 0.0
        cost_known = False
        mutating = 0
        calls = 0
        for sid in t["stepIds"]:
            s = steps_by_id[sid]
            u = s.get("usage")
            if isinstance(u, dict):
                tin += u.get("in", 0)
                tout += u.get("out", 0)
                cread += u.get("cacheRead", 0)
                cwrite += u.get("cacheWrite", 0)
                c = step_cost(s)
                if c is not None:
                    cost += c
                    cost_known = True
            if s.get("kind") == "tool_call":
                calls += 1
                if s.get("tool") in MUTATING_TOOLS:
                    mutating += 1
        per_turn.append(
            {
                "turn": t,
                "billable": tin + tout + cwrite + cread // 10,  # вход-эквивалент с учётом кэша
                "tokens": {"in": tin, "out": tout, "cacheRead": cread, "cacheWrite": cwrite},
                "cost": round(cost, 4) if cost_known else None,
                "mutating": mutating,
                "calls": calls,
            }
        )

    total = sum(p["billable"] for p in per_turn)
    if total < MIN_SESSION_TOKENS or len(per_turn) < MIN_TURNS:
        return []

    values = sorted(p["billable"] for p in per_turn)
    med = median(values) if values else 0
    out: list[dict] = []

    # участок «дорого и без правок» информативнее простого «дорого»: показываем только его
    no_change_turns = {
        p["turn"]["index"]
        for p in per_turn
        if total and p["billable"] / total >= 0.15 and p["mutating"] == 0 and p["calls"] >= 5
    }

    for p in sorted(per_turn, key=lambda x: -x["billable"])[:3]:
        if p["turn"]["index"] in no_change_turns:
            continue
        share = p["billable"] / total if total else 0
        if share < 0.2 or (med and p["billable"] < med * 2):
            continue
        t = p["turn"]
        out.append(
            finding(
                "token_hotspot",
                severity=min(0.75, 0.25 + share),
                title=(
                    f"Участок сессии съел {round(share * 100)}% расхода токенов "
                    f"({p['calls']} вызовов инструментов)"
                ),
                step_ids=_anchor_steps(t, steps_by_id),
                metrics={
                    "shareOfSession": round(share, 3),
                    "billableTokens": p["billable"],
                    "costUsd": p["cost"],
                    "medianTurnTokens": med,
                    "calls": p["calls"],
                    "fileEdits": p["mutating"],
                },
                evidence={
                    "turnIndex": t["index"],
                    "promptStepId": t["promptStepId"],
                    "promptText": snippet(t["promptText"], 300),
                    "stepRange": [t["stepIds"][0], t["stepIds"][-1]],
                    "tokens": p["tokens"],
                },
                explanation=(
                    "На этот участок пришлась основная часть расхода. Сам по себе объём "
                    "не доказывает бесполезность работы — смотрите, что происходило внутри."
                ),
            )
        )

    # потратили много и ничего не изменили
    for p in per_turn:
        share = p["billable"] / total if total else 0
        if share >= 0.15 and p["mutating"] == 0 and p["calls"] >= 5:
            t = p["turn"]
            out.append(
                finding(
                    "spend_without_changes",
                    severity=min(0.8, 0.4 + share),
                    title=(
                        f"{round(share * 100)}% расхода токенов на участке, где не изменён "
                        f"ни один файл ({p['calls']} вызовов)"
                    ),
                    step_ids=_anchor_steps(t, steps_by_id),
                    metrics={
                        "shareOfSession": round(share, 3),
                        "billableTokens": p["billable"],
                        "costUsd": p["cost"],
                        "calls": p["calls"],
                        "fileEdits": 0,
                    },
                    evidence={
                        "turnIndex": t["index"],
                        "promptStepId": t["promptStepId"],
                        "promptText": snippet(t["promptText"], 300),
                        "stepRange": [t["stepIds"][0], t["stepIds"][-1]],
                        "tokens": p["tokens"],
                    },
                    explanation=(
                        "Участок с большим расходом без единой правки файлов: чтение и попытки "
                        "были, результата в коде нет. Это может быть и легитимным разбором задачи."
                    ),
                )
            )

    return out


def _anchor_steps(turn: dict, steps_by_id: dict[int, dict]) -> list[int]:
    """Ссылаемся на реплику человека и на вызовы инструментов участка (до 10 штук)."""
    ids: list[int] = []
    if turn["promptStepId"]:
        ids.append(turn["promptStepId"])
    calls = [sid for sid in turn["stepIds"] if steps_by_id[sid].get("kind") == "tool_call"]
    ids.extend(calls[:10])
    if not ids:
        ids = turn["stepIds"][:5]
    return ids

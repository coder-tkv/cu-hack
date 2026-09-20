"""Вмешательства человека.

Считаем только настоящие реплики (parser помечает служебные synthetic=True).
Короткая реплика с отрицанием — признак того, что агент пошёл не туда.
Но реплика человека может быть и новой задачей, поэтому формулировки осторожные.
"""

from __future__ import annotations

import re

from .util import finding, jaccard, plural, snippet, tokens_of

# «нет», «не то», «стоп» и прочие сигналы, что агента разворачивают
CORRECTION_PATTERNS = (
    r"^нет\b", r"\bне то\b", r"\bне так\b", r"\bне туда\b", r"\bне надо\b", r"\bне нужно\b",
    r"\bстоп\b", r"\bподожди\b", r"\bпогоди\b", r"\bотмени\b", r"\bверни\b",
    r"\bнеправильно\b", r"\bя же (говорил|просил|сказал)\b", r"\bзачем\b", r"\bопять\b",
    r"\bсломал\b", r"\bне работает\b", r"\bснова не\b",
    r"^no\b", r"\bnot that\b", r"\bwrong\b", r"\bstop\b", r"\brevert\b", r"\bundo\b",
    r"\bthat'?s not\b", r"\bbroke\b", r"\bdoesn'?t work\b",
)
_CORRECTION_RE = re.compile("|".join(CORRECTION_PATTERNS), re.IGNORECASE)

SHORT_MESSAGE = 200  # символов: «нет, не это» против новой постановки задачи
REPEAT_SIMILARITY = 0.6  # ниже — уже не «то же указание», а просто похожая лексика
REPEAT_STEP_DISTANCE = 150  # повтор указания ищем рядом, а не через всю сессию


def is_correction(text: str | None) -> bool:
    if not isinstance(text, str):
        return False
    t = text.strip()
    if not t or len(t) > SHORT_MESSAGE:
        return False
    return bool(_CORRECTION_RE.search(t))


def detect_human_interventions(steps: list[dict]) -> list[dict]:
    humans = [s for s in steps if s.get("kind") == "human" and not s.get("synthetic")]
    interrupts = [s for s in steps if s.get("interrupted")]
    out: list[dict] = []

    corrections = [s for s in humans if is_correction(s.get("text"))]
    if len(corrections) >= 2:
        out.append(
            finding(
                "human_corrections",
                severity=min(0.85, 0.4 + 0.12 * len(corrections)),
                title=(
                    f"Человек {len(corrections)} "
                    f"{plural(len(corrections), ('раз', 'раза', 'раз'))} разворачивал агента "
                    "короткой репликой"
                ),
                step_ids=[s["id"] for s in corrections][:12],
                metrics={"corrections": len(corrections), "humanMessages": len(humans)},
                evidence={
                    "messages": [
                        {"stepId": s["id"], "line": s.get("line"), "text": snippet(s.get("text"), 160)}
                        for s in corrections[:8]
                    ]
                },
                explanation=(
                    "Короткие правящие реплики означают, что агент уходил в сторону и его "
                    "приходилось возвращать. Часть таких реплик может быть уточнением задачи."
                ),
            )
        )

    if len(interrupts) >= 2:
        out.append(
            finding(
                "interruptions",
                severity=min(0.8, 0.35 + 0.12 * len(interrupts)),
                title=(
                    f"Работа агента прервана человеком {len(interrupts)} "
                    f"{plural(len(interrupts), ('раз', 'раза', 'раз'))}"
                ),
                step_ids=[s["id"] for s in interrupts][:12],
                metrics={"interruptions": len(interrupts)},
                evidence={
                    "stepIds": [s["id"] for s in interrupts][:12],
                    "lines": [s.get("line") for s in interrupts][:12],
                },
                explanation=(
                    "Прерывание — сильный сигнал: человек видел, что продолжать текущий путь "
                    "бессмысленно, и остановил агента."
                ),
            )
        )

    # одно и то же указание пришлось повторить.
    # Похожие реплики склеиваем в один кластер: цепочка A~B~C — это одна проблема,
    # а не три находки.
    clusters: list[list[dict]] = []
    for later in humans:
        t_later = later.get("text") or ""
        if len(t_later) < 25:
            continue
        tok_later = tokens_of(t_later)
        placed = False
        for cluster in clusters:
            anchor = cluster[-1]
            if later["id"] - anchor["id"] > REPEAT_STEP_DISTANCE:
                continue
            if jaccard(tokens_of(anchor.get("text") or ""), tok_later) >= REPEAT_SIMILARITY:
                cluster.append(later)
                placed = True
                break
        if not placed:
            clusters.append([later])

    for cluster in clusters:
        if len(cluster) < 2:
            continue
        times = len(cluster)
        out.append(
            finding(
                "repeated_instruction",
                severity=min(0.8, 0.45 + 0.12 * (times - 1)),
                title=(
                    f"Одно указание человек повторил {times} "
                    f"{plural(times, ('раз', 'раза', 'раз'))}: "
                    f"«{snippet(cluster[0].get('text'), 60)}»"
                ),
                step_ids=[s["id"] for s in cluster][:10],
                metrics={"repeats": times},
                evidence={
                    "messages": [
                        {"stepId": s["id"], "line": s.get("line"), "text": snippet(s.get("text"), 200)}
                        for s in cluster[:6]
                    ]
                },
                explanation=(
                    "Близкие по смыслу реплики человека подряд: предыдущее указание не было "
                    "выполнено так, как ожидалось. Возможен и вариант, что человек уточнял задачу."
                ),
            )
        )

    return out

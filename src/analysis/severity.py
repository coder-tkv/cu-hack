"""Полосы значимости и прозрачные правила, по которым находка в них попала.

Документ архитектуры (8.8) требует ранжировать прозрачными правилами и прямо
предупреждает: число вроде confidence=0.93 нельзя выдавать за измеренную
вероятность. Поэтому наружу идёт полоса (высокая / средняя / низкая) и список
сработавших правил, а число остаётся только для сортировки внутри полосы.

Значимость эпизода и уверенность в его трактовке — разные вещи. Здесь только
значимость: во что нам обошёлся эпизод и насколько твёрдые под ним факты.
"""

from __future__ import annotations

from .detectors.util import plural


def _times(n: int) -> str:
    return plural(n, ("раз", "раза", "раз"))


BAND_HIGH = "высокая"
BAND_MEDIUM = "средняя"
BAND_LOW = "низкая"
BANDS = (BAND_HIGH, BAND_MEDIUM, BAND_LOW)
BAND_ORDER = {BAND_HIGH: 0, BAND_MEDIUM: 1, BAND_LOW: 2}

# Находки, которые сами по себе ничего не доказывают: справочный фон сессии.
INFORMATIONAL = {"idle_gaps", "slow_tool_calls", "api_errors", "token_hotspot"}

# Твёрдые факты: вызов повторён, вызов упал, правка отменена — это видно в логе.
DIRECT_EVIDENCE = {
    "repeated_call", "retry_loop", "repeated_error", "edit_revert",
    "interruptions", "file_churn", "rewrite_loop", "repeated_instruction",
    "human_corrections", "high_failure_rate", "spend_without_changes", "similar_call",
}


def evidence_strength(ftype: str) -> str:
    """direct — утверждение читается прямо из шагов; indirect — это признак."""
    if ftype in INFORMATIONAL:
        return "indirect"
    return "direct" if ftype in DIRECT_EVIDENCE else "indirect"


def rules_for(f: dict) -> list[str]:
    """Человекочитаемые правила, сработавшие на этой находке."""
    t = f.get("type")
    m = f.get("metrics") or {}
    e = f.get("evidence") or {}
    rules: list[str] = []

    if t in ("repeated_call", "similar_call"):
        n = m.get("repeats") or 0
        rules.append(f"вызов повторён {n} {_times(n)}")
        if m.get("mutatingBetween") == 0:
            rules.append("в доступных событиях между попытками не обнаружено правок файлов")
        else:
            rules.append(f"между попытками правились файлы ({m.get('mutatingBetween')})")
        if m.get("backToBack"):
            rules.append("часть повторов идёт подряд, без других действий между ними")
        if e.get("resultsIdentical"):
            rules.append("результат каждой попытки совпадает")
        if e.get("errorsIdentical"):
            rules.append("ошибка во всех попытках одна и та же")
        if m.get("compactionsBetween"):
            rules.append("между повторами сжимался контекст — агент мог потерять прошлый результат")
    elif t == "retry_loop":
        n = m.get("attempts") or 0
        rules.append(f"один и тот же вызов падал {n} {_times(n)}")
        rules.append("причина отказа не менялась" if m.get("sameError") else "ошибки отличались")
    elif t == "repeated_error":
        rules.append(f"одна ошибка в {m.get('occurrences')} вызовах")
        rules.append(f"разных вызовов: {m.get('distinctCalls')}")
    elif t == "high_failure_rate":
        rules.append(f"падений {m.get('failures')} из {m.get('calls')} вызовов с известным статусом")
    elif t == "api_errors":
        rules.append(f"сбоев API: {m.get('count')}")
        rules.append("это сбой среды, а не решение агента")
    elif t in ("token_hotspot", "spend_without_changes"):
        rules.append(f"доля расхода сессии: {round((m.get('shareOfSession') or 0) * 100)}%")
        rules.append("на участке не изменён ни один файл" if m.get("fileEdits") == 0
                     else f"правок файлов на участке: {m.get('fileEdits')}")
    elif t == "edit_revert":
        rules.append("более поздняя правка вернула ровно тот текст, который убрала предыдущая")
    elif t == "file_churn":
        rules.append(f"правок одного файла: {m.get('edits')}")
    elif t == "rewrite_loop":
        rules.append(f"полных перезаписей файла: {m.get('writes')}")
    elif t == "human_corrections":
        rules.append(f"коротких реплик-разворотов: {m.get('corrections')}")
    elif t == "interruptions":
        rules.append(f"прерываний человеком: {m.get('interruptions')}")
    elif t == "repeated_instruction":
        n = m.get("repeats") or 0
        rules.append(f"одно указание повторено {n} {_times(n)}")
    elif t == "idle_gaps":
        rules.append(f"интервалов без записей: {m.get('gaps')}")
        rules.append("интервал мог уйти на ожидание человека или выполнение команды")
    elif t == "slow_tool_calls":
        rules.append(f"вызовов дольше минуты: {m.get('slowCalls')}")

    return rules


def classify(f: dict) -> dict:
    """Полоса значимости + правила. Полосу определяем правилами, не порогом по числу."""
    t = f.get("type")
    m = f.get("metrics") or {}
    e = f.get("evidence") or {}
    rules = rules_for(f)

    band = BAND_LOW

    # Высокая: подтверждённые неудачные попытки без наблюдаемой коррекции
    # либо устойчивый цикл с твёрдыми доказательствами.
    if t == "retry_loop" and m.get("sameError") and (m.get("attempts") or 0) >= 3:
        band = BAND_HIGH
    elif t == "repeated_call" and (m.get("repeats") or 0) >= 4 and m.get("mutatingBetween") == 0 \
            and (e.get("resultsIdentical") or e.get("errorsIdentical")):
        band = BAND_HIGH
    elif t == "repeated_error" and (m.get("occurrences") or 0) >= 4:
        band = BAND_HIGH
    elif t == "repeated_instruction" and (m.get("repeats") or 0) >= 3:
        band = BAND_HIGH
    elif t == "interruptions" and (m.get("interruptions") or 0) >= 3:
        band = BAND_HIGH

    # Средняя: несколько связанных неудач, вероятный возврат изменений,
    # перепахивание файла, разворот человеком.
    elif t in ("retry_loop", "repeated_error", "edit_revert", "high_failure_rate",
               "human_corrections", "interruptions", "repeated_instruction",
               "spend_without_changes"):
        band = BAND_MEDIUM
    elif t == "repeated_call" and (m.get("repeats") or 0) >= 3 and m.get("mutatingBetween") == 0:
        band = BAND_MEDIUM
    elif t == "file_churn" and (m.get("edits") or 0) >= 6:
        band = BAND_MEDIUM
    elif t == "rewrite_loop" and (m.get("writes") or 0) >= 3:
        band = BAND_MEDIUM

    # Низкая: слабый сигнал, отдельная пауза, дорогой участок без доказанного
    # отсутствия прогресса — остаётся значением по умолчанию.

    return {
        "band": band,
        "rules": rules,
        "evidenceStrength": evidence_strength(t),
        "informational": t in INFORMATIONAL,
    }


def sort_key(f: dict):
    """Порядок отчёта: полоса, затем число, затем позиция в логе (для стабильности)."""
    return (
        BAND_ORDER.get(f.get("severityBand"), 3),
        -float(f.get("severity") or 0),
        f["stepIds"][0] if f.get("stepIds") else 0,
    )

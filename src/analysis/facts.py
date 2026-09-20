"""Факт и ограничения находки.

Дизайн отчёта показывает у каждой находки два разных блока: «ФАКТ — посчитано
кодом» и «ГИПОТЕЗА — объяснено моделью». Здесь живёт первый: одно предложение,
целиком собранное из чисел и цитат лога, без предположений о причинах.

Этот же текст уходит в промпт: модель объясняет ровно то, что посчитал код, и
не придумывает числа. limitations — честный список того, чего код установить не
смог; в дизайне это строка «Контекст между второй и третьей попыткой был усечён».
"""

from __future__ import annotations

from .detectors.util import plural, snippet

_TIMES = ("раз", "раза", "раз")


def fact_text(f: dict) -> str:
    """Одно предложение с числами. Никаких «вероятно» — это работа модели."""
    t = f.get("type")
    m = f.get("metrics") or {}
    e = f.get("evidence") or {}
    tool = e.get("tool") or "инструмент"
    what = snippet(e.get("argsPreview"), 80) or ""
    n_ep = f.get("episodeCount")
    tail = f" Повторялось в {n_ep} эпизодах сессии." if n_ep else ""

    if t == "repeated_call":
        n = m.get("repeats", 0)
        base = f"{tool} «{what}» вызван {n} {plural(n, _TIMES)} с теми же аргументами."
        if m.get("mutatingBetween") == 0:
            base += " Между попытками не найдено правок файлов."
        else:
            base += f" Между попытками правились файлы: {m['mutatingBetween']}."
        if e.get("resultsIdentical"):
            base += " Результат всех вызовов совпадает."
        return base + tail
    if t == "similar_call":
        n = m.get("repeats", 0)
        return f"{n} близких по написанию команд подряд: {', '.join((e.get('variants') or [])[:3])}.{tail}"
    if t == "retry_loop":
        n = m.get("attempts", 0)
        base = f"{tool} «{what}» завершился ошибкой {n} {plural(n, _TIMES)}."
        if m.get("sameError"):
            base += f" Текст ошибки совпадает: {snippet(e.get('errorSnippet'), 120)}."
        return base + tail
    if t == "repeated_error":
        return (f"Одна и та же ошибка «{snippet(e.get('signature'), 80)}» получена "
                f"в {m.get('occurrences')} вызовах, различных по аргументам: {m.get('distinctCalls')}.")
    if t == "high_failure_rate":
        return (f"Ошибкой завершились {m.get('failures')} из {m.get('calls')} вызовов "
                f"с известным статусом ({round((m.get('rate') or 0) * 100)}%). "
                f"Вызовов без результата: {m.get('unknownStatusCount', 0)}.")
    if t == "api_errors":
        return f"Ошибок обращения к API модели: {m.get('count')}."
    if t == "token_hotspot":
        return (f"На участок пришлось {round((m.get('shareOfSession') or 0) * 100)}% расхода "
                f"сессии при {m.get('calls')} вызовах инструментов и {m.get('fileEdits')} правках файлов.")
    if t == "spend_without_changes":
        return (f"На участке {m.get('calls')} вызовов инструментов и {round((m.get('shareOfSession') or 0) * 100)}% "
                f"расхода сессии, правок файлов — ноль.")
    if t == "edit_revert":
        return (f"Файл {e.get('filePath')} изменён и возвращён к прежнему виду: "
                f"правка на шаге {e.get('editStepId')}, возврат на шаге {e.get('revertStepId')}.")
    if t == "file_churn":
        return f"Файл {e.get('filePath')} правился {m.get('edits')} {plural(m.get('edits', 0), _TIMES)}.{tail}"
    if t == "rewrite_loop":
        return (f"Файл {e.get('filePath')} перезаписан целиком {m.get('writes')} "
                f"{plural(m.get('writes', 0), _TIMES)}.{tail}")
    if t == "human_corrections":
        return (f"Коротких реплик человека с отрицанием: {m.get('corrections')} "
                f"из {m.get('humanMessages')} сообщений.")
    if t == "interruptions":
        return f"Работа агента прервана человеком {m.get('interruptions')} {plural(m.get('interruptions', 0), _TIMES)}."
    if t == "repeated_instruction":
        return (f"Реплики человека совпадают по смыслу: повторов {m.get('repeats')}, "
                f"сходство {m.get('similarity', '—')}.{tail}")
    if t == "idle_gaps":
        return (f"Интервалов без записей длиннее 10 минут: {m.get('gaps')}, суммарно {m.get('idleMinutes')} мин "
                f"при активном времени {m.get('activeMinutes')} мин.")
    if t == "slow_tool_calls":
        return (f"Вызовов длительностью больше минуты: {m.get('slowCalls')}, "
                f"суммарно {m.get('totalMinutes')} мин.")
    if t == "bash_instead_of_tool":
        return (f"Через Bash выполнено {m.get('occurrences')} операций вида «{e.get('category')}», "
                f"для которых в сессии есть инструмент {m.get('tool')}.{tail}")
    if t == "missing_cli":
        return f"Сообщение об отсутствии команды «{m.get('binary')}» встречается в {m.get('occurrences')} результатах инструментов.{tail}"
    if t == "tool_permission_denied":
        return f"Отклонено по разрешениям вызовов: {m.get('denials')}. Инструменты: {', '.join(m.get('tools') or []) or '—'}."
    return f.get("title") or ""


# Что код принципиально не может установить по логу
_COMMON = {
    "repeated_call": [
        "релевантного изменения между попытками в доступных событиях не найдено — "
        "состояние проекта могло измениться вне лога",
    ],
    "similar_call": ["сходство команд — сигнал для просмотра, а не доказательство одинаковых действий"],
    "retry_loop": ["причина повтора неизвестна: это может быть и ожидание внешнего события"],
    "repeated_error": ["совпадение подписи ошибки не доказывает одну причину"],
    "high_failure_rate": ["вызовы без результата в знаменатель не вошли: их статус неизвестен"],
    "api_errors": ["сбои среды не относятся к решениям агента"],
    "token_hotspot": ["объём расхода не доказывает бесполезность работы на участке"],
    "spend_without_changes": ["чтение и попытки без правок могут быть нормальным началом задачи"],
    "edit_revert": ["осознанный откат неудачной гипотезы выглядит в логе так же"],
    "file_churn": ["число правок не говорит об их качестве"],
    "rewrite_loop": ["перезапись могла быть запрошена человеком"],
    "human_corrections": ["реплика человека может быть новой задачей, а не исправлением агента"],
    "interruptions": ["причина прерывания в логе не зафиксирована"],
    "repeated_instruction": ["повтор указания может быть уточнением, а не следствием ошибки агента"],
    "idle_gaps": ["интервал без записей мог уйти на ожидание человека или выполнение команды"],
    "slow_tool_calls": ["timestamp записи не всегда совпадает со временем старта действия"],
    "bash_instead_of_tool": ["у команды могли быть причины, не видные в логе"],
    "missing_cli": ["нехватка команды в окружении, а не ошибка рассуждения агента"],
    "tool_permission_denied": ["политика разрешений в логе не зафиксирована"],
}


def limitations(f: dict) -> list[str]:
    out = list(_COMMON.get(f.get("type"), []))
    m = f.get("metrics") or {}
    if m.get("compactionsBetween"):
        out.append("контекст сессии между попытками был усечён: агент мог потерять прошлый результат")
    if f.get("episodesTruncated"):
        out.append("показаны не все эпизоды: список ограничен")
    if not (f.get("evidence") or {}).get("resultSnippet") and f.get("type") == "retry_loop" \
            and not m.get("sameError"):
        out.append("текста ошибки в логе нет: совпадение причин не проверено")
    return out

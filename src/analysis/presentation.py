"""То, из чего фронт собирает карточку находки.

Макет отчёта показывает у карточки: категорию в заголовке, бейдж значимости,
бейдж источника объяснения (llm / rule_based), блоки ФАКТ и ГИПОТЕЗА,
рекомендацию с коротким правилом и строку ограничения.

Категорию, источник объяснения и короткое правило даёт код — это наша таксономия.
Бейдж assessment (inefficient / reasonable / uncertain) ставит модель: кода,
который бы решал это за неё, здесь нет и быть не должно.
"""

from __future__ import annotations

from .severity import BAND_HIGH, BAND_LOW, BAND_MEDIUM

# тип находки -> заголовок карточки
CATEGORY = {
    "repeated_call": ("repeats", "Повторяющиеся вызовы"),
    "similar_call": ("repeats", "Повторяющиеся вызовы"),
    "retry_loop": ("failures", "Ошибки и повторные попытки"),
    "repeated_error": ("failures", "Ошибки и повторные попытки"),
    "high_failure_rate": ("failures", "Ошибки и повторные попытки"),
    "api_errors": ("failures", "Сбои среды"),
    "token_hotspot": ("tokens", "Расход токенов"),
    "spend_without_changes": ("tokens", "Расход без результата"),
    "edit_revert": ("edits", "Отменённые правки"),
    "file_churn": ("edits", "Правки файлов"),
    "rewrite_loop": ("edits", "Правки файлов"),
    "human_corrections": ("interventions", "Вмешательства человека"),
    "interruptions": ("interventions", "Вмешательства человека"),
    "repeated_instruction": ("interventions", "Повторные указания"),
    "idle_gaps": ("timing", "Интервалы и простои"),
    "slow_tool_calls": ("timing", "Долгие вызовы"),
    "bash_instead_of_tool": ("tools", "Инструменты и доступы"),
    "missing_cli": ("tools", "Инструменты и доступы"),
    "tool_permission_denied": ("tools", "Инструменты и доступы"),
}

# Заголовок отчёта говорит, что делал агент. Сбои среды сюда не попадают:
# «Агент вызывал ошибки API» — неправда, это не его поведение.
NOT_AGENT_BEHAVIOUR = {"api_errors"}

# из чего складывается заголовок отчёта, если объяснять некому
HEADLINE = {
    "repeated_call": "повторял вызовы без изменений между попытками",
    "similar_call": "перебирал варианты одной команды",
    "retry_loop": "повторял упавшую команду",
    "repeated_error": "упирался в одну и ту же ошибку",
    "high_failure_rate": "часто получал ошибки инструментов",
    "edit_revert": "отменял собственные правки",
    "file_churn": "подолгу перепахивал одни и те же файлы",
    "rewrite_loop": "переписывал файлы целиком",
    "spend_without_changes": "тратил токены на участках без единой правки",
    "token_hotspot": "неравномерно расходовал токены по участкам",
    "human_corrections": "требовал коротких поправок от человека",
    "interruptions": "был прерван человеком",
    "repeated_instruction": "заставлял повторять указания",
    "idle_gaps": "работал с длинными паузами",
    "slow_tool_calls": "ждал долгие команды",
    "bash_instead_of_tool": "делал через Bash то, для чего есть инструменты",
    "missing_cli": "вызывал команды, которых нет в окружении",
    "tool_permission_denied": "упирался в запрет на инструменты",
}


def decorate(findings: list[dict]) -> None:
    """Дописывает в находки поля, нужные карточке. Меняет список на месте."""
    for f in findings:
        category, title = CATEGORY.get(f.get("type"), ("other", "Прочее"))
        f["category"] = category
        f["categoryTitle"] = title
        # объяснение сейчас от кода; ML перезапишет на "llm", когда объяснит
        f.setdefault("explanationSource", "rule_based" if f.get("explanation") else "not_explained")
        f["evidenceSteps"] = len(f.get("stepIds") or [])


def summary(findings: list[dict]) -> dict:
    """Итог для шапки отчёта. Считает код: никаких оценок, только состав находок."""
    bands = {BAND_HIGH: 0, BAND_MEDIUM: 0, BAND_LOW: 0}
    for f in findings:
        if f.get("severityBand") in bands:
            bands[f["severityBand"]] += 1

    if not findings:
        return {
            "headline": "Значимых проблем не найдено в доступных данных",
            "total": 0,
            "byBand": bands,
            "significant": 0,
        }

    parts: list[str] = []
    for f in findings:
        if f.get("type") in NOT_AGENT_BEHAVIOUR:
            continue
        phrase = HEADLINE.get(f.get("type"))
        if phrase and phrase not in parts:
            parts.append(phrase)
        if len(parts) == 2:
            break
    headline = ("Агент " + " и ".join(parts)) if parts else "Найдены сбои среды, не связанные с поведением агента"

    return {
        "headline": headline,
        "total": len(findings),
        "byBand": bands,
        "significant": bands[BAND_HIGH] + bands[BAND_MEDIUM],
    }


def rule_snippet(recommendation: dict, limit: int = 220) -> str:
    """Короткое правило для рамки в карточке; полный текст остаётся в файле."""
    body = [l.strip() for l in (recommendation.get("content") or "").splitlines()
            if l.strip() and not l.startswith("#") and not l.startswith("_")]
    text = " ".join(body)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"

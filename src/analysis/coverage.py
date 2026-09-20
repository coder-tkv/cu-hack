"""Явный результат по каждому из шести направлений разбора.

Требование кейса и документа архитектуры: по каждому направлению отчёт обязан
сказать что-то определённое — нашли, не нашли, или данных не хватило и почему.
Молчание направления фронту показать нечем.
"""

from __future__ import annotations

from .census import census

FOUND = "found"
CLEAN = "clean"
INSUFFICIENT = "insufficient_data"

# Шесть направлений из кейса плюс одно сверх него: инструменты и доступы.
# Поле required отмечает те шесть, которые обязаны быть в отчёте.
DIRECTIONS = (
    {"id": "repeats", "title": "Повторяющиеся вызовы инструментов",
     "detectors": ("repeated",), "checks": ("toolCalls",),
     "unit": "вызовов инструментов"},
    {"id": "failures", "title": "Падения инструментов и повторные попытки",
     "detectors": ("failures",), "checks": ("callsWithKnownStatus",),
     "unit": "вызовов с известным статусом"},
    {"id": "tokens", "title": "Расход токенов по участкам сессии",
     "detectors": ("tokens",), "checks": ("stepsWithUsage",),
     "unit": "шагов с данными о токенах"},
    {"id": "interventions", "title": "Вмешательства человека",
     "detectors": ("human",), "checks": ("humanMessages",),
     "unit": "реплик человека"},
    {"id": "edits", "title": "Отменённые правки и перепахивание файлов",
     "detectors": ("edits",), "checks": ("fileEdits",),
     "unit": "правок файлов"},
    {"id": "timing", "title": "Интервалы между шагами",
     "detectors": ("timing",), "checks": ("stepsWithTime",),
     "unit": "шагов со временем"},
    {"id": "tools", "title": "Инструменты и доступы", "required": False,
     "detectors": ("tools",), "checks": ("toolCalls",),
     "unit": "вызовов инструментов"},
)


def build_coverage(steps: list[dict], findings: list[dict], warnings: list[str] | None = None) -> list[dict]:
    c = census(steps)
    warnings = warnings or []
    out = []
    for d in DIRECTIONS:
        own = [f for f in findings if f.get("detector") in d["detectors"]]
        checked = {k: c[k] for k in d["checks"]}
        denominator = sum(checked.values())
        broke = [w for w in warnings if any(det in w for det in d["detectors"])]

        if broke:
            status, note = INSUFFICIENT, broke[0]
        elif denominator == 0:
            status = INSUFFICIENT
            note = f"в логе нет данных для этой проверки: {d['unit']} — 0"
        elif own:
            status = FOUND
            note = f"проверено {denominator} {d['unit']}"
        else:
            status = CLEAN
            note = f"проверено {denominator} {d['unit']}, признаков не найдено"

        if d["id"] == "tokens" and status == CLEAN and c["turns"] < 3:
            status, note = INSUFFICIENT, "меньше трёх участков между репликами человека: доли расхода не показательны"

        out.append({
            "direction": d["id"],
            "title": d["title"],
            "required": d.get("required", True),
            "status": status,
            "findings": len(own),
            "findingIds": [f["id"] for f in own],
            "checked": checked,
            "note": note,
        })
    return out

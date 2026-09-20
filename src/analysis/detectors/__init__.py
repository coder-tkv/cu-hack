"""Детекторы проблемного поведения агента. Чистый код, никакой LLM.

run_all(steps) -> findings[], отсортированные по значимости.
Каждая находка: {type, severity, title, stepIds, evidence, metrics, explanation, source}.
Любой упавший детектор не роняет разбор: его ошибка попадает в warnings.
"""

from __future__ import annotations

from .edits import detect_edit_churn
from .failures import detect_failures
from .human import detect_human_interventions
from .repeated import detect_repeated_calls
from .timing import detect_idle_and_slow
from .tokens import detect_token_hotspots

DETECTORS = (
    ("repeated", detect_repeated_calls),
    ("failures", detect_failures),
    ("tokens", detect_token_hotspots),
    ("edits", detect_edit_churn),
    ("human", detect_human_interventions),
    ("timing", detect_idle_and_slow),
)


def run_all(steps: list[dict]) -> tuple[list[dict], list[str]]:
    """Возвращает (findings, warnings). Порядок — по убыванию значимости."""
    findings: list[dict] = []
    warnings: list[str] = []
    valid_ids = {s["id"] for s in steps}

    for name, fn in DETECTORS:
        try:
            got = fn(steps) or []
        except Exception as e:  # один сломанный детектор не должен ронять отчёт
            warnings.append(f"детектор {name} упал: {e}")
            continue
        for f in got:
            # ссылки на шаги обязаны существовать: находку без них не показываем
            f["stepIds"] = [i for i in f.get("stepIds", []) if i in valid_ids]
            if not f["stepIds"]:
                warnings.append(f"находка {f.get('type')} отброшена: нет валидных ссылок на шаги")
                continue
            f["detector"] = name
            findings.append(f)

    findings.sort(key=lambda f: (-f["severity"], f["stepIds"][0]))
    for i, f in enumerate(findings, start=1):
        f["id"] = f"f{i}"
    return findings, warnings


__all__ = ["run_all", "DETECTORS"]

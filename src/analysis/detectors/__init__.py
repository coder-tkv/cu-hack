"""Детекторы проблемного поведения агента. Чистый код, никакой LLM.

run_all(steps) -> findings[], отсортированные по значимости.
Каждая находка: {type, severity, title, stepIds, evidence, metrics, explanation, source}.
Любой упавший детектор не роняет разбор: его ошибка попадает в warnings.
"""

from __future__ import annotations

from ..merge import merge_findings
from ..severity import classify, sort_key
from .edits import detect_edit_churn
from .failures import detect_failures
from .human import detect_human_interventions
from .repeated import detect_repeated_calls
from .timing import detect_idle_and_slow
from .tools import detect_tool_gaps
from .tokens import detect_token_hotspots

# Полный список типов находок. Новый тип обязан попасть сюда — иначе run_all
# положит предупреждение в отчёт, а тест аудита не даст выпустить его без проверки.
FINDING_TYPES = (
    "repeated_call",
    "similar_call",
    "retry_loop",
    "repeated_error",
    "high_failure_rate",
    "api_errors",
    "token_hotspot",
    "spend_without_changes",
    "edit_revert",
    "file_churn",
    "rewrite_loop",
    "human_corrections",
    "interruptions",
    "repeated_instruction",
    "idle_gaps",
    "slow_tool_calls",
    "bash_instead_of_tool",
    "missing_cli",
    "tool_permission_denied",
)

DETECTORS = (
    ("repeated", detect_repeated_calls),
    ("failures", detect_failures),
    ("tokens", detect_token_hotspots),
    ("edits", detect_edit_churn),
    ("human", detect_human_interventions),
    ("timing", detect_idle_and_slow),
    ("tools", detect_tool_gaps),
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
            if f.get("type") not in FINDING_TYPES:
                warnings.append(f"неизвестный тип находки {f.get('type')} от детектора {name}")
            # ссылки на шаги обязаны существовать: находку без них не показываем
            f["stepIds"] = [i for i in f.get("stepIds", []) if i in valid_ids]
            if not f["stepIds"]:
                warnings.append(f"находка {f.get('type')} отброшена: нет валидных ссылок на шаги")
                continue
            f["detector"] = name
            band = classify(f)
            f["severityBand"] = band["band"]
            f["severityRules"] = band["rules"]
            f["evidenceStrength"] = band["evidenceStrength"]
            f["informational"] = band["informational"]
            findings.append(f)

    # однотипные находки по одной цели — это одна проблема в нескольких местах
    findings = merge_findings(findings)
    for i, f in enumerate(findings, start=1):
        f["id"] = f"f{i}"
    return findings, warnings


__all__ = ["run_all", "DETECTORS", "FINDING_TYPES"]

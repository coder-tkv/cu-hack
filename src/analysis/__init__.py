"""Разбор логов кодинг-агента: парсер + детекторы (чистый код, без LLM)."""

from .kpi import compute_kpi
from .parser import parse_file, parse_log, session_timing
from .detectors import run_all


def analyze_log(text: str) -> dict:
    """Текст лога -> отчёт без LLM-части: meta, kpi, findings, steps."""
    parsed = parse_log(text)
    return _finish(parsed)


def analyze_file(path: str) -> dict:
    parsed = parse_file(path)
    return _finish(parsed)


def _finish(parsed: dict) -> dict:
    steps = parsed["steps"]
    findings, warnings = run_all(steps)
    meta = dict(parsed["meta"])
    meta["warnings"] = list(meta.get("warnings", [])) + warnings
    return {
        "meta": meta,
        "kpi": compute_kpi(steps),
        "findings": findings,
        "recommendations": [],  # заполняет LLM-этап
        "steps": steps,
    }


__all__ = [
    "analyze_log",
    "analyze_file",
    "parse_log",
    "parse_file",
    "session_timing",
    "compute_kpi",
    "run_all",
]

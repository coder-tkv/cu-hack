"""Разбор логов кодинг-агента: парсер + детекторы (чистый код, без LLM)."""

from .census import census
from .coverage import build_coverage
from .kpi import compute_kpi
from .parser import parse_file, parse_log, session_timing
from .recommendations import build_claude_md, build_recommendations
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
    # Рекомендации собирает код: если LLM-этап недоступен, отчёт всё равно
    # отвечает на «что поменять к следующей сессии».
    recommendations = build_recommendations(findings)
    return {
        "meta": meta,
        "kpi": compute_kpi(steps),
        "census": census(steps),
        "coverage": build_coverage(steps, findings, warnings),
        "findings": findings,
        "recommendations": recommendations,
        "artifacts": {"CLAUDE.generated.md": build_claude_md(recommendations, meta)},
        "steps": steps,
    }


__all__ = [
    "analyze_log",
    "build_coverage",
    "build_recommendations",
    "build_claude_md",
    "census",
    "analyze_file",
    "parse_log",
    "parse_file",
    "session_timing",
    "compute_kpi",
    "run_all",
]

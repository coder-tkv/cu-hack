"""Экспорт артефактов отчёта. Владелец после перехода Бек-3 на фронт: Бек-1.

Пути задаёт сервер, имена — только из ARTIFACT_ALLOWLIST. Модель имена не выбирает.
"""

import json
from pathlib import Path

from schemas import ARTIFACT_ALLOWLIST, Report


def artifacts_dir(analysis_id: str) -> Path:
    from config import settings
    return settings.storage.exports_dir / analysis_id


def artifact_path(analysis_id: str, name: str) -> Path | None:
    """Путь к артефакту или None, если имя не в allowlist."""
    if name not in ARTIFACT_ALLOWLIST:
        return None
    return artifacts_dir(analysis_id) / name


def render_report_md(report: Report) -> str:
    lines = [
        f"# Отчёт по сессии {report.session_id}",
        "",
        f"Статус анализа: **{report.status.value}**",
        "",
        report.summary,
        "",
        "## Метрики",
        "",
    ]
    for m in report.metrics:
        value = "неизвестно" if m.value is None else str(m.value)
        denom = f" (знаменатель: {m.denominator})" if m.denominator is not None else ""
        lines.append(f"- {m.label}: {value}{denom}")

    lines += ["", "## Находки", ""]
    if not report.findings:
        lines.append("Данных недостаточно для вывода об эффективности." if report.status.value == "insufficient_data"
                     else "Находок нет в пределах доступных данных; это не доказательство эффективности.")
    for f in report.findings:
        lines += [
            f"### {f.rank + 1}. {f.title}",
            "",
            f"- Приоритет: {f.severity.value}",
            f"- Оценка: {f.assessment or 'не объяснено'} ({f.explanation_source})",
            f"- Наблюдение: {f.explanation or '—'}",
            f"- Возможная причина: {f.likely_cause or '—'}",
            f"- Доказательства: {', '.join(f.evidence_step_ids[:8]) or '—'}",
        ]
        if f.limitations:
            lines.append(f"- Ограничения: {'; '.join(f.limitations)}")
        lines.append("")

    lines += ["## Рекомендации", ""]
    if not report.recommendations:
        lines.append("Оснований для изменения инструкций не найдено в доступном анализе.")
    for r in report.recommendations:
        lines += [
            f"- **{r.action}**",
            f"  - Основание: {r.rationale}",
            f"  - Проверка: {r.verification or '—'}",
        ]

    if report.warnings:
        lines += ["", "## Предупреждения", ""] + [f"- {w}" for w in report.warnings]

    lines += [
        "",
        "## Происхождение результата",
        "",
        f"- Парсер: {report.provenance.parser_version}",
        f"- Детекторы: {report.provenance.detector_version}",
        f"- Промпт: {report.provenance.prompt_version}",
        f"- Модель: {report.provenance.model or 'не вызывалась'}",
        "",
        f"Покрытие: распознано шагов {report.coverage.recognized_steps}, "
        f"битых строк {report.coverage.invalid_lines}, "
        f"кандидатов {report.coverage.candidates_explained}/{report.coverage.candidates_total} объяснено.",
    ]
    return "\n".join(lines) + "\n"


def render_claude_md(report: Report) -> str:
    rules = [r for r in report.recommendations if r.rule_text]
    lines = ["# Предлагаемые правила для этого проекта", ""]
    if not rules:
        lines.append("Оснований для изменения инструкций не найдено в доступном анализе.")
        return "\n".join(lines) + "\n"

    lines.append(
        "Это предложения. Просмотри их и перенеси подходящее в свой CLAUDE.md вручную."
    )
    lines.append("")
    for r in rules:
        lines += [
            f"## {r.action}",
            "",
            r.rule_text or "",
            "",
            f"Основание: {r.rationale}",
            f"Проверка пользы: {r.verification or '—'}",
            "",
        ]
    return "\n".join(lines) + "\n"


def write_artifacts(report: Report) -> list[str]:
    """Пишет все три артефакта на диск, возвращает их имена."""
    out = artifacts_dir(report.analysis_id)
    out.mkdir(parents=True, exist_ok=True)
    export_report_json(report, out / "report.json")
    export_report_md(report, out / "report.md")
    export_claude_generated_md(report, out / "CLAUDE.generated.md")
    return list(ARTIFACT_ALLOWLIST)


def _export(content: str, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def export_report_json(report: Report, destination: str | Path) -> Path:
    return _export(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), destination)


def export_report_md(report: Report, destination: str | Path) -> Path:
    return _export(render_report_md(report), destination)


def export_claude_generated_md(report: Report, destination: str | Path) -> Path:
    return _export(render_claude_md(report), destination)

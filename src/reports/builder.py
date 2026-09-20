"""Adapters between detector output, the website contract and ML v2.

The production pipeline parses a file once. Standalone ml/prepare remains a
development helper; it is not run again by this adapter.
"""

import json
import re
from datetime import UTC, datetime

from agent_review import ReviewInput, ReviewReport
from agent_review.redaction import redact
from agent_review.schemas import Candidate as MLCandidate, Evidence, Fact
from analysis.candidates import DETECTOR_VERSIONS, KIND_MAP, PROPOSED_KINDS
from analysis.presentation import CATEGORY
from schemas import (Actor, AnalysisStatus, Coverage, Finding, Metric, Provenance,
                     Recommendation, Report, SourceRef, Step, StepKind)

PARSER_VERSION = "claude-parser-integrated-v2"
DETECTOR_VERSION = "team-detectors-v2"
SECRET_KEY = re.compile(r"password|secret|token|api[_-]?key", re.I)


def clean(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET_KEY.search(k) and isinstance(v, str)
                else clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return redact(value) if isinstance(value, str) else value


def step_id(session_id: str, ordinal: int) -> str:
    return f"{session_id}:step_{ordinal}"


def to_steps(parsed: dict, session_id: str) -> list[Step]:
    """Keep stable IDs and source lines, including service events for coverage."""
    result = []
    for s in parsed["steps"]:
        kind = {"human": StepKind.human_message, "assistant_text": StepKind.assistant_text,
                "tool_call": StepKind.tool_call, "tool_result": StepKind.tool_result}.get(s["kind"], StepKind.system_event)
        actor = {StepKind.human_message: Actor.human, StepKind.assistant_text: Actor.assistant,
                 StepKind.tool_call: Actor.assistant, StepKind.tool_result: Actor.tool}.get(kind, Actor.system)
        if s.get("synthetic"):
            actor = Actor.system
        step_warnings = list(s.get("warnings", []))
        known_system = {"system", "mode", "permission-mode", "file-history-snapshot", "attachment",
                        "progress", "summary", "ai-title", "queue-operation", "last-prompt", "custom-title",
                        "thinking", "assistant_empty", "user_empty"}
        if s["kind"] == "other" and (step_warnings or (s.get("raw") or "").split(":")[0] not in known_system):
            kind, actor = StepKind.unknown, Actor.unknown
            if not step_warnings:
                step_warnings.append("unknown_event_type")
        text = None if s.get("raw") == "thinking" else s.get("text")
        timestamp = None
        if s.get("ts") is not None:
            try:
                timestamp = datetime.fromtimestamp(s["ts"] / 1000, UTC)
            except (ValueError, OverflowError, OSError):
                pass
        args = s.get("args")
        shortened = bool(text and s.get("textLen", len(text)) > len(text))
        result.append(Step(
            step_id=step_id(session_id, s["id"]), session_id=session_id, ordinal=s["id"] - 1,
            source=SourceRef(source_line=s["line"], block_index=s.get("blockIndex", 0),
                             source_event_id=s.get("uuid"), source_message_id=s.get("messageId")),
            parent_event_id=s.get("parentUuid"), branch_id=s.get("agentId") or ("sidechain" if s.get("sidechain") else "main"),
            timestamp=timestamp, kind=kind, actor=actor, tool_call_id=s.get("toolUseId"),
            tool_name=s.get("tool"), arguments=clean(args) if isinstance(args, dict) else None,
            text=clean(text), text_truncated=shortened,
            is_error=s.get("isError") if kind == StepKind.tool_result else None,
            usage_ref=s.get("usageRef"), usage=s.get("usage"), result_metadata=clean(s.get("result")),
            warnings=step_warnings + (["Текст сокращён парсером; исходный файл сохранён."] if shortened else []),
        ))
    return result


def build_ml_packet(raw: dict, steps: list[Step], source_id: str) -> tuple[ReviewInput, list[str]]:
    """Keep every finding in the report; skip ML when its evidence cannot fit."""
    by_id = {s.ordinal + 1: s for s in steps}
    candidates, warnings = [], []
    for f in raw["findings"]:
        refs = list(dict.fromkeys(f["stepIds"]))
        if not refs or len(refs) > 40:
            warnings.append(f"{f['id']}: ML пропущен — слишком много шагов для одного доказательства.")
            continue
        first, last = min(refs), max(refs)
        # All intervening edits, diagnostics and human requests stay visible.
        selected = [s for s in steps if first - 1 <= s.ordinal + 1 <= last + 1]
        if len(selected) > 50:
            warnings.append(f"{f['id']}: ML пропущен — контекст эпизода больше 50 шагов.")
            continue
        evidence = []
        for s in selected:
            text = json.dumps({"kind": s.kind.value, "tool": s.tool_name,
                "arguments": s.arguments, "text": s.text, "is_error": s.is_error,
                "timestamp": s.timestamp.isoformat() if s.timestamp else None,
                "usage": s.usage, "result_metadata": s.result_metadata,
                "warnings": s.warnings}, ensure_ascii=False)
            if len(text) > 6000:
                break
            evidence.append(Evidence(step_id=s.step_id, kind=s.kind.value,
                                     source_line=s.source.source_line, text=text))
        fact = clean(f.get("fact") or "")
        if len(evidence) != len(selected) or not fact or len(fact) > 2000:
            warnings.append(f"{f['id']}: ML пропущен — доказательство превышает лимит; текст не обрезан.")
            continue
        task = next((s.text for s in reversed(steps[:first - 1])
                     if s.kind == StepKind.human_message and s.actor == Actor.human), None)
        candidates.append(MLCandidate(candidate_id=f["id"], kind="detector_observation",
            priority={"высокая": "high", "средняя": "medium"}.get(f.get("severityBand"), "low"),
            task_context=task, facts=[Fact(fact_id="detector_fact", text=fact,
                evidence_step_ids=[by_id[i].step_id for i in refs])], evidence=evidence,
            context_complete=False, limitations=[*clean(f.get("limitations", [])),
                "Сигнал эвристического детектора; сам по себе не доказывает неэффективность."][:30]))
        if len(candidates) == 1000:
            warnings.append("ML ограничен первыми 1000 кандидатами; все находки сохранены в отчёте.")
            break
    return ReviewInput(source_id=source_id, candidates=candidates,
                       warnings=clean(raw["meta"].get("warnings", []))), warnings


def build_report(raw: dict, *, analysis_id: str, session_id: str, llm_enabled: bool,
                 ml: ReviewReport | None = None, warnings: list[str] = ()) -> Report:
    raw = clean(raw)
    meta, kpi = raw["meta"], raw["kpi"]
    review_by_id = {i.candidate.candidate_id: i for i in ml.findings} if ml else {}
    findings, recommendations = [], []
    for rank, f in enumerate(raw["findings"]):
        item = review_by_id.get(f["id"])
        judgment = item.judgment if item else None
        fact = f.get("fact") or "Наблюдение детектора требует проверки по указанным шагам."
        finding = Finding(finding_id=f["id"], candidate_id=f["id"],
            kind=KIND_MAP.get(f["type"]) or PROPOSED_KINDS[f["type"]],
            title=CATEGORY.get(f["type"], ("other", "Наблюдение"))[1],
            severity={"высокая": "high", "средняя": "medium"}.get(f.get("severityBand"), "low"), rank=rank,
            facts={"fact_text": fact, **f.get("metrics", {}), "detector_type": f["type"]},
            evidence_step_ids=[step_id(session_id, i) for i in f["stepIds"]],
            evidence_strength=f.get("evidenceStrength", "indirect"),
            assessment=judgment.assessment if judgment else None,
            explanation=judgment.explanation if judgment else fact,
            explanation_source="llm" if judgment else "rule_based",
            limitations=list(dict.fromkeys([*f.get("limitations", []),
                "Находка — сигнал для проверки, а не доказанная ошибка агента.",
                *(judgment.limitations if judgment else [])])),
            detector_version=DETECTOR_VERSIONS.get(f.get("detector")),
            citations=[q.model_dump() for q in judgment.citations] if judgment else [])
        findings.append(finding)
        if judgment and judgment.assessment == "reasonable":
            continue
        action = judgment.action if judgment else None
        # Do not copy detector prose that asserts an unseen cause or auto-grants permissions.
        if not action:
            action = {
                "repeated": "Проверить, давали ли повторные вызовы новую информацию. Если нет — изменить подход перед следующей попыткой.",
                "failures": "Проверить результаты упавших вызовов и условия повторного запуска.",
                "edits": "Проверить, какие правки сохранились и были ли остальные необходимы для решения задачи.",
                "human": "Сопоставить указания человека с последующими действиями; проверить, были ли это уточнения или исправления.",
                "timing": "Проверить, чем объясняются интервалы: работой инструмента, ожиданием человека или отсутствующими записями.",
                "tokens": "Проверить, какую информацию дал отмеченный участок и можно ли сократить его без потери результата.",
                "tools": "Проверить доступные инструменты и причины отказов. Изменения окружения и разрешений рассматривать отдельно.",
            }.get(f.get("detector"), "Проверить указанные шаги и условия задачи.")
        recommendations.append(Recommendation(recommendation_id=f"r_{rank + 1}", finding_id=f["id"],
            action=action, rationale=fact,
            verification=judgment.verification if judgment and judgment.verification else "Сравнить корректность результата и число обращений на той же задаче.",
            rule_text=judgment.rule_text if judgment else None,
            source="llm" if judgment else "rule_based"))
    incomplete = list(dict.fromkeys([*meta.get("warnings", []), *warnings]))
    if ml and ml.status == "partial":
        incomplete.append("Не все эпизоды получили проверенную оценку модели; факты кода сохранены.")
    insufficient = raw.get("summary", {}).get("dataStatus") == "insufficient_data"
    status = AnalysisStatus.insufficient_data if insufficient else (
        AnalysisStatus.partial if incomplete else AnalysisStatus.complete)
    summary = ("Недостаточно данных для содержательного разбора." if insufficient else
               f"Проверено шагов: {len(raw['steps'])}. Найдено эпизодов для проверки: {len(findings)}.")
    metrics = []
    definitions = [
        ("toolCalls", "Вызовы инструментов", "count"), ("failures", "Вызовы с ошибкой", "count"),
        ("errorRate", "Доля ошибок среди вызовов с известным результатом", "ratio"),
        ("unknownStatusCount", "Вызовы без известного результата", "count"),
        ("tokensIn", "Входные токены", "tokens"), ("tokensOut", "Выходные токены", "tokens"),
        ("cacheRead", "Прочитано из кэша", "tokens"), ("cacheWrite", "Записано в кэш", "tokens"),
        ("cost", "Оценка стоимости исходной сессии", "USD"),
        ("durationMin", "Время между событиями без длинных пауз", "minutes"),
        ("fileEdits", "Вызовы инструментов изменения файлов", "count"),
        ("humanMessages", "Сообщения человека", "count"),
    ]
    for key, label, unit in definitions:
        value = kpi.get(key)
        usage_summary = meta.get("usageSummary", {})
        usage_fields = {"tokensIn": "input_tokens", "tokensOut": "output_tokens",
                        "cacheRead": "cache_read_input_tokens", "cacheWrite": "cache_creation_input_tokens"}
        if key in usage_fields and usage_summary:
            value = usage_summary.get(usage_fields[key])
        if unit == "tokens" and not raw.get("census", {}).get("stepsWithUsage"):
            value = None
        if key == "durationMin" and raw.get("census", {}).get("stepsWithTime", 0) < 2:
            value = None
        limits = ["Приблизительная оценка по таблице тарифов в коде, не сумма списания."] if key == "cost" else []
        if key in usage_fields or key == "cost":
            limits.extend(usage_summary.get("limitations", []))
        if key == "cost" and kpi.get("costPartial"):
            limits.append("Для части моделей стоимость неизвестна.")
        metrics.append(Metric(key=key, label=label, value=value, unit=unit,
            denominator=kpi.get("callsWithKnownStatus") if key == "errorRate" else None,
            limitations=limits))
    return Report(analysis_id=analysis_id, session_id=session_id, status=status, summary=summary,
        coverage=Coverage(total_lines=meta.get("lines", 0), recognized_steps=len(raw["steps"]),
            invalid_lines=meta.get("badJson", 0), unknown_events=sum(s["kind"] == "other" for s in raw["steps"]),
            candidates_total=len(findings), candidates_explained=ml.candidates_reviewed if ml else 0,
            llm_enabled=llm_enabled, incomplete_reasons=incomplete),
        metrics=metrics, findings=findings, recommendations=recommendations, warnings=incomplete,
        provenance=Provenance(parser_version=PARSER_VERSION, detector_version=DETECTOR_VERSION,
            prompt_version=ml.prompt_version if ml and ml.api_calls else None,
            model=ml.model if ml and ml.api_calls else None),
        directions=raw.get("coverage", []), analysis_usage=ml.analysis_usage if ml else {},
        ml_details=ml.model_dump() if ml else None,
        artifacts=["report.json", "report.md", "CLAUDE.generated.md"], created_at=datetime.now(UTC))

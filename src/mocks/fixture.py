"""Мок-данные по контракту v1.

Нужны, чтобы фронт и ML работали до появления настоящего парсера и детекторов.
Сценарий: агент трижды запускает `npm test`, каждый раз одна и та же ошибка,
потом вмешивается человек.

УДАЛИТЬ, когда сквозная цепочка заработает на реальном логе.
"""

from datetime import UTC, datetime, timedelta

from schemas import (
    Actor,
    AnalysisStatus,
    Candidate,
    Coverage,
    Finding,
    Metric,
    Provenance,
    Recommendation,
    Report,
    Severity,
    SourceRef,
    Step,
    StepKind,
)

BASE_TIME = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)


def _step(
    session_id: str,
    ordinal: int,
    line: int,
    kind: StepKind,
    actor: Actor,
    *,
    seconds: int,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    arguments: dict | None = None,
    text: str | None = None,
    is_error: bool | None = None,
) -> Step:
    return Step(
        step_id=f"{session_id}:line_{line}:block_0",
        session_id=session_id,
        ordinal=ordinal,
        source=SourceRef(source_line=line, block_index=0, source_event_id=f"event-{line}"),
        timestamp=BASE_TIME + timedelta(seconds=seconds),
        kind=kind,
        actor=actor,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        text=text,
        is_error=is_error,
    )


def build_mock_steps(session_id: str) -> list[Step]:
    steps = [
        _step(
            session_id,
            0,
            1,
            StepKind.human_message,
            Actor.human,
            seconds=0,
            text="Запусти тесты и исправь ошибку",
        ),
        _step(
            session_id,
            1,
            2,
            StepKind.assistant_text,
            Actor.assistant,
            seconds=2,
            text="Запускаю тесты проекта.",
        ),
    ]
    ordinal = 2
    line = 3
    for attempt in range(3):
        steps.append(
            _step(
                session_id,
                ordinal,
                line,
                StepKind.tool_call,
                Actor.assistant,
                seconds=5 + attempt * 30,
                tool_call_id=f"tool-{attempt + 1}",
                tool_name="Bash",
                arguments={"command": "npm test"},
            )
        )
        ordinal += 1
        line += 1
        steps.append(
            _step(
                session_id,
                ordinal,
                line,
                StepKind.tool_result,
                Actor.tool,
                seconds=6 + attempt * 30,
                tool_call_id=f"tool-{attempt + 1}",
                tool_name="Bash",
                text="npm error Missing script: \"test\"",
                is_error=True,
            )
        )
        ordinal += 1
        line += 1

    steps.append(
        _step(
            session_id,
            ordinal,
            line,
            StepKind.human_message,
            Actor.human,
            seconds=120,
            text="Посмотри в package.json, там нет скрипта test",
        )
    )
    return steps


def build_mock_candidates(session_id: str) -> list[Candidate]:
    steps = build_mock_steps(session_id)
    evidence = [s.step_id for s in steps if s.tool_call_id]
    return [
        Candidate(
            candidate_id="c_001",
            kind="repeated_failed_tool",
            evidence_step_ids=evidence,
            facts={
                "tool_name": "Bash",
                "command": "npm test",
                "attempt_count": 3,
                "explicit_error_count": 3,
                "identical_errors": True,
            },
            detector_version="mock-v0",
            evidence_strength="direct",
            limitations=["в доступных событиях не обнаружено релевантного изменения"],
            severity=Severity.high,
            rank=0,
        ),
        Candidate(
            candidate_id="c_002",
            kind="human_intervention",
            evidence_step_ids=[steps[-1].step_id],
            facts={"human_message_count": 2, "position_ordinal": steps[-1].ordinal},
            detector_version="mock-v0",
            evidence_strength="indirect",
            severity=Severity.low,
            rank=1,
        ),
    ]


def build_mock_report(analysis_id: str, session_id: str) -> Report:
    steps = build_mock_steps(session_id)
    candidates = build_mock_candidates(session_id)

    findings = [
        Finding(
            finding_id="f_001",
            candidate_id="c_001",
            kind="repeated_failed_tool",
            title="Команда `npm test` повторена 3 раза с одинаковой ошибкой",
            severity=Severity.high,
            rank=0,
            facts=candidates[0].facts,
            evidence_step_ids=candidates[0].evidence_step_ids,
            evidence_strength="direct",
            assessment="inefficient",
            explanation=(
                "Команда повторялась после одинакового сообщения об отсутствии test-скрипта; "
                "между попытками в логе нет изменений, способных повлиять на результат."
            ),
            likely_cause="Вероятно, агент не проверил доступные команды проекта.",
            explanation_source="llm",
            limitations=candidates[0].limitations,
            detector_version="mock-v0",
        ),
        Finding(
            finding_id="f_002",
            candidate_id="c_002",
            kind="human_intervention",
            title="Человек вмешался после серии неудачных запусков",
            severity=Severity.low,
            rank=1,
            facts=candidates[1].facts,
            evidence_step_ids=candidates[1].evidence_step_ids,
            evidence_strength="indirect",
            assessment="uncertain",
            explanation="Второе сообщение человека указывает на причину ошибки.",
            likely_cause=None,
            explanation_source="llm",
            limitations=["намерение человека по одному сообщению установить нельзя"],
            detector_version="mock-v0",
        ),
    ]

    recommendations = [
        Recommendation(
            recommendation_id="r_001",
            finding_id="f_001",
            action="Перед запуском тестов проверь scripts в package.json и выбери существующую команду.",
            rationale="Находка f_001: три одинаковые ошибки «Missing script: test» без изменений между попытками.",
            verification="В следующей сессии после одинаковой ошибки появляется диагностический шаг, а не повтор.",
            rule_text=(
                "Перед первым запуском тестов проверь scripts в package.json. "
                "После одинаковой ошибки не повторяй команду без проверки причины."
            ),
            source="llm",
        )
    ]

    metrics = [
        Metric(
            key="recognized_steps",
            label="Распознано шагов",
            value=len(steps),
            unit="count",
            coverage="весь файл",
        ),
        Metric(
            key="tool_calls",
            label="Вызовов инструментов",
            value=3,
            unit="count",
            coverage="весь файл",
        ),
        Metric(
            key="tool_error_rate",
            label="Доля ошибок инструментов",
            value=1.0,
            unit="ratio",
            denominator=3,
            coverage="вызовы с известным статусом",
            limitations=["вызовов мало, доля нестабильна"],
        ),
        Metric(
            key="human_messages",
            label="Сообщений человека",
            value=2,
            unit="count",
            coverage="весь файл",
        ),
        Metric(
            key="source_total_tokens",
            label="Токены исходной сессии",
            value=None,
            unit="tokens",
            coverage="usage в логе отсутствует",
            limitations=["в мок-данных нет usage, значение неизвестно"],
        ),
    ]

    return Report(
        analysis_id=analysis_id,
        session_id=session_id,
        status=AnalysisStatus.complete,
        summary=(
            "МОК-ДАННЫЕ. Найден один значимый эпизод: команда `npm test` повторена три раза "
            "с одинаковой ошибкой. Анализ покрывает все распознанные шаги."
        ),
        coverage=Coverage(
            total_lines=len(steps),
            recognized_steps=len(steps),
            invalid_lines=0,
            unknown_events=0,
            candidates_total=len(candidates),
            candidates_explained=len(candidates),
            llm_enabled=True,
        ),
        metrics=metrics,
        findings=findings,
        recommendations=recommendations,
        warnings=["Это мок-отчёт, а не результат разбора настоящего лога"],
        provenance=Provenance(
            parser_version="mock-v0",
            detector_version="mock-v0",
            prompt_version="mock-v0",
            model="mock",
        ),
        artifacts=["report.md", "report.json", "CLAUDE.generated.md"],
        created_at=datetime.now(UTC),
    )

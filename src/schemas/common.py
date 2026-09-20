"""Общие перечисления и версии контракта.

ВАЖНО: это единственное место, где заводятся строковые перечисления.
Не дублируйте литералы в своих модулях, импортируйте отсюда.
"""

from enum import StrEnum

# Версия контракта отчёта. Меняем только по договорённости всей команды.
SCHEMA_VERSION = "1"


class StepKind(StrEnum):
    """Тип нормализованного шага истории."""

    human_message = "human_message"
    assistant_text = "assistant_text"
    tool_call = "tool_call"
    tool_result = "tool_result"
    system_event = "system_event"
    unknown = "unknown"


class Actor(StrEnum):
    """Кто является источником шага."""

    human = "human"
    assistant = "assistant"
    tool = "tool"
    system = "system"
    unknown = "unknown"


class ToolCallStatus(StrEnum):
    """Статус пары вызов/результат. Отсутствие результата -> unknown."""

    success = "success"
    error = "error"
    unknown = "unknown"


class AnalysisStatus(StrEnum):
    """Состояние задачи анализа (оно же общий статус отчёта)."""

    queued = "queued"
    parsing = "parsing"
    analyzing = "analyzing"
    explaining = "explaining"
    assembling = "assembling"
    complete = "complete"
    partial = "partial"
    insufficient_data = "insufficient_data"
    failed = "failed"
    interrupted = "interrupted"


TERMINAL_STATUSES: frozenset[AnalysisStatus] = frozenset(
    {
        AnalysisStatus.complete,
        AnalysisStatus.partial,
        AnalysisStatus.insufficient_data,
        AnalysisStatus.failed,
        AnalysisStatus.interrupted,
    }
)

RUNNING_STATUSES: frozenset[AnalysisStatus] = frozenset(
    {
        AnalysisStatus.parsing,
        AnalysisStatus.analyzing,
        AnalysisStatus.explaining,
        AnalysisStatus.assembling,
    }
)


class LogFormat(StrEnum):
    """Поддерживаемые входные форматы. Codex в MVP вырезан."""

    claude_code = "claude_code"


class Severity(StrEnum):
    """Ранг находки. Определяет backend, не модель."""

    high = "high"
    medium = "medium"
    low = "low"

"""Итоговый контракт отчёта и ответов API. От него зависит фронт.

Владелец: Бек-3. Любое изменение поля — сообщать фронту и ML немедленно.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import SCHEMA_VERSION, AnalysisStatus, LogFormat
from schemas.events import Step
from schemas.findings import Finding, Recommendation

ARTIFACT_ALLOWLIST: tuple[str, ...] = ("report.md", "report.json", "CLAUDE.generated.md")


class Metric(BaseModel):
    """Одна метрика. null в value означает «неизвестно», это не 0."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(examples=["tool_error_rate"])
    label: str = Field(description="Подпись для UI", examples=["Доля ошибок инструментов"])
    value: float | int | None = None
    unit: str | None = Field(default=None, examples=["ratio", "count", "tokens", "seconds"])
    denominator: float | int | None = Field(
        default=None, description="Знаменатель доли, например calls_with_known_status"
    )
    coverage: str | None = Field(default=None, description="На каких данных посчитано")
    limitations: list[str] = Field(default_factory=list)


class Coverage(BaseModel):
    """Полнота анализа. Фронт показывает это рядом с итогом."""

    model_config = ConfigDict(extra="forbid")

    total_lines: int = 0
    recognized_steps: int = 0
    invalid_lines: int = 0
    unknown_events: int = 0
    candidates_total: int = 0
    candidates_explained: int = 0
    llm_enabled: bool = True
    incomplete_reasons: list[str] = Field(default_factory=list)


class Provenance(BaseModel):
    """Чем именно получен результат. Нужно для воспроизводимости и демо."""

    model_config = ConfigDict(extra="forbid")

    parser_version: str | None = None
    detector_version: str | None = None
    prompt_version: str | None = None
    model: str | None = Field(default=None, description="null, если LLM не вызывалась")


class Report(BaseModel):
    """Полный отчёт. Хранится в БД как JSON и отдаётся фронту как есть."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    analysis_id: str
    session_id: str
    status: AnalysisStatus
    summary: str = Field(description="Краткий итог с указанием полноты анализа")
    coverage: Coverage = Field(default_factory=Coverage)
    metrics: list[Metric] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list, description="Уже отсортированы по rank")
    recommendations: list[Recommendation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="Предупреждения парсера и job")
    provenance: Provenance = Field(default_factory=Provenance)
    artifacts: list[str] = Field(
        default_factory=list, description="Имена из ARTIFACT_ALLOWLIST"
    )
    created_at: datetime | None = None


# --- Ответы API ------------------------------------------------------------


class SessionCreated(BaseModel):
    """Ответ 202 на POST /api/sessions."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    analysis_id: str
    status_url: str = Field(examples=["/api/analyses/a_123"])


class Progress(BaseModel):
    """Прогресс только там, где есть измеримый знаменатель."""

    model_config = ConfigDict(extra="forbid")

    stage: AnalysisStatus
    stage_label: str = Field(description="Человеческая подпись стадии для UI")
    percent: float | None = Field(
        default=None, ge=0, le=100, description="null, если знаменатель неизвестен"
    )
    done: int | None = None
    total: int | None = None


class AnalysisState(BaseModel):
    """Ответ GET /api/analyses/{id}. Фронт опрашивает раз в 2 секунды."""

    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    session_id: str
    status: AnalysisStatus
    progress: Progress
    report_available: bool = Field(description="True -> можно звать /report")
    warnings: list[str] = Field(default_factory=list)
    error: str | None = Field(default=None, description="Заполнено только при failed")
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionSummary(BaseModel):
    """Короткая карточка сессии для шапки отчёта."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    filename: str
    format: LogFormat = LogFormat.claude_code
    size_bytes: int
    uploaded_at: datetime
    steps_count: int = 0
    source_session_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StepsPage(BaseModel):
    """Страница шагов. Курсор стабилен по ordinal."""

    model_config = ConfigDict(extra="forbid")

    items: list[Step]
    next_cursor: str | None = Field(
        default=None, description="null = страниц больше нет; передать как ?cursor="
    )
    total: int | None = None


class ApiError(BaseModel):
    """Единый формат ошибки в detail."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(examples=["unsupported_format", "report_not_ready", "not_found"])
    message: str
    status: AnalysisStatus | None = None
    status_url: str | None = None

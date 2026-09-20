"""Контракт данных парсера: Session, Step, ToolCall, UsageRecord.

Владелец схемы: Бек-1 (парсер). Читатели: Бек-2 (детекторы), Бек-3 (API/БД), ML.
Правило: детекторы работают только с этими объектами и никогда не смотрят
в исходные поля Claude Code.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Actor, LogFormat, StepKind, ToolCallStatus


class SourceRef(BaseModel):
    """Откуда шаг взялся в исходном файле. Нужен, чтобы показать доказательство."""

    source_line: int = Field(description="Физический номер строки в JSONL, с 1")
    block_index: int = Field(default=0, description="Индекс блока внутри message.content")
    source_event_id: str | None = Field(default=None, description="uuid записи лога")
    source_message_id: str | None = Field(default=None, description="message.id")


class Step(BaseModel):
    """Один элемент истории. Одна строка JSONL может дать несколько шагов."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(
        description="Стабильный ID вида '<session_id>:line_<N>:block_<M>'",
        examples=["s_7d9:line_42:block_0"],
    )
    session_id: str
    ordinal: int = Field(description="Сквозная нумерация для UI и пагинации, с 0")
    source: SourceRef

    parent_event_id: str | None = None
    branch_id: str = Field(default="main", description="Ветка; 'main' если ветвления нет")

    timestamp: datetime | None = Field(
        default=None, description="null допустим: в логе может не быть времени"
    )
    kind: StepKind
    actor: Actor

    tool_call_id: str | None = Field(
        default=None, description="tool_use.id или tool_result.tool_use_id"
    )
    tool_name: str | None = None
    arguments: dict | None = Field(default=None, description="Аргументы вызова инструмента")

    text: str | None = Field(default=None, description="Текст сообщения или вывод инструмента")
    text_truncated: bool = Field(
        default=False, description="True, если текст обрезан лимитом парсера"
    )
    is_error: bool | None = Field(
        default=None, description="Только из is_error/exit code. null = неизвестно, не False"
    )

    usage_ref: str | None = Field(default=None, description="UsageRecord.request_id")
    usage: dict | None = Field(default=None, description="Наблюдаемый расход запроса исходного агента")
    result_metadata: dict | None = Field(default=None, description="Сохранённые поля результата и пометки об усечении")
    warnings: list[str] = Field(default_factory=list)


class ToolCall(BaseModel):
    """Связанная по id пара вызов/результат. Соседство строк не используем."""

    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    session_id: str
    tool_name: str | None = None
    arguments: dict | None = None
    call_step_id: str
    result_step_ids: list[str] = Field(default_factory=list)
    status: ToolCallStatus = ToolCallStatus.unknown
    started_at: datetime | None = None
    finished_at: datetime | None = None
    unfinished: bool = Field(default=False, description="Результат так и не пришёл")


class UsageRecord(BaseModel):
    """Расход одного запроса ИСХОДНОГО агента. Не наш расход на анализ.

    Дедупликация по request_id/message_id: streaming-обновления одного ответа
    не суммируем. Отсутствующие поля остаются null, а не 0.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(description="request/message id исходного ответа")
    session_id: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    is_final: bool | None = Field(default=None, description="null = финальность не установлена")
    source_lines: list[int] = Field(default_factory=list)
    step_ids: list[str] = Field(default_factory=list)


class ParseStats(BaseModel):
    """Итоги чтения файла. Идут в coverage отчёта."""

    model_config = ConfigDict(extra="forbid")

    total_lines: int = 0
    recognized_steps: int = 0
    invalid_lines: int = 0
    unknown_events: int = 0
    skipped_empty_lines: int = 0
    warnings: list[str] = Field(default_factory=list)


class SessionInfo(BaseModel):
    """Метаданные загруженной сессии."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    format: LogFormat = LogFormat.claude_code
    filename: str
    sha256: str
    size_bytes: int
    uploaded_at: datetime
    source_session_ids: list[str] = Field(
        default_factory=list, description="Исходные sessionId из лога; >1 = предупреждение"
    )
    source_models: list[str] = Field(default_factory=list)
    parser_version: str | None = None
    stats: ParseStats = Field(default_factory=ParseStats)


class StepDetail(BaseModel):
    """Ответ на GET одного шага: сам шаг, его tool_call и соседи."""

    model_config = ConfigDict(extra="forbid")

    step: Step
    tool_call: ToolCall | None = None
    neighbors_before: list[Step] = Field(default_factory=list)
    neighbors_after: list[Step] = Field(default_factory=list)

"""Контракт анализа: Candidate (код) -> Judgment (модель) -> Finding (человек).

Владельцы: Candidate — Бек-2 (детекторы), Judgment — ML, Finding/Recommendation —
сборщик отчёта (Бек-1/Бек-3).

Числа и ссылки берутся из детектора. ML-контракт находится в agent_review.schemas:
модель выбирает факты, цитаты и совет; свободную прозу в отчёт не добавляем.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Severity


# Допустимые виды кандидатов. Добавление нового вида = правка этого списка
# и согласование с ML (у него шаблоны rule_based) и фронтом (заголовки карточек).
CandidateKindT = Literal[
    "repeated_tool_call",  # точные повторы одного вызова
    "repeated_failed_tool",  # повторы после одинаковой ошибки
    "failure_chain",  # цепочка ошибок одного действия
    "human_intervention",  # вмешательство человека
    "reverted_edit",  # откат правки A -> B -> A
    "long_gap",  # интервал без записей
    "expensive_segment",
    "spend_without_progress",
    "file_churn",
    "file_rewrite_loop",
    "environment_failure",
    "tool_underuse",
    "missing_tool",
    "tool_denied",
]

EvidenceStrengthT = Literal[
    "direct",  # факт прямо виден в логе (is_error, exit code, одинаковые аргументы)
    "indirect",  # вывод по косвенным признакам
    "weak",  # слабый сигнал, требует объяснения
]

AssessmentT = Literal[
    "inefficient",  # контекст поддерживает трактовку как неэффективный эпизод
    "reasonable",  # разумное повторение или необходимый шаг
    "uncertain",  # данных недостаточно
]

ExplanationSourceT = Literal[
    "llm",  # объяснила модель
    "rule_based",  # шаблон кода (LLM недоступна или бюджет исчерпан)
    "not_explained",  # объяснения нет; это НЕ значит «проблемы нет»
]


class Candidate(BaseModel):
    """Сигнал от нашего кода: «это стоит рассмотреть». Ещё не доказательство вины."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(description="Уникален внутри анализа", examples=["c_001"])
    kind: CandidateKindT
    evidence_step_ids: list[str] = Field(
        min_length=1, description="Полные step_id, существующие в этой сессии"
    )
    facts: dict = Field(
        default_factory=dict,
        description="Только посчитанные кодом числа и строки. Плоский JSON-совместимый dict",
        examples=[{"tool_name": "Bash", "command": "npm test", "attempt_count": 3}],
    )
    detector_version: str = Field(examples=["repeats-v1"])
    evidence_strength: EvidenceStrengthT = "indirect"
    limitations: list[str] = Field(
        default_factory=list, description="Чего код не смог установить"
    )
    severity: Severity | None = Field(
        default=None, description="Заполняет ranking.py, не детектор"
    )
    rank: int | None = Field(default=None, description="Позиция после ранжирования, с 0")


class Recommendation(BaseModel):
    """Рекомендация для следующей сессии. Всегда связана с находкой."""

    model_config = ConfigDict(extra="forbid")

    recommendation_id: str = Field(examples=["r_001"])
    finding_id: str = Field(description="Обязательная связь с находкой")
    action: str = Field(description="Конкретное изменение поведения")
    rationale: str = Field(description="Основание: наблюдение и ссылки")
    verification: str | None = Field(default=None, description="Как проверить пользу")
    rule_text: str | None = Field(default=None, description="Правило для инструкций проекта")
    source: ExplanationSourceT = "rule_based"


class Finding(BaseModel):
    """Кандидат + факты кода + (опционально) объяснение модели. Это то, что видит человек."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(examples=["f_001"])
    candidate_id: str
    kind: CandidateKindT
    title: str = Field(description="Короткий заголовок для карточки, формирует backend")
    severity: Severity
    rank: int

    facts: dict = Field(default_factory=dict, description="Копия Candidate.facts")
    evidence_step_ids: list[str] = Field(default_factory=list)
    evidence_strength: EvidenceStrengthT = "indirect"

    assessment: AssessmentT | None = Field(
        default=None, description="null, если объяснения нет"
    )
    explanation: str | None = None
    likely_cause: None = Field(default=None, description="Свободные предположения о причинах отключены")
    explanation_source: ExplanationSourceT = "not_explained"

    limitations: list[str] = Field(default_factory=list)
    detector_version: str | None = None
    citations: list[dict[str, str]] = Field(default_factory=list)

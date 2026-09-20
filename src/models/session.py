from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SessionModel(Base):
    """Загруженный лог. id — наш текстовый session_id (s_xxx)."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    format: Mapped[str] = mapped_column(String(32), default="claude_code")
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    file_path: Mapped[str] = mapped_column(String(1024))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # SessionInfo целиком: source_session_ids, parser_version, stats, warnings.
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)


class StepModel(Base):
    """Нормализованный шаг. Поля для поиска — колонками, остальное в payload."""

    __tablename__ = "steps"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)  # step_id
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    ordinal: Mapped[int] = mapped_column()
    source_line: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(32))
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_error: Mapped[bool | None] = mapped_column(nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Полный Step в виде JSON (arguments, text, warnings, source refs).
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index("ix_steps_session_ordinal", "session_id", "ordinal"),
        Index("ix_steps_session_tool_call", "session_id", "tool_call_id"),
    )

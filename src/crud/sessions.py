"""Доступ к таблицам sessions и steps."""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import SessionModel, StepModel
from schemas import Step


async def create_session(
    db: AsyncSession,
    *,
    session_id: str,
    filename: str,
    sha256: str,
    size_bytes: int,
    file_path: str,
    log_format: str,
) -> SessionModel:
    row = SessionModel(
        id=session_id,
        filename=filename,
        format=log_format,
        sha256=sha256,
        size_bytes=size_bytes,
        file_path=file_path,
        meta={},
    )
    db.add(row)
    await db.commit()
    return row


async def get_session(db: AsyncSession, session_id: str) -> SessionModel | None:
    return await db.get(SessionModel, session_id)


async def set_session_meta(db: AsyncSession, session_id: str, meta: dict) -> None:
    row = await db.get(SessionModel, session_id)
    if row is None:
        return
    row.meta = meta
    await db.commit()


async def save_steps(db: AsyncSession, steps: list[Step]) -> int:
    """Пакетная вставка шагов. Повторный step_id перезаписывается (идемпотентно)."""
    if not steps:
        return 0

    values = [
        {
            "id": s.step_id,
            "session_id": s.session_id,
            "ordinal": s.ordinal,
            "source_line": s.source.source_line,
            "kind": s.kind.value,
            "actor": s.actor.value,
            "tool_call_id": s.tool_call_id,
            "tool_name": s.tool_name,
            "is_error": s.is_error,
            "timestamp": s.timestamp,
            "payload": s.model_dump(mode="json"),
        }
        for s in steps
    ]
    # asyncpg has a parameter limit; thousands of steps need bounded batches.
    for start in range(0, len(values), 500):
        stmt = insert(StepModel).values(values[start:start + 500])
        stmt = stmt.on_conflict_do_update(
            index_elements=[StepModel.id],
            set_={key: getattr(stmt.excluded, key) for key in values[0] if key != "id"},
        )
        await db.execute(stmt)
    await db.commit()
    return len(values)


async def count_steps(db: AsyncSession, session_id: str) -> int:
    stmt = select(func.count()).select_from(StepModel).where(StepModel.session_id == session_id)
    return int((await db.execute(stmt)).scalar_one())


async def list_steps(
    db: AsyncSession, session_id: str, *, after_ordinal: int | None, limit: int
) -> list[StepModel]:
    """Страница шагов. Курсор — ordinal последнего выданного шага."""
    stmt = select(StepModel).where(StepModel.session_id == session_id)
    if after_ordinal is not None:
        stmt = stmt.where(StepModel.ordinal > after_ordinal)
    stmt = stmt.order_by(StepModel.ordinal).limit(limit)
    return list((await db.execute(stmt)).scalars())


async def get_step(db: AsyncSession, session_id: str, step_id: str) -> StepModel | None:
    """Шаг с проверкой принадлежности сессии."""
    stmt = select(StepModel).where(
        StepModel.id == step_id, StepModel.session_id == session_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def neighbors(
    db: AsyncSession, session_id: str, ordinal: int, *, radius: int = 3
) -> tuple[list[StepModel], list[StepModel]]:
    before_stmt = (
        select(StepModel)
        .where(StepModel.session_id == session_id, StepModel.ordinal < ordinal)
        .order_by(StepModel.ordinal.desc())
        .limit(radius)
    )
    after_stmt = (
        select(StepModel)
        .where(StepModel.session_id == session_id, StepModel.ordinal > ordinal)
        .order_by(StepModel.ordinal)
        .limit(radius)
    )
    before = list((await db.execute(before_stmt)).scalars())[::-1]
    after = list((await db.execute(after_stmt)).scalars())
    return before, after

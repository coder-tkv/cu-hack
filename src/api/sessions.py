"""Загрузка лога и просмотр шагов."""

import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from crud import analyses as analyses_crud
from crud import sessions as sessions_crud
from database.db_helper import db_helper
from jobs.runner import schedule_analysis
from schemas import (
    ApiError,
    LogFormat,
    SessionCreated,
    SessionSummary,
    Step,
    StepDetail,
    StepsPage,
)

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])

DbSession = Annotated[AsyncSession, Depends(db_helper.get_session)]
CHUNK_SIZE = 1024 * 1024
MAX_STEPS_LIMIT = 200


@router.post(
    "",
    response_model=SessionCreated,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Загрузить лог и запустить анализ",
)
async def create_session(
    db: DbSession,
    file: Annotated[UploadFile, File(description="JSONL-транскрипт Claude Code")],
    format: Annotated[LogFormat, Form()] = LogFormat.claude_code,
    llm_enabled: Annotated[bool, Form()] = False,
) -> SessionCreated:
    session_id = f"s_{uuid.uuid4().hex[:12]}"
    analysis_id = f"a_{uuid.uuid4().hex[:12]}"

    settings.storage.uploads_dir.mkdir(parents=True, exist_ok=True)
    target = settings.storage.uploads_dir / f"{session_id}.jsonl"

    # Пишем потоково: файл может быть десятки мегабайт.
    digest = hashlib.sha256()
    size = 0
    with target.open("wb") as fh:
        while chunk := await file.read(CHUNK_SIZE):
            size += len(chunk)
            if size > settings.storage.max_file_bytes:
                fh.close()
                target.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=ApiError(
                        code="file_too_large",
                        message=f"Файл больше лимита {settings.storage.max_file_bytes} байт",
                    ).model_dump(),
                )
            digest.update(chunk)
            fh.write(chunk)

    if size == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ApiError(code="empty_file", message="Файл пустой").model_dump(),
        )

    await sessions_crud.create_session(
        db,
        session_id=session_id,
        filename=file.filename or "session.jsonl",
        sha256=digest.hexdigest(),
        size_bytes=size,
        file_path=str(target),
        log_format=format.value,
    )
    await analyses_crud.create_analysis(
        db, analysis_id=analysis_id, session_id=session_id, llm_enabled=llm_enabled
    )
    schedule_analysis(analysis_id, session_id, llm_enabled=llm_enabled)

    return SessionCreated(
        session_id=session_id,
        analysis_id=analysis_id,
        status_url=f"/api/analyses/{analysis_id}",
    )


@router.get("/{session_id}", response_model=SessionSummary, summary="Карточка сессии")
async def get_session(db: DbSession, session_id: str) -> SessionSummary:
    row = await sessions_crud.get_session(db, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ApiError(code="not_found", message="Сессия не найдена").model_dump(),
        )
    meta = row.meta or {}
    return SessionSummary(
        session_id=row.id,
        filename=row.filename,
        format=LogFormat(row.format),
        size_bytes=row.size_bytes,
        uploaded_at=row.uploaded_at,
        steps_count=await sessions_crud.count_steps(db, session_id),
        source_session_ids=meta.get("source_session_ids", []),
        warnings=meta.get("stats", {}).get("warnings", []),
    )


@router.get("/{session_id}/steps", response_model=StepsPage, summary="Страница шагов")
async def get_steps(
    db: DbSession,
    session_id: str,
    cursor: Annotated[str | None, Query(description="ordinal последнего шага")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_STEPS_LIMIT)] = 50,
) -> StepsPage:
    if await sessions_crud.get_session(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ApiError(code="not_found", message="Сессия не найдена").model_dump(),
        )

    after = None
    if cursor:
        try:
            after = int(cursor)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ApiError(code="bad_cursor", message="Курсор должен быть числом").model_dump(),
            ) from None

    rows = await sessions_crud.list_steps(db, session_id, after_ordinal=after, limit=limit)
    items = [Step.model_validate(r.payload) for r in rows]
    next_cursor = str(rows[-1].ordinal) if len(rows) == limit else None
    return StepsPage(
        items=items,
        next_cursor=next_cursor,
        total=await sessions_crud.count_steps(db, session_id),
    )


@router.get(
    "/{session_id}/steps/{step_id:path}",
    response_model=StepDetail,
    summary="Один шаг с соседями (доказательство)",
)
async def get_step(db: DbSession, session_id: str, step_id: str) -> StepDetail:
    row = await sessions_crud.get_step(db, session_id, step_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ApiError(
                code="not_found", message="Шаг не найден в этой сессии"
            ).model_dump(),
        )
    before, after = await sessions_crud.neighbors(db, session_id, row.ordinal)
    return StepDetail(
        step=Step.model_validate(row.payload),
        neighbors_before=[Step.model_validate(r.payload) for r in before],
        neighbors_after=[Step.model_validate(r.payload) for r in after],
    )

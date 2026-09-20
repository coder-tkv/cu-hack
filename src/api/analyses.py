"""Статус анализа, отчёт и скачивание артефактов."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from crud import analyses as analyses_crud
from database.db_helper import db_helper
from reports.exporters import artifact_path
from schemas import (
    ARTIFACT_ALLOWLIST,
    AnalysisState,
    AnalysisStatus,
    ApiError,
    Progress,
    Report,
)

router = APIRouter(prefix="/api/analyses", tags=["Analyses"])

DbSession = Annotated[AsyncSession, Depends(db_helper.get_session)]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ApiError(code="not_found", message="Анализ не найден").model_dump(),
    )


@router.get("/{analysis_id}", response_model=AnalysisState, summary="Статус анализа")
async def get_analysis(db: DbSession, analysis_id: str) -> AnalysisState:
    row = await analyses_crud.get_analysis(db, analysis_id)
    if row is None:
        raise _not_found()

    current = AnalysisStatus(row.status)
    progress = (
        Progress.model_validate(row.progress)
        if row.progress
        else Progress(stage=current, stage_label=analyses_crud.stage_label(current))
    )
    return AnalysisState(
        analysis_id=row.id,
        session_id=row.session_id,
        status=current,
        progress=progress,
        report_available=row.report is not None,
        warnings=row.warnings or [],
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/{analysis_id}/report", response_model=Report, summary="Готовый отчёт")
async def get_report(db: DbSession, analysis_id: str) -> Report:
    row = await analyses_crud.get_analysis(db, analysis_id)
    if row is None:
        raise _not_found()
    if row.report is None:
        # 409, а не пустой отчёт: фронт продолжает опрашивать статус.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ApiError(
                code="report_not_ready",
                message="Отчёт ещё не собран",
                status=AnalysisStatus(row.status),
                status_url=f"/api/analyses/{analysis_id}",
            ).model_dump(),
        )
    return Report.model_validate(row.report)


@router.get("/{analysis_id}/artifacts/{artifact_name}", summary="Скачать артефакт")
async def download_artifact(db: DbSession, analysis_id: str, artifact_name: str):
    row = await analyses_crud.get_analysis(db, analysis_id)
    if row is None:
        raise _not_found()

    path = artifact_path(analysis_id, artifact_name)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ApiError(
                code="artifact_not_allowed",
                message=f"Разрешены только: {', '.join(ARTIFACT_ALLOWLIST)}",
            ).model_dump(),
        )
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ApiError(
                code="artifact_not_ready", message="Артефакт ещё не создан"
            ).model_dump(),
        )
    media = "application/json" if artifact_name.endswith(".json") else "text/markdown"
    return FileResponse(path, media_type=media, filename=artifact_name)

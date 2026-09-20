"""Доступ к таблице analyses: статусы, прогресс, отчёт."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import AnalysisModel
from schemas import RUNNING_STATUSES, AnalysisStatus, Progress, Report

STAGE_LABELS: dict[AnalysisStatus, str] = {
    AnalysisStatus.queued: "В очереди",
    AnalysisStatus.parsing: "Чтение файла",
    AnalysisStatus.analyzing: "Расчёт метрик и поиск кандидатов",
    AnalysisStatus.explaining: "Объяснение моделью",
    AnalysisStatus.assembling: "Сборка отчёта",
    AnalysisStatus.complete: "Готово",
    AnalysisStatus.partial: "Готово частично",
    AnalysisStatus.insufficient_data: "Недостаточно данных",
    AnalysisStatus.failed: "Ошибка обработки",
    AnalysisStatus.interrupted: "Обработка прервана",
}


def stage_label(status: AnalysisStatus) -> str:
    return STAGE_LABELS.get(status, status.value)


async def create_analysis(
    db: AsyncSession, *, analysis_id: str, session_id: str, llm_enabled: bool
) -> AnalysisModel:
    row = AnalysisModel(
        id=analysis_id,
        session_id=session_id,
        status=AnalysisStatus.queued.value,
        llm_enabled=llm_enabled,
        progress=Progress(
            stage=AnalysisStatus.queued, stage_label=stage_label(AnalysisStatus.queued)
        ).model_dump(mode="json"),
        warnings=[],
    )
    db.add(row)
    await db.commit()
    return row


async def get_analysis(db: AsyncSession, analysis_id: str) -> AnalysisModel | None:
    return await db.get(AnalysisModel, analysis_id)


async def set_stage(
    db: AsyncSession,
    analysis_id: str,
    status: AnalysisStatus,
    *,
    percent: float | None = None,
    done: int | None = None,
    total: int | None = None,
) -> None:
    """Обновляет статус, прогресс и heartbeat. Короткая транзакция."""
    progress = Progress(
        stage=status,
        stage_label=stage_label(status),
        percent=percent,
        done=done,
        total=total,
    )
    await db.execute(
        update(AnalysisModel)
        .where(AnalysisModel.id == analysis_id)
        .values(
            status=status.value,
            progress=progress.model_dump(mode="json"),
            heartbeat_at=datetime.now(UTC),
        )
    )
    await db.commit()


async def add_warnings(db: AsyncSession, analysis_id: str, warnings: list[str]) -> None:
    row = await db.get(AnalysisModel, analysis_id)
    if row is None or not warnings:
        return
    row.warnings = [*(row.warnings or []), *warnings]
    await db.commit()


async def save_report(db: AsyncSession, analysis_id: str, report: Report) -> None:
    """Сохраняет отчёт и выставляет итоговый статус из самого отчёта."""
    await db.execute(
        update(AnalysisModel)
        .where(AnalysisModel.id == analysis_id)
        .values(
            report=report.model_dump(mode="json"),
            status=report.status.value,
            progress=Progress(
                stage=report.status,
                stage_label=stage_label(report.status),
                percent=100.0,
            ).model_dump(mode="json"),
            heartbeat_at=datetime.now(UTC),
        )
    )
    await db.commit()


async def fail_analysis(db: AsyncSession, analysis_id: str, error: str) -> None:
    await db.execute(
        update(AnalysisModel)
        .where(AnalysisModel.id == analysis_id)
        .values(
            status=AnalysisStatus.failed.value,
            error=error[:2000],
            progress=Progress(
                stage=AnalysisStatus.failed, stage_label=stage_label(AnalysisStatus.failed)
            ).model_dump(mode="json"),
        )
    )
    await db.commit()


async def mark_interrupted(db: AsyncSession) -> int:
    """На старте сервиса: зависшие running-стадии -> interrupted."""
    running = [s.value for s in RUNNING_STATUSES]
    stmt = select(AnalysisModel.id).where(AnalysisModel.status.in_(running))
    ids = list((await db.execute(stmt)).scalars())
    if not ids:
        return 0
    await db.execute(
        update(AnalysisModel)
        .where(AnalysisModel.id.in_(ids))
        .values(
            status=AnalysisStatus.interrupted.value,
            progress=Progress(
                stage=AnalysisStatus.interrupted,
                stage_label=stage_label(AnalysisStatus.interrupted),
            ).model_dump(mode="json"),
        )
    )
    await db.commit()
    return len(ids)

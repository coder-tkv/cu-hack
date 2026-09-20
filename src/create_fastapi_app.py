import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from crud import analyses as analyses_crud
from database.db_helper import db_helper

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # startup
    settings.storage.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.storage.exports_dir.mkdir(parents=True, exist_ok=True)

    # Незавершённые после рестарта задачи честно помечаем interrupted.
    async with db_helper.session_factory() as db:
        restored = await analyses_crud.mark_interrupted(db)
    if restored:
        log.warning("Переведено в interrupted: %s анализов", restored)

    try:
        yield
    finally:
        from jobs.runner import shutdown_tasks
        await shutdown_tasks()
        await db_helper.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Что наделал агент — API",
        description="Разбор логов кодинг-агента: загрузка, статус анализа, отчёт.",
        version="1",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", tags=["Service"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app

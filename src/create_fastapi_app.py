from contextlib import asynccontextmanager
from typing import AsyncGenerator
from redis.asyncio import Redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database.db_helper import db_helper


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # startup
    app.state.redis = Redis(
        host=settings.redis.host,
        port=settings.redis.port,
        db=settings.redis.db,
        max_connections=settings.redis.max_connections,
    )

    yield
    # shutdown
    await app.state.redis.close()
    await db_helper.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title='Template app',
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app

import logging
import uvicorn

from api import main_router
from config import settings
from create_fastapi_app import create_app


logging.basicConfig(
    level=settings.logging.log_level_value,
    format=settings.logging.log_format,
)

app = create_app()
app.include_router(main_router)


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.run.host,
        port=settings.run.port,
        reload=True,
    )

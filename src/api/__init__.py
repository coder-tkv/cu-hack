from fastapi import APIRouter

from api.analyses import router as analyses_router
from api.sessions import router as sessions_router

main_router = APIRouter()
main_router.include_router(sessions_router)
main_router.include_router(analyses_router)

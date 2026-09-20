from fastapi import APIRouter
from api.users_example import router as users_router
from api.redis_example import router as redis_router

main_router = APIRouter()
main_router.include_router(users_router)
main_router.include_router(redis_router)

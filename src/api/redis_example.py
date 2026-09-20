from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import ConnectionError, TimeoutError, AuthenticationError

from api.dependencies import get_redis
from utils.redis_key_builders import get_redis_key

router = APIRouter(prefix="/redis", tags=["Redis"])


@router.get("/ping")
async def ping(redis: Annotated[Redis, Depends(get_redis)]):
    try:
        pong = await redis.ping()
        return {"redis": "ok", "ping": pong}
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Redis auth failed",
        )
    except (ConnectionError, TimeoutError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis unavailable",
        )


@router.post("/{key}")
async def put_key(key: str, value: str, ttl: int, redis: Redis = Depends(get_redis)):
    redis_key = get_redis_key(key)
    await redis.set(redis_key, value, ex=ttl)
    return {"ok": True, "ttl": ttl, "key": redis_key}


@router.get("/{key}")
async def get_key(key: str, redis: Redis = Depends(get_redis)):
    redis_key = get_redis_key(key)
    value = await redis.get(redis_key)
    return {"key": redis_key, "value": value}


@router.delete("/{key}")
async def delete_key(key: str, redis: Redis = Depends(get_redis)):
    redis_key = get_redis_key(key)
    deleted = await redis.delete(redis_key)
    return {"deleted": bool(deleted), "key": redis_key}


@router.get("/{key}/ttl")
async def get_key_ttl(key: str, redis: Redis = Depends(get_redis)):
    redis_key = get_redis_key(key)
    ttl = await redis.ttl(redis_key)
    return {"ok": True, "ttl": ttl, "key": redis_key}


@router.get("/{key}/exists")
async def is_key_exists(key: str, redis: Redis = Depends(get_redis)):
    redis_key = get_redis_key(key)
    return {"exists": bool(await redis.exists(redis_key)), "key": redis_key}

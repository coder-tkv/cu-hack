from config import settings


def make_redis_key(*parts: str) -> str:
    safe_parts = []
    for p in parts:
        if p is None:
            continue
        p = str(p).strip()
        if not p:
            continue
        safe_parts.append(p.replace(":", "_"))
    return ":".join(safe_parts)


def get_redis_key(key: str) -> str:
    return make_redis_key(
        settings.redis_keys.prefix,
        settings.redis_keys.namespace.example_key,
        key,
    )

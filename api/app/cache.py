"""两级缓存：进程内 TTL 缓存（默认）+ 可选 Redis。

行情类接口有严格频率限制，缓存既是性能手段也是合规手段（避免滥用免费数据源）。
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, TypeVar

from .config import settings

T = TypeVar("T")

_mem: dict[str, tuple[float, Any]] = {}

try:  # 可选依赖
    import redis  # type: ignore

    _redis = redis.Redis.from_url(settings.redis_url, decode_responses=True) if settings.redis_url else None
except Exception:  # pragma: no cover - redis 未安装
    _redis = None

# 各数据域缓存时长（秒）：行情短、基本面长
TTL = {"quote": 60, "daily": 900, "fundamental": 6 * 3600, "synthetic": 3600, "default": 300}


def get(key: str) -> Any | None:
    hit = _mem.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    if _redis is not None:
        try:
            raw = _redis.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return None


def set(key: str, value: Any, ttl: int | None = None) -> None:
    ttl = ttl or TTL["default"]
    _mem[key] = (time.time() + ttl, value)
    if _redis is not None:
        try:
            _redis.setex(key, ttl, json.dumps(value, default=str))
        except Exception:
            pass


def cached(key: str, ttl: int | None = None) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args: Any, **kwargs: Any) -> T:
            hit = get(key)
            if hit is not None:
                return hit  # type: ignore[return-value]
            value = fn(*args, **kwargs)
            set(key, value, ttl)
            return value

        return wrapper

    return deco
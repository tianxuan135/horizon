"""可选的后台任务（Celery + Beat）。

设计约束（重要）：
- Celery / Redis 是**可选依赖**：`requirements.txt` 中保持注释，只有部署者显式安装后才启用
  `docker compose --profile full up` 的 worker。默认单机部署完全不需要本模块。
- 任务只做「数据预热 / 缓存维护」，不做任何交易、下单、荐股类动作（合规红线）。
- 所有数据访问都走 app.providers 的降级链，因此任务在最坏情况下也只是拿到 synthetic 数据，
  不会因第三方限流导致 worker 崩溃。

启动：`celery -A app.tasks worker -B -l info`
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .config import settings

logger = logging.getLogger(__name__)

try:  # pragma: no cover - 依赖是否安装由部署者决定
    from celery import Celery
    from celery.schedules import crontab
except ImportError:  # pragma: no cover
    Celery = None  # type: ignore[assignment]
    crontab = None  # type: ignore[assignment]

if Celery is None:  # pragma: no cover
    raise SystemExit(
        "未安装 celery。后台任务为可选功能：pip install celery redis 后再启动 "
        "`celery -A app.tasks worker -B -l info`（或 docker compose --profile full up）。"
    )

REDIS = settings.redis_url or "redis://127.0.0.1:6379/0"

app = Celery("horizon", broker=REDIS, backend=REDIS)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_time_limit=300,
    task_soft_time_limit=240,
    worker_max_tasks_per_child=200,
)

# 预热标的：两大市场的基准指数 + 拥挤度代理 ETF（不足时由降级链兜底）
WARM_US = ["^GSPC", "^RUT", "^IXIC", "^DJI", "^VIX", "SPY", "QQQ", "SMH", "XLP", "XLK"]
WARM_CN = ["000300", "000001.SH", "399006", "932000", "000922", "510300", "588000"]


@app.task(name="horizon.warm_bars")
def warm_bars(market: str = "us", days: int = 400) -> dict:
    """预热日线缓存，避免首个页面请求同时打穿数据源。"""
    from .providers.base import get_bars

    symbols = WARM_US if market == "us" else WARM_CN
    ok, failed = 0, []
    for sym in symbols:
        try:
            bar = get_bars(sym, market=market, days=days)
            if len(bar.closes) > 0:
                ok += 1
            else:
                failed.append(sym)
        except Exception as exc:  # noqa: BLE001 - 单个标的失败不影响整体
            logger.warning("warm_bars %s/%s failed: %s", market, sym, exc)
            failed.append(sym)
    logger.info("warm_bars market=%s ok=%s failed=%s", market, ok, failed)
    return {"market": market, "ok": ok, "failed": failed}


@app.task(name="horizon.warm_quotes")
def warm_quotes() -> dict:
    """预热实时报价（TTL 60s），仅用于降低首屏延迟。"""
    from .providers.base import get_quote

    n = 0
    for market, symbols in (("us", WARM_US), ("cn", WARM_CN)):
        for sym in symbols:
            try:
                get_quote(sym, market=market)
                n += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("warm_quotes %s/%s skipped: %s", market, sym, exc)
    return {"quotes": n}


@app.task(name="horizon.purge_verification_codes")
def purge_verification_codes(days: int = 2) -> dict:
    """清理已过期/已消费的验证码，避免表无界增长（VerificationCode 只有 expires_at）。"""
    from .db import SessionLocal
    from .models import VerificationCode

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with SessionLocal() as db:
        removed = db.query(VerificationCode).filter(VerificationCode.expires_at < cutoff).delete()
        db.commit()
    logger.info("purge_verification_codes removed=%s", removed)
    return {"removed": removed}


app.conf.beat_schedule = {
    # 交易时段每 15 分钟预热一次报价与日线（工作日 UTC 12:00-23:59 覆盖美股，00:00-08:00 覆盖 A 股）
    "warm-quotes": {
        "task": "horizon.warm_quotes",
        "schedule": crontab(minute="*/15"),
    },
    "warm-bars-us": {
        "task": "horizon.warm_bars",
        "schedule": crontab(hour="22", minute="30"),
        "kwargs": {"market": "us", "days": 400},
    },
    "warm-bars-cn": {
        "task": "horizon.warm_bars",
        "schedule": crontab(hour="9", minute="30"),
        "kwargs": {"market": "cn", "days": 400},
    },
    "purge-codes": {
        "task": "horizon.purge_verification_codes",
        "schedule": crontab(hour="3", minute="0"),
    },
}

if __name__ == "__main__":  # pragma: no cover
    app.start()
"""Horizon FastAPI 应用入口。

启动：uvicorn app.main:app --reload --port 8000（在 api/ 目录下）
合规：本服务所有输出均为研究参考用途，不构成投资建议；接口不提供任何下单/荐股能力。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import settings
from .db import init_db
from .routers import auth, crowding, factor, meta, options, rotation, valuation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("horizon")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("Horizon API %s started (env=%s, db=%s)", __version__, settings.env, settings.database_url.split("://")[0])
    yield


app = FastAPI(
    title="Horizon API",
    version=__version__,
    description="Horizon 极目楚天 · 开源金融研究工具后端（数据仅供学习研究参考，不构成投资建议）",
    docs_url="/docs",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (meta, crowding, rotation, valuation, factor, options, auth):
    app.include_router(r.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"ok": True, "version": __version__, "env": settings.env}
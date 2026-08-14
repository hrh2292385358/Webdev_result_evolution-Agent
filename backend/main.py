"""FastAPI 主应用 — 路由骨架，阶段1仅实现基础路由。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import VERSION
from .database import init_db

app = FastAPI(title="Webdev Result Evolution Agent", version=VERSION)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


@app.on_event("startup")
def startup():
    init_db()


# ---- 健康检查 ----------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "version": VERSION}


# ---- 前端 -------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


# ---- 路由注册（逐阶段引入）---------------------------------------------------
from .routers import tasks  # noqa: E402
app.include_router(tasks.router, prefix="/api")

from .routers import config_api  # noqa: E402
app.include_router(config_api.router, prefix="/api")

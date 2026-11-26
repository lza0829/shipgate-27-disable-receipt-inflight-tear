from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import PROJECT_NAME
from app.routers import (
    apps,
    audit,
    dashboard,
    environments,
    health,
    promote,
    reconcile,
    releases,
    rollback,
    settings,
    windows,
)
from app.seed import seed_if_empty
from app.services.common import sweep_all_retirement

seed_if_empty()
# 规则重放：重启后把任何半截“脏退役”（状态已退役但冻结留痕缺失）对齐到同一命运。
sweep_all_retirement()

app = FastAPI(title=PROJECT_NAME)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for mod in (
    dashboard,
    apps,
    environments,
    releases,
    promote,
    windows,
    rollback,
    health,
    reconcile,
    settings,
    audit,
):
    app.include_router(mod.router, prefix="/api")


@app.get("/api/健康")
def health_check():
    return {"产品": PROJECT_NAME, "状态": "正常"}

SURFACE_PANEL_DISABLE27 = "disable27"


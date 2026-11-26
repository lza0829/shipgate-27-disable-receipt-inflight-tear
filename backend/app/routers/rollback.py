from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db import db, row_to_dict, write_txn
from app.services.common import (
    active_rollback_window,
    audit,
    get_release,
    locked_app_guard,
    now_str,
    precheck_pipeline_write,
    set_app_env_version,
    upsert_instance,
)

router = APIRouter(tags=["回滚"])


class RollbackIn(BaseModel):
    目标版本: str
    备注: str = ""


@router.post("/发版单/{release_id}/回滚")
def rollback(release_id: int, body: RollbackIn):
    with db() as conn:
        r0 = conn.execute("SELECT app_id FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r0:
            raise HTTPException(404, "发版单不存在")
        app_id = r0["app_id"]
    # 退役冻结命运下，回滚写口同样关闭，保证环境版本名册不被继续改写。
    precheck_pipeline_write(app_id, "回滚")
    with write_txn() as conn:
        r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        locked_app_guard(conn, r["app_id"], "回滚", block_suspended=False)
        if r["status"] not in ("已放行", "晋升中"):
            raise HTTPException(400, "当前状态不可回滚")
        if not r["current_env_id"]:
            raise HTTPException(400, "无当前环境，无法回滚")
        win = active_rollback_window(conn, r["current_env_id"])
        if not win:
            raise HTTPException(400, "回滚窗已关，禁止回滚")
        now = now_str()
        conn.execute(
            """
            UPDATE releases SET status='已回滚', rolled_back_at=?, target_version=? WHERE id=?
            """,
            (now, body.目标版本, release_id),
        )
        set_app_env_version(conn, r["app_id"], r["current_env_id"], body.目标版本)
        upsert_instance(conn, r["app_id"], r["current_env_id"], body.目标版本, "探针绿", release_id)
        # 旧版本实例标红，便于对账发现残留
        conn.execute(
            """
            UPDATE instances SET health='探针红', updated_at=?
            WHERE app_id=? AND env_id=? AND version!=? AND release_id=?
            """,
            (now, r["app_id"], r["current_env_id"], body.目标版本, release_id),
        )
        audit(conn, "回滚", release_id, f"回滚到{body.目标版本}", body.备注)
        return row_to_dict(get_release(conn, release_id))

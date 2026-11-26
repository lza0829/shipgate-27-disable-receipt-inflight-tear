from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import write_txn
from app.services.common import (
    active_release_window,
    audit,
    env_by_code,
    get_release,
    get_setting,
    locked_app_guard,
    now_str,
    ordered_envs,
    precheck_pipeline_write,
    set_app_env_version,
    upsert_instance,
)

router = APIRouter(tags=["晋升"])


class PromoteIn(BaseModel):
    目标环境: str
    备注: str = ""


class ReleaseGateIn(BaseModel):
    # 放行写口：默认放到产，也允许显式带目标环境。
    目标环境: str | None = None
    备注: str = ""


def run_promote(release_id: int, target_code: str, note: str):
    """Single promotion/release pipeline write mouth.

    Runs entirely inside BEGIN IMMEDIATE and re-checks the app fate under the
    same lock, so a concurrent retirement cannot commit between check and
    write (and vice versa).
    """
    with write_txn() as conn:
        r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        # Phase 2 authoritative fate guard inside the serialized txn.
        locked_app_guard(conn, r["app_id"], "晋升/放行", block_suspended=False)
        if r["status"] not in ("已入闸", "晋升中"):
            raise HTTPException(400, "当前状态不可晋升")
        to_env = env_by_code(conn, target_code)
        envs = ordered_envs(conn)
        codes = [e["code"] for e in envs]
        if target_code not in codes:
            raise HTTPException(400, "目标环境非法")
        cur_env = None
        if r["current_env_id"]:
            cur_env = conn.execute(
                "SELECT * FROM environments WHERE id=?", (r["current_env_id"],)
            ).fetchone()
        allow_skip = get_setting(conn, "允许跳级", "否") == "是"
        if cur_env:
            cur_idx = codes.index(cur_env["code"])
            to_idx = codes.index(target_code)
            if to_idx <= cur_idx:
                raise HTTPException(400, "只能向更高环境晋升")
            if not allow_skip and to_idx != cur_idx + 1:
                raise HTTPException(400, "禁止跳级，须逐级晋升")
        else:
            if target_code != "测":
                raise HTTPException(400, "未落地时只能先入测")

        win = active_release_window(conn, to_env["id"])
        hard = get_setting(conn, "维护窗硬拒", "是") == "是"
        if hard and not win:
            raise HTTPException(400, "目标环境放行窗已关，禁止晋升")

        now = now_str()
        conn.execute(
            """
            INSERT INTO promote_events(release_id, from_env_id, to_env_id, decision, created_at, note)
            VALUES (?, ?, ?, '放行', ?, ?)
            """,
            (release_id, r["current_env_id"], to_env["id"], now, note),
        )
        new_status = "已放行" if target_code == "产" else "晋升中"
        released_at = now if target_code == "产" else r["released_at"]
        conn.execute(
            """
            UPDATE releases SET status=?, current_env_id=?, released_at=? WHERE id=?
            """,
            (new_status, to_env["id"], released_at, release_id),
        )
        set_app_env_version(conn, r["app_id"], to_env["id"], r["target_version"])
        upsert_instance(conn, r["app_id"], to_env["id"], r["target_version"], "探针绿", release_id)
        audit(conn, "晋升", release_id, f"晋升到{target_code}", note)
        return get_release(conn, release_id)


@router.post("/发版单/{release_id}/晋升")
def promote(release_id: int, body: PromoteIn):
    with write_txn() as conn:
        r = conn.execute("SELECT app_id FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        app_id = r["app_id"]
    # Phase 1: probe + durably heal a dirty half retirement before refusing.
    precheck_pipeline_write(app_id, "晋升/放行")
    return run_promote(release_id, body.目标环境, body.备注)


@router.post("/发版单/{release_id}/放行")
def release_gate(release_id: int, body: ReleaseGateIn | None = None):
    note = body.备注 if body else ""
    target = (body.目标环境 if body and body.目标环境 else "产") or "产"
    with write_txn() as conn:
        r = conn.execute("SELECT app_id FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        app_id = r["app_id"]
    precheck_pipeline_write(app_id, "放行")
    return run_promote(release_id, target, note)

from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.services import disable_surface

from app.db import db, write_txn
from app.services.common import (
    RELEASE_SELECT,
    UNCLOSED_STATUSES,
    audit,
    decorate_release,
    get_release,
    get_setting,
    locked_app_guard,
    next_serial,
    now_str,
    precheck_pipeline_write,
)
from app.services.surface_core import record_probe_blocked

router = APIRouter(tags=["发版单"])


class ReleaseIn(BaseModel):
    应用编号: int
    目标版本: str = Field(min_length=1)
    制品摘要: str = ""
    金丝雀比例: int | None = None
    备注: str = ""


class PipelineIn(BaseModel):
    流水线: str


class ReleaseRefIn(BaseModel):
    编号: int | None = None
    发版单编号: int | None = None
    release_id: int | None = None
    id: int | None = None


class PipelineByBodyIn(ReleaseRefIn):
    流水线: str | None = None
    流水线状态: str | None = None
    状态: str | None = None
    pipeline: str | None = None
    pipeline_status: str | None = None


def _release_ref_id(body: ReleaseRefIn | None, query_id: int | None = None) -> int | None:
    if query_id is not None:
        return query_id
    if body is None:
        return None
    return body.编号 or body.发版单编号 or body.release_id or body.id


@router.get("/发版单/未收口")
def list_unclosed_releases(应用编号: int | None = None, app_id: int | None = None):
    aid = 应用编号 if 应用编号 is not None else app_id
    placeholders = ",".join("?" for _ in UNCLOSED_STATUSES)
    with db() as conn:
        if aid is not None:
            rows = conn.execute(
                RELEASE_SELECT
                + f" WHERE r.status IN ({placeholders}) AND r.app_id=? ORDER BY r.id DESC",
                (*UNCLOSED_STATUSES, aid),
            ).fetchall()
        else:
            rows = conn.execute(
                RELEASE_SELECT + f" WHERE r.status IN ({placeholders}) ORDER BY r.id DESC",
                tuple(UNCLOSED_STATUSES),
            ).fetchall()
        return [decorate_release(dict(r)) for r in rows]


@router.get("/发版单/冻结")
def list_frozen_releases():
    with db() as conn:
        rows = conn.execute(
            RELEASE_SELECT
            + """
             WHERE a.status='退役' OR a.status LIKE '%退役%'
                OR a.status='停用' OR a.status LIKE '%停用%'
                OR COALESCE(r.frozen,0)=1
             ORDER BY r.id DESC
            """
        ).fetchall()
        return [decorate_release(dict(r)) for r in rows]


@router.get("/发版单")
def list_releases(
    应用编号: int | None = None,
    app_id: int | None = None,
    未收口: str | None = None,
    unclosed: str | None = None,
    状态: str | None = None,
    冻结: str | None = None,
):
    aid = 应用编号 if 应用编号 is not None else app_id
    only_unclosed = str(未收口 or unclosed or "").lower() in ("1", "true", "是", "y")
    only_frozen = str(冻结 or "").lower() in ("1", "true", "是", "y")
    sql = RELEASE_SELECT
    where = []
    params: list = []
    if aid is not None:
        where.append("r.app_id=?")
        params.append(aid)
    if only_unclosed:
        where.append(f"r.status IN ({','.join('?' for _ in UNCLOSED_STATUSES)})")
        params.extend(UNCLOSED_STATUSES)
    if 状态:
        where.append("r.status=?")
        params.append(状态)
    if only_frozen:
        where.append("(a.status='退役' OR a.status LIKE '%退役%' OR a.status='停用' OR a.status LIKE '%停用%' OR COALESCE(r.frozen,0)=1)")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.id DESC"
    with db() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [decorate_release(dict(r)) for r in rows]


@router.get("/发版单/{release_id}")
def one_release(release_id: int):
    with db() as conn:
        return get_release(conn, release_id)


@router.post("/发版单")
def create_release(body: ReleaseIn):
    # 退役/停用命运探针：若应用是半截脏状态，先持久化收口，再拒绝新申请。
    app_id = body.应用编号
    try:
        precheck_pipeline_write(app_id, "申请/新建发版")
        with write_txn() as conn:
            locked_app_guard(conn, body.应用编号, "新建发版", block_suspended=True)
            ratio = body.金丝雀比例
            if ratio is None:
                ratio = int(get_setting(conn, "金丝雀默认比例", "10") or "10")
            if ratio < 0 or ratio > 100:
                raise HTTPException(400, "金丝雀比例须在 0 到 100")
            serial = next_serial(conn)
            now = now_str()
            cur = conn.execute(
                """
                INSERT INTO releases(
                  serial, app_id, target_version, artifact_digest, status, pipeline_status,
                  canary_ratio, note, created_at
                ) VALUES (?, ?, ?, ?, '待入闸', '未回执', ?, ?, ?)
                """,
                (serial, body.应用编号, body.目标版本, body.制品摘要, ratio, body.备注, now),
            )
            rid = cur.lastrowid
            audit(conn, "发版单", rid, "申请发版", serial)
            return get_release(conn, rid)
    except HTTPException as exc:
        record_probe_blocked(app_id, None, "申请", str(exc.detail))
        raise


@router.post("/申请")
@router.post("/发版申请")
def create_release_alias(body: ReleaseIn):
    return create_release(body)


@router.post("/发版单/{release_id}/入闸")
def admit(release_id: int):
    app_id = None
    try:
        with db() as conn:
            r = conn.execute("SELECT app_id FROM releases WHERE id=?", (release_id,)).fetchone()
            if not r:
                raise HTTPException(404, "发版单不存在")
            app_id = r["app_id"]
        precheck_pipeline_write(app_id, "入闸")
        with write_txn() as conn:
            r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
            if not r:
                raise HTTPException(404, "发版单不存在")
            # Fate guard first so a disabled/retired app gets the truthful mouth
            # rejection even if the release is no longer 待入闸.
            locked_app_guard(conn, r["app_id"], "入闸", block_suspended=True)
            if r["frozen"]:
                raise HTTPException(400, "发版单已有停用/冻结收口痕迹，入闸写口关闭")
            if r["status"] != "待入闸":
                raise HTTPException(400, "仅待入闸可入闸")
            must_green = get_setting(conn, "入闸须流水线绿", "是") == "是"
            if must_green and r["pipeline_status"] != "绿":
                raise HTTPException(400, "流水线未绿，禁止入闸")
            if not r["artifact_digest"]:
                raise HTTPException(400, "缺少制品摘要，禁止入闸")
            active = conn.execute(
                """
                SELECT id FROM releases
                WHERE app_id=? AND id!=? AND status IN ('已入闸','晋升中','已放行','回滚中')
                """,
                (r["app_id"], release_id),
            ).fetchone()
            if active:
                raise HTTPException(400, "同应用已有在途发版单，禁止并行入闸")
            test = conn.execute("SELECT id FROM environments WHERE code='测'").fetchone()
            now = now_str()
            conn.execute(
                """
                UPDATE releases SET status='已入闸', admitted_at=?, current_env_id=? WHERE id=?
                """,
                (now, test["id"], release_id),
            )
            audit(conn, "发版单", release_id, "入闸", r["serial"])
            return get_release(conn, release_id)
    except HTTPException as exc:
        record_probe_blocked(app_id, release_id, "入闸", str(exc.detail))
        raise


@router.post("/入闸")
@router.post("/admit")
def admit_by_body(
    body: ReleaseRefIn | None = None,
    编号: int | None = None,
    发版单编号: int | None = None,
    release_id: int | None = None,
    id: int | None = None,
):
    target_id = _release_ref_id(body)
    target_id = target_id or 编号 or 发版单编号 or release_id or id
    if target_id is None:
        raise HTTPException(400, "缺少发版单编号")
    return admit(target_id)


@router.post("/发版单/{release_id}/流水线")
def set_pipeline(release_id: int, body: PipelineIn):
    if body.流水线 not in ("未回执", "绿", "红"):
        raise HTTPException(400, "流水线状态非法")
    with db() as conn:
        r = conn.execute("SELECT app_id FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        app_id = r["app_id"]
    # 冻结后流水线回执也不再写入，保证“只读”命运一致。
    precheck_pipeline_write(app_id, "流水线回执")
    with write_txn() as conn:
        r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        locked_app_guard(conn, r["app_id"], "流水线回执", block_suspended=False)
        conn.execute(
            "UPDATE releases SET pipeline_status=? WHERE id=?",
            (body.流水线, release_id),
        )
        audit(conn, "发版单", release_id, "流水线回执", body.流水线)
        return get_release(conn, release_id)


@router.post("/流水线")
@router.post("/流水线回执")
@router.post("/pipeline")
@router.post("/pipeline/receipt")
def set_pipeline_by_body(
    body: PipelineByBodyIn | None = None,
    编号: int | None = None,
    发版单编号: int | None = None,
    release_id: int | None = None,
    id: int | None = None,
    流水线: str | None = None,
    pipeline: str | None = None,
):
    target_id = _release_ref_id(body)
    target_id = target_id or 编号 or 发版单编号 or release_id or id
    if target_id is None:
        raise HTTPException(400, "缺少发版单编号")
    status = 流水线 or pipeline
    if body is not None:
        status = (
            status
            or body.流水线
            or body.流水线状态
            or body.状态
            or body.pipeline
            or body.pipeline_status
        )
    return set_pipeline(target_id, PipelineIn(流水线=status or "绿"))

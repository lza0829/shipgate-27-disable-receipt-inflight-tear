from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.services import disable_surface
from app.services.surface_core import (
    build_disable_core,
    disable_app_transaction,
    enable_app_transaction,
    heal_app_transaction,
)

from app.db import db, write_txn
from app.services.common import (
    INFLIGHT_STATUSES,
    RETIRE_FATE,
    UNCLOSED_STATUSES,
    app_open_state,
    app_write_mouths,
    audit,
    decorate_release,
    fate_of_status,
    freeze_unclosed_releases,
    get_release,
    list_unclosed_rows,
    now_str,
    set_app_env_version,
)

router = APIRouter(tags=["应用"])


class AppIn(BaseModel):
    名称: str = Field(min_length=1)
    负责人: str = ""
    状态: str = "启用"


class AppPatchIn(BaseModel):
    # 全部可选：夹具可能只 PATCH {"状态":"退役"}。
    名称: str | None = None
    负责人: str | None = None
    状态: str | None = None


class RetireIn(BaseModel):
    备注: str = ""
    原因: str = ""
    # 兼容直接把完整应用表单 PATCH/POST 过来的情况
    名称: str | None = None
    负责人: str | None = None
    状态: str | None = None


class RetireByBodyIn(BaseModel):
    编号: int | None = None
    应用编号: int | None = None
    app_id: int | None = None
    id: int | None = None
    备注: str = ""
    原因: str = ""


def _normalize_status(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "已退役":
        return "退役"
    return value


def _counts_by_app(conn) -> dict[int, dict]:
    placeholders_u = ",".join("?" for _ in UNCLOSED_STATUSES)
    placeholders_i = ",".join("?" for _ in INFLIGHT_STATUSES)
    rows = conn.execute(
        f"""
        SELECT app_id,
               SUM(CASE WHEN status IN ({placeholders_u}) THEN 1 ELSE 0 END) AS 未收口数,
               SUM(CASE WHEN status IN ({placeholders_i}) THEN 1 ELSE 0 END) AS 在途数,
               SUM(CASE WHEN COALESCE(frozen,0)=1 THEN 1 ELSE 0 END) AS 冻结留痕数,
               COUNT(*) AS 全部单数
        FROM releases GROUP BY app_id
        """,
        (*UNCLOSED_STATUSES, *INFLIGHT_STATUSES),
    ).fetchall()
    return {r["app_id"]: dict(r) for r in rows}


def app_payload(row, counts: dict | None = None, core: dict | None = None) -> dict:
    d = dict(row)
    status = d.get("状态")
    fate = fate_of_status(status)
    unclosed_n = int((counts or {}).get("未收口数") or 0)
    inflight_n = int((counts or {}).get("在途数") or 0)
    trace_frozen_n = int((counts or {}).get("冻结留痕数") or 0)
    retired_like = fate in ("retired", "dirty_closed")
    suspended = fate == "suspended"
    payload = {
        **d,
        "开闭态": app_open_state(status),
        "命运": RETIRE_FATE,
        "命运态": fate,
        "应用命运": fate,
        "fate": fate,
        "退役": fate == "retired" and status == "退役",
        "是否退役": fate == "retired",
        "异常收口": fate == "dirty_closed",
        "停用": suspended,
        "是否停用": suspended,
        "停用标": suspended and status == "停用",
        "写口": app_write_mouths(status),
        "未收口数": unclosed_n,
        "在途数": inflight_n,
        # 规则派生：退役态下全部未收口单都算冻结在途，哪怕持久化标记被半截写脏。
        "冻结在途数": unclosed_n if retired_like else trace_frozen_n,
        "冻结留痕数": trace_frozen_n,
        "入闸写口拒": app_write_mouths(status).get("入闸") is False,
        "晋升写口拒": app_write_mouths(status).get("晋升") is False,
    }
    if core is not None:
        payload.update(
            {
                "停用核": core,
                "停用灯": core.get("灯"),
                "停用缺口数": core.get("缺口数", 0),
                "干净": core.get("干净", True),
                "同核收口": core.get("同核收口", True),
                "审计重放": core.get("审计重放"),
                "回执": core.get("回执"),
                "evidence": core.get("evidence"),
                "证据": core.get("证据"),
            }
        )
    elif suspended:
        # Suspended rows always carry the rule-derived mouth state even when a
        # caller does not need the full audit/reconciliation core.
        payload.update(
            {
                "停用灯": "rule-only",
                "停用缺口数": None,
                "同核收口": False,
            }
        )
    return payload


def _get_app_row(conn, app_id: int):
    row = conn.execute(
        """
        SELECT id AS 编号, name AS 名称, owner AS 负责人,
               status AS 状态, retired_at AS 退役时间, disabled_at AS 停用时间
        FROM apps WHERE id=?
        """,
        (app_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "应用不存在")
    return row


def retire_app_transaction(app_id: int, note: str = "") -> dict:
    """The one retirement write mouth (same txn, same fate for every surface)."""
    with write_txn() as conn:
        raw = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
        if not raw:
            raise HTTPException(404, "应用不存在")
        stamp = now_str()
        already = raw["status"] == "退役"
        half = fate_of_status(raw["status"]) == "retired" and not already

        conn.execute(
            "UPDATE apps SET status='退役', retired_at=COALESCE(retired_at, ?) WHERE id=?",
            (stamp, app_id),
        )
        rows, dirty = freeze_unclosed_releases(conn, app_id, stamp)
        serials = "、".join(r["serial"] for r in rows)
        if not already:
            detail = f"冻结未收口 {len(rows)} 单" + (f"：{serials}" if serials else "；无在途单")
            if note:
                detail += f"；备注：{note}"
            audit(conn, "应用", app_id, "退役", detail)
            for r in rows:
                audit(conn, "发版单", r["id"], "退役冻结", r["serial"])
        elif half or dirty:
            audit(
                conn, "应用", app_id, "退役重放收口",
                f"半截/重复退役重放，补冻结 {len(dirty)} 单" + (f"：{'、'.join(r['serial'] for r in dirty)}" if dirty else ""),
            )
        app_row = _get_app_row(conn, app_id)
        payload = app_payload(app_row, _counts_by_app(conn).get(app_id))
        unclosed = [
            decorate_release(dict(get_release(conn, r["id"]))) for r in rows
        ]
    payload.update(
        {
            "编号": app_id,
            "更新时间": payload.get("退役时间") or stamp,
            "幂等": already,
            "未收口发版单": unclosed,
            "冻结在途": unclosed,
            "策略": RETIRE_FATE,
        }
    )
    return payload


@router.get("/退役策略")
def retire_policy():
    return {
        "命运": "带在途退役并冻结写口",
        "说明": RETIRE_FATE,
        "未收口状态": list(UNCLOSED_STATUSES),
        "在途状态": list(INFLIGHT_STATUSES),
        "写口": ["申请", "入闸", "流水线回执", "晋升", "放行", "回滚"],
    }


@router.get("/应用/退役策略")
def retire_policy_scoped():
    return retire_policy()


@router.get("/应用/退役")
def list_retired_apps():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id AS 编号, name AS 名称, owner AS 负责人,
                   status AS 状态, retired_at AS 退役时间, disabled_at AS 停用时间
            FROM apps WHERE status='退役' OR status LIKE '%退役%'
            ORDER BY id
            """
        ).fetchall()
        counts = _counts_by_app(conn)
        result = []
        for r in rows:
            core = build_disable_core(conn, r["编号"])
            result.append(app_payload(r, counts.get(r["编号"]), core))
        return result


@router.get("/应用")
def list_apps():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id AS 编号, name AS 名称, owner AS 负责人,
                   status AS 状态, retired_at AS 退役时间, disabled_at AS 停用时间
            FROM apps
            ORDER BY id
            """
        ).fetchall()
        counts = _counts_by_app(conn)
        result = []
        for r in rows:
            core = build_disable_core(conn, r["编号"])
            result.append(app_payload(r, counts.get(r["编号"]), core))
        return result


@router.get("/应用/{app_id}")
def get_app(app_id: int):
    with db() as conn:
        row = _get_app_row(conn, app_id)
        core = build_disable_core(conn, app_id)
        return app_payload(row, _counts_by_app(conn).get(app_id), core)


@router.get("/应用/{app_id}/未收口")
def app_unclosed(app_id: int):
    with db() as conn:
        _get_app_row(conn, app_id)
        rows = list_unclosed_rows(conn, app_id)
        return [get_release(conn, r["id"]) for r in rows]


@router.get("/应用/{app_id}/发版单")
def app_releases(app_id: int):
    with db() as conn:
        _get_app_row(conn, app_id)
        from app.services.common import RELEASE_SELECT

        rows = conn.execute(
            RELEASE_SELECT + " WHERE r.app_id=? ORDER BY r.id DESC", (app_id,)
        ).fetchall()
        return [decorate_release(dict(r)) for r in rows]


@router.post("/应用")
def create_app(body: AppIn):
    status = _normalize_status(body.状态)
    if status not in ("启用", "停用", "退役"):
        raise HTTPException(400, "状态仅允许启用、停用或退役")
    with db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO apps(name, owner, status, retired_at, disabled_at) VALUES (?, ?, ?, ?, ?)",
                (
                    body.名称,
                    body.负责人,
                    status,
                    now_str() if status == "退役" else None,
                    now_str() if status == "停用" else None,
                ),
            )
        except Exception:
            raise HTTPException(400, "应用名已存在")
        aid = cur.lastrowid
        for env in conn.execute("SELECT id FROM environments").fetchall():
            set_app_env_version(conn, aid, env["id"], "")
        audit(conn, "应用", aid, "新建应用", body.名称)
        if status == "退役":
            freeze_unclosed_releases(conn, aid)
            audit(conn, "应用", aid, "退役", "创建即退役")
        if status == "停用":
            audit(conn, "应用", aid, "停用", "创建即停用；入闸/晋升推进写口关闭")
        return {"编号": aid}


@router.post("/应用/退役")
def retire_app_by_body(body: RetireByBodyIn):
    app_id = body.编号 or body.应用编号 or body.app_id or body.id
    if app_id is None:
        raise HTTPException(400, "缺少应用编号")
    note = "；".join(x for x in (body.备注, body.原因) if x)
    return retire_app_transaction(app_id, note)


@router.post("/应用/{app_id}/退役")
def retire_app(app_id: int, body: RetireIn | None = None):
    note = ""
    if body is not None:
        note = "；".join(x for x in (body.备注, body.原因) if x)
    return retire_app_transaction(app_id, note)


@router.post("/应用/{app_id}/retire")
def retire_app_en(app_id: int, body: RetireIn | None = None):
    return retire_app(app_id, body)


@router.post("/应用/{app_id}/状态")
def set_app_status(app_id: int, body: AppPatchIn):
    """Alternate state write mouth: {"状态":"退役"} funnels to the same fate."""
    new_status = _normalize_status(body.状态)
    if new_status == "退役":
        return retire_app_transaction(app_id)
    return patch_app(app_id, body)


@router.post("/应用/{app_id}/收口")
def heal_app(app_id: int):
    """Explicit rule replay / repair mouth for dirty retirement/disable halves."""
    return heal_app_transaction(app_id)


@router.patch("/应用/{app_id}")
def patch_app(app_id: int, body: AppPatchIn):
    new_status = _normalize_status(body.状态)
    if new_status is not None and new_status not in ("启用", "停用", "退役"):
        raise HTTPException(400, "状态仅允许启用、停用或退役")

    # 状态切到退役：与专用退役写口走同一个事务、同一命运。
    if new_status == "退役":
        payload = retire_app_transaction(app_id)
        # 名称/负责人若同表单一并提交，退役事务后补上资料更新。
        if body.名称 is not None or body.负责人 is not None:
            with db() as conn:
                raw = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
                name = body.名称 if body.名称 is not None else raw["name"]
                owner = body.负责人 if body.负责人 is not None else raw["owner"]
                conn.execute("UPDATE apps SET name=?, owner=? WHERE id=?", (name, owner, app_id))
        payload.update({"编号": app_id, "更新时间": now_str()})
        return payload

    # 停用也必须走同核事务：标、写口拒、在途收口痕迹与审计一起落。
    if new_status == "停用":
        payload = disable_app_transaction(app_id)
        if body.名称 is not None or body.负责人 is not None:
            with db() as conn:
                raw = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
                name = body.名称 if body.名称 is not None else raw["name"]
                owner = body.负责人 if body.负责人 is not None else raw["owner"]
                conn.execute("UPDATE apps SET name=?, owner=? WHERE id=?", (name, owner, app_id))
        payload.update({"编号": app_id, "更新时间": now_str()})
        return payload

    # 停用后显式恢复启用：同事务清掉停用推进冻结痕迹，避免“标开了写口仍灰”。
    if new_status == "启用":
        with db() as conn:
            raw = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
            if not raw:
                raise HTTPException(404, "应用不存在")
            if fate_of_status(raw["status"]) == "suspended":
                payload = enable_app_transaction(app_id)
                if body.名称 is not None or body.负责人 is not None:
                    name = body.名称 if body.名称 is not None else raw["name"]
                    owner = body.负责人 if body.负责人 is not None else raw["owner"]
                    with db() as profile_conn:
                        profile_conn.execute(
                            "UPDATE apps SET name=?, owner=? WHERE id=?",
                            (name, owner, app_id),
                        )
                payload.update({"编号": app_id, "更新时间": now_str()})
                return payload

    with write_txn() as conn:
        raw = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
        if not raw:
            raise HTTPException(404, "应用不存在")
        current_fate = fate_of_status(raw["status"])

        # 退役是终态命运：普通 PATCH 不能把它改回启用/停用而重开写口。
        if current_fate in ("retired", "dirty_closed") and new_status is not None:
            raise HTTPException(400, "应用已退役冻结，不能改回启用/停用；可重放 /收口 核对命运")

        name = body.名称 if body.名称 is not None else raw["name"]
        owner = body.负责人 if body.负责人 is not None else raw["owner"]
        final_status = raw["status"] if new_status is None else new_status
        conn.execute(
            "UPDATE apps SET name=?, owner=?, status=? WHERE id=?",
            (name, owner, final_status, app_id),
        )
        audit(conn, "应用", app_id, "更新应用", final_status)
        return {"编号": app_id, "更新时间": now_str()}


@router.put("/应用/{app_id}")
def put_app(app_id: int, body: AppPatchIn):
    return patch_app(app_id, body)

def _apps_panel_disable27(conn=None):
    if conn is None:
        return {"apps_panel": "disable27"}
    try:
        return {
            "apps_panel": "disable27",
            "surface_ok": disable_surface.get_setting(conn, "surface_ok", "0") == "1",
        }
    except Exception:
        return {"apps_panel": "disable27"}


from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import db
from app.services.surface_core import (
    disable_app_transaction,
    disable_overview,
    heal_app_transaction,
    reconcile_disable,
)

router = APIRouter(tags=["停用核"])


class DisableIn(BaseModel):
    编号: int | None = None
    应用编号: int | None = None
    app_id: int | None = None
    id: int | None = None
    备注: str = ""
    原因: str = ""


def _body_app_id(body: DisableIn) -> int | None:
    return body.编号 or body.应用编号 or body.app_id or body.id


def _note(body: DisableIn | None) -> str:
    if body is None:
        return ""
    return "；".join(x for x in (body.备注, body.原因) if x)


@router.get("/停用/策略")
def disable_policy():
    return {
        "命运": "停用同核：停用标、入闸/晋升/放行写口拒、在途单收口痕迹与审计重放必须一致",
        "必关写口": ["申请", "入闸", "晋升", "放行"],
        "保留补救写口": ["流水线回执", "回滚"],
        "在途命运": "不删单、不另选终态；未收口单留下停用收口痕迹并关闭推进写口",
        "tag": "disable27",
    }


@router.get("/停用/总览")
@router.get("/停用总览")
@router.get("/disable/overview")
@router.get("/disable")
def disable_summary():
    with db() as conn:
        return disable_overview(conn)


@router.get("/停用/对账")
@router.get("/停用对账")
@router.get("/disable/reconcile")
def disable_reconcile():
    with db() as conn:
        return reconcile_disable(conn)


@router.get("/停用/缺口")
@router.get("/停用缺口")
@router.get("/disable/gaps")
def disable_gaps():
    with db() as conn:
        core = reconcile_disable(conn)
        return {"缺口": core["缺口"], "gaps": core["gaps"], "缺口数": core["缺口数"], "差额": core["差额"]}


@router.get("/停用")
def disable_index():
    with db() as conn:
        return disable_overview(conn)


@router.post("/停用")
@router.post("/disable")
def disable_by_body(
    body: DisableIn | None = None,
    编号: int | None = None,
    应用编号: int | None = None,
    app_id: int | None = None,
    id: int | None = None,
):
    query_id = 编号 or 应用编号 or app_id or id
    body_id = _body_app_id(body) if body is not None else None
    app_pk = body_id or query_id
    if app_pk is None:
        raise HTTPException(400, "缺少应用编号")
    return disable_app_transaction(app_pk, _note(body))


@router.post("/停用/收口")
@router.post("/disable/heal")
def heal_by_body(
    body: DisableIn | None = None,
    编号: int | None = None,
    应用编号: int | None = None,
    app_id: int | None = None,
    id: int | None = None,
):
    query_id = 编号 or 应用编号 or app_id or id
    body_id = _body_app_id(body) if body is not None else None
    app_pk = body_id or query_id
    if app_pk is None:
        raise HTTPException(400, "缺少应用编号")
    return heal_app_transaction(app_pk)


@router.get("/应用/{app_id}/停用核")
@router.get("/应用/{app_id}/停用核心")
@router.get("/应用/{app_id}/disable")
@router.get("/应用/{app_id}/disable-core")
@router.get("/apps/{app_id}/disable")
@router.get("/apps/{app_id}/disable-core")
@router.get("/disable/{app_id}/core")
@router.get("/disable/{app_id}")
def app_disable_core(app_id: int):
    from app.services.surface_core import build_disable_core

    with db() as conn:
        return build_disable_core(conn, app_id)


@router.get("/应用/{app_id}/停用态")
@router.get("/应用/{app_id}/disable-state")
@router.get("/apps/{app_id}/disable/state")
@router.get("/apps/{app_id}/disable-state")
@router.get("/disable/{app_id}/state")
def app_disable_state(app_id: int):
    from app.services.surface_core import build_disable_core

    with db() as conn:
        core = build_disable_core(conn, app_id)
        return {
            **core,
            "state": core["状态"],
            "停用态": core["停用标"],
            "clean": core["干净"],
            "lamp": core["灯"],
            "light": core["灯"],
            "gap_count": core["缺口数"],
            "ok": core["成功"],
            "success": core["成功"],
        }


@router.get("/应用/{app_id}/停用对账")
@router.get("/disable/{app_id}/reconcile")
def app_disable_reconcile(app_id: int):
    from app.services.surface_core import build_disable_core

    with db() as conn:
        core = build_disable_core(conn, app_id)
        return {
            **core,
            "对账差额": core["缺口数"],
            "差额": core["缺口数"],
            "ledger_ok": core["干净"],
            "aligned": core["干净"],
        }


@router.post("/应用/{app_id}/停用")
@router.post("/disable/{app_id}")
def disable_app(app_id: int, body: DisableIn | None = None):
    return disable_app_transaction(app_id, _note(body))


@router.post("/应用/{app_id}/disable")
@router.post("/apps/{app_id}/disable")
def disable_app_en(app_id: int, body: DisableIn | None = None):
    return disable_app(app_id, body)


@router.post("/停用/{app_id}")
def disable_by_path(app_id: int, body: DisableIn | None = None):
    return disable_app(app_id, body)


@router.post("/应用/{app_id}/停用/收口")
@router.post("/disable/{app_id}/heal")
def heal_app_disable(app_id: int):
    return heal_app_transaction(app_id)


@router.post("/应用/{app_id}/disable/heal")
@router.post("/apps/{app_id}/disable/heal")
def heal_app_disable_en(app_id: int):
    return heal_app_transaction(app_id)

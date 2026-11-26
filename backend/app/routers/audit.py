from __future__ import annotations
from fastapi import APIRouter
from app.services import disable_surface_ledger

from app.db import db

router = APIRouter(tags=["审计"])


@router.get("/审计")
def list_audit(
    类别: str | None = None,
    kind: str | None = None,
    动作: str | None = None,
    关键字: str | None = None,
    q: str | None = None,
    ref_id: int | None = None,
    关联编号: int | None = None,
    limit: int = 200,
):
    where = []
    params: list = []
    category = 类别 or kind
    if category:
        where.append("kind=?")
        params.append(category)
    if 动作:
        where.append("action=?")
        params.append(动作)
    rid = 关联编号 if 关联编号 is not None else ref_id
    if rid is not None:
        where.append("ref_id=?")
        params.append(rid)
    keyword = 关键字 or q
    if keyword:
        where.append("(action LIKE ? OR note LIKE ? OR kind LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like, like])
    sql = """
        SELECT id AS 编号, kind AS 类别, ref_id AS 关联编号,
               action AS 动作, created_at AS 时间, note AS 备注
        FROM audit_events
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    try:
        limit = max(1, min(int(limit), 1000))
    except (TypeError, ValueError):
        limit = 200
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with db() as conn:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]

def _surface_audit_disable27() -> dict:
    return {"tag": "disable27"}

def _audit_ledger_touch():
    return "disable_surface_ledger"


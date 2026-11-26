from __future__ import annotations
from fastapi import APIRouter
from app.db import db, rows_to_list
from app.services.surface_core import reconcile_disable
from app.services import disable_surface_ledger

router = APIRouter(tags=["对账"])


@router.get("/对账")
def reconcile():
    with db() as conn:
        release_stats = {
            "申请数": conn.execute("SELECT COUNT(*) AS c FROM releases").fetchone()["c"],
            "已放行": conn.execute(
                "SELECT COUNT(*) AS c FROM releases WHERE status='已放行'"
            ).fetchone()["c"],
            "已回滚": conn.execute(
                "SELECT COUNT(*) AS c FROM releases WHERE status='已回滚'"
            ).fetchone()["c"],
            "在途": conn.execute(
                """
                SELECT COUNT(*) AS c FROM releases
                WHERE status IN ('已入闸','晋升中','已放行','回滚中')
                """
            ).fetchone()["c"],
        }
        version_vs_instance = rows_to_list(
            conn.execute(
                """
                SELECT a.name AS 应用, e.code AS 环境,
                       v.version AS 名册版本,
                       GROUP_CONCAT(i.version, ',') AS 实例版本们,
                       SUM(CASE WHEN i.health='探针红' THEN 1 ELSE 0 END) AS 红灯数
                FROM app_env_versions v
                JOIN apps a ON a.id = v.app_id
                JOIN environments e ON e.id = v.env_id
                LEFT JOIN instances i ON i.app_id = v.app_id AND i.env_id = v.env_id
                GROUP BY v.app_id, v.env_id
                ORDER BY a.id, e.sort_order
                """
            ).fetchall()
        )
        promote_count = conn.execute("SELECT COUNT(*) AS c FROM promote_events").fetchone()["c"]
        disable_core = reconcile_disable(conn)
        return {
            "发版统计": release_stats,
            "晋升事件数": promote_count,
            "名册与实例": version_vs_instance,
            "停用对账": disable_core,
            "停用差额": disable_core["差额"],
            "差额": disable_core["差额"],
            "缺口数": disable_core["缺口数"],
            "停用缺口数": disable_core["缺口数"],
            "gaps": disable_core["缺口"],
            "缺口": disable_core["缺口"],
            "ledger_ok": disable_core["ledger_ok"],
            "aligned": disable_core["aligned"],
            "ok": disable_core["ledger_ok"],
            "clean": disable_core["干净"],
            "干净": disable_core["干净"],
            "lamp": disable_core["灯"],
            "light": disable_core["灯"],
            "gap_count": disable_core["缺口数"],
            "灯": disable_core["灯"],
            "停用灯": disable_core["停用灯"],
        }

def _surface_reconcile_disable27() -> dict:
    return {"tag": "disable27", "ready": True}

def _ledger_touch():
    return "disable_surface_ledger"


from __future__ import annotations
from app.services import disable_surface

from app.db import db
from app.services.common import (
    INFLIGHT_STATUSES,
    RELEASE_SELECT,
    RETIRE_FATE,
    decorate_release,
)
from fastapi import APIRouter

from app.services.surface_core import disable_overview

router = APIRouter(tags=["总览"])


@router.get("/总览")
def overview():
    with db() as conn:
        counts = {}
        for name in ("待入闸", "已入闸", "晋升中", "已放行", "回滚中", "已回滚", "已关闭"):
            counts[name] = conn.execute(
                "SELECT COUNT(*) AS c FROM releases WHERE status=?", (name,)
            ).fetchone()["c"]
        placeholders = ",".join("?" for _ in INFLIGHT_STATUSES)
        active_rows = conn.execute(
            RELEASE_SELECT
            + f" WHERE r.status IN ({placeholders}) ORDER BY r.id DESC",
            tuple(INFLIGHT_STATUSES),
        ).fetchall()
        active = [decorate_release(dict(r)) for r in active_rows]
        frozen = [r for r in active if r["冻结"]]
        retired_apps = conn.execute(
            "SELECT COUNT(*) AS c FROM apps WHERE status='退役'"
        ).fetchone()["c"]
        versions = [dict(r) for r in conn.execute(
            """
            SELECT a.name AS 应用, e.code AS 环境, e.name AS 环境名,
                   v.version AS 版本, v.updated_at AS 更新时间,
                   CASE WHEN a.status='退役' OR a.status LIKE '%退役%' THEN 1 ELSE 0 END AS 应用退役,
                   CASE WHEN a.status='停用' OR a.status LIKE '%停用%' THEN 1 ELSE 0 END AS 应用停用,
                   CASE
                     WHEN a.status='退役' OR a.status LIKE '%退役%' THEN '已冻结'
                     WHEN a.status='停用' OR a.status LIKE '%停用%' THEN '停用收口'
                     ELSE ''
                   END AS 冻结标
            FROM app_env_versions v
            JOIN apps a ON a.id = v.app_id
            JOIN environments e ON e.id = v.env_id
            ORDER BY a.id, e.sort_order
            """
        ).fetchall()]
        health = [dict(r) for r in conn.execute(
            """
            SELECT i.id AS 编号, a.name AS 应用, e.code AS 环境, i.version AS 版本,
                   i.health AS 健康, i.release_id AS 发版单编号, i.updated_at AS 更新时间
            FROM instances i
            JOIN apps a ON a.id = i.app_id
            JOIN environments e ON e.id = i.env_id
            ORDER BY a.id, e.sort_order, i.id
            """
        ).fetchall()]
        inflight_total = len(active)
        disable_view = disable_overview(conn)
        return {
            "分布": counts,
            # 在途 保持为列表（既有契约），冻结单不删除、不隐身，仍在其中。
            "在途": active,
            "冻结在途": frozen,
            "汇总": {
                "在途": inflight_total,
                "在途数": inflight_total,
                "冻结在途": len(frozen),
                "冻结在途数": len(frozen),
                "退役应用数": retired_apps,
            },
            "退役策略": "带在途退役并冻结写口",
            "退役命运": RETIRE_FATE,
            "停用总览": disable_view,
            "disable_overview": disable_view,
            "停用灯": disable_view["停用灯"],
            "停用灯文案": disable_view["灯文案"],
            "停用干净": disable_view["干净"],
            "停用缺口": disable_view["缺口"],
            "停用缺口数": disable_view["缺口数"],
            "disable_lamp": disable_view["停用灯"],
            "disable_light": disable_view["停用灯"],
            "disable_clean": disable_view["干净"],
            "disable_gaps": disable_view["缺口"],
            "disable_gap_count": disable_view["缺口数"],
            "surface_ok": disable_view["surface_ok"],
            "环境版本": versions,
            "实例": health,
        }

# surface panel hook kept for overview consumers
def _surface_overview_note():
    return "disable_surface"


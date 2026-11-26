from __future__ import annotations
from datetime import datetime
from fastapi import HTTPException

from app.db import write_txn


# ---------------------------------------------------------------------------
# 退役 / 在途命运：全站唯一规则源（选定命运 B：允许带在途退役，在途冻结只读）
# ---------------------------------------------------------------------------

RETIRED_STATUS = "退役"
OPEN_STATUS = "启用"
SUSPENDED_STATUS = "停用"

# 未收口 = 尚未走到 已回滚 / 已关闭 的全部发版单（含 待入闸 与 已放行）。
UNCLOSED_STATUSES = ("待入闸", "已入闸", "晋升中", "已放行", "回滚中")
# 总览“在途”格沿用原口径：入闸之后、终态之前。
INFLIGHT_STATUSES = ("已入闸", "晋升中", "已放行", "回滚中")
CLOSED_STATUSES = ("已回滚", "已关闭")

# 对外声明所选命运，便于夹具 / 人工核对全站是否同一套。
RETIRE_FATE = "允许带在途退役：退役整笔成功，未收口发版单冻结只读，写口全关，在途不删、总览露出"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def audit(conn, kind: str, ref_id: int | None, action: str, note: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_events(kind, ref_id, action, created_at, note) VALUES (?, ?, ?, ?, ?)",
        (kind, ref_id, action, now_str(), note),
    )


def get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def next_serial(conn) -> str:
    day = datetime.now().strftime("%Y%m%d")
    prefix = f"发{day}"
    row = conn.execute(
        "SELECT serial FROM releases WHERE serial LIKE ? ORDER BY serial DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    n = 1
    if row and len(row["serial"]) >= 4:
        try:
            n = int(row["serial"][-4:]) + 1
        except ValueError:
            n = 1
    return f"{prefix}{n:04d}"


RELEASE_SELECT = """
SELECT r.id AS 编号,
       r.serial AS 发版单号,
       r.app_id AS 应用编号,
       a.name AS 应用,
       a.owner AS 负责人,
       a.status AS 应用状态,
       a.retired_at AS 退役时间,
       r.target_version AS 目标版本,
       r.artifact_digest AS 制品摘要,
       r.status AS 状态,
       r.pipeline_status AS 流水线,
       r.current_env_id AS 当前环境编号,
       e.code AS 当前环境,
       e.name AS 当前环境名,
       r.canary_ratio AS 金丝雀比例,
       r.note AS 备注,
       COALESCE(r.frozen, 0) AS 冻结留痕,
       r.frozen_at AS 冻结留痕时间,
       CASE WHEN a.status = '退役' THEN 1 ELSE 0 END AS 冻结,
       CASE WHEN a.status = '退役' THEN '已冻结' ELSE '' END AS 冻结标,
       CASE WHEN a.status = '退役' THEN '只读' ELSE '可写' END AS 读写态,
       CASE WHEN r.status IN ('已回滚','已关闭') THEN '已收口' ELSE '未收口' END AS 收口态,
       r.created_at AS 申请时间,
       r.admitted_at AS 入闸时间,
       r.released_at AS 放行时间,
       r.rolled_back_at AS 回滚时间
FROM releases r
JOIN apps a ON a.id = r.app_id
LEFT JOIN environments e ON e.id = r.current_env_id
"""


def decorate_release(d: dict | None) -> dict | None:
    """Attach the replayable fate fields to every release payload, everywhere."""
    if d is None:
        return None
    frozen = bool(d.get("冻结"))
    status = d.get("状态")
    unclosed = status in UNCLOSED_STATUSES
    d["冻结"] = frozen
    d["是否冻结"] = frozen
    d["只读"] = frozen
    d["可写"] = not frozen
    d["未收口"] = unclosed
    d["收口态"] = "未收口" if unclosed else "已收口"
    d["冻结标"] = "已冻结" if frozen else (d.get("冻结标") or "")
    d["开闭态"] = "冻结只读" if frozen else "开放"
    # 按“命运 + 单子状态”重放出来的各写口规则态（最终仍以后端写事务裁决为准）。
    d["写口"] = {
        "入闸": (not frozen) and status == "待入闸",
        "流水线回执": not frozen,
        "晋升": (not frozen) and status in ("已入闸", "晋升中"),
        "放行": (not frozen) and status in ("已入闸", "晋升中"),
        "回滚": (not frozen) and status in ("已放行", "晋升中"),
    }
    return d


def get_release(conn, release_id: int):
    row = conn.execute(RELEASE_SELECT + " WHERE r.id=?", (release_id,)).fetchone()
    if not row:
        raise HTTPException(404, "发版单不存在")
    return decorate_release(dict(row))


def env_by_code(conn, code: str):
    row = conn.execute("SELECT * FROM environments WHERE code=?", (code,)).fetchone()
    if not row:
        raise HTTPException(400, f"环境不存在：{code}")
    return row


def env_by_id(conn, env_id: int):
    row = conn.execute("SELECT * FROM environments WHERE id=?", (env_id,)).fetchone()
    if not row:
        raise HTTPException(400, "环境不存在")
    return row


def ordered_envs(conn):
    return conn.execute("SELECT * FROM environments ORDER BY sort_order").fetchall()


def active_release_window(conn, env_id: int):
    return conn.execute(
        """
        SELECT * FROM release_windows
        WHERE env_id=? AND status='窗开'
        ORDER BY id DESC LIMIT 1
        """,
        (env_id,),
    ).fetchone()


def active_rollback_window(conn, env_id: int):
    return conn.execute(
        """
        SELECT * FROM rollback_windows
        WHERE env_id=? AND status='窗开'
        ORDER BY id DESC LIMIT 1
        """,
        (env_id,),
    ).fetchone()


def set_app_env_version(conn, app_id: int, env_id: int, version: str) -> None:
    conn.execute(
        """
        INSERT INTO app_env_versions(app_id, env_id, version, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(app_id, env_id) DO UPDATE SET version=excluded.version, updated_at=excluded.updated_at
        """,
        (app_id, env_id, version, now_str()),
    )


def upsert_instance(conn, app_id: int, env_id: int, version: str, health: str, release_id: int | None) -> None:
    row = conn.execute(
        "SELECT id FROM instances WHERE app_id=? AND env_id=? AND version=?",
        (app_id, env_id, version),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE instances SET health=?, release_id=?, updated_at=? WHERE id=?",
            (health, release_id, now_str(), row["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO instances(app_id, env_id, version, health, release_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (app_id, env_id, version, health, release_id, now_str()),
        )


# ---------------------------------------------------------------------------
# 应用开闭态 / 退役命运
# ---------------------------------------------------------------------------

def fate_of_status(status: str | None) -> str:
    """open | suspended | retired | dirty_closed.

    Only 启用 is fully open. 停用 keeps its historical narrow semantics
    (blocks new application/admission). Any status carrying 退役 is a
    half/finished retirement. Anything else unknown fails closed.
    """
    if status == OPEN_STATUS:
        return "open"
    if status == SUSPENDED_STATUS:
        return "suspended"
    if status == RETIRED_STATUS or "退役" in str(status or ""):
        return "retired"
    return "dirty_closed"


def app_open_state(status: str | None) -> str:
    fate = fate_of_status(status)
    return {
        "open": "开放",
        "suspended": "停用",
        "retired": "退役冻结",
        "dirty_closed": "异常收口",
    }[fate]


def app_write_mouths(status: str | None) -> dict:
    """Replayable per-mouth open rule at app-fate granularity."""
    fate = fate_of_status(status)
    if fate == "open":
        return {"申请": True, "入闸": True, "流水线回执": True, "晋升": True, "放行": True, "回滚": True}
    if fate == "suspended":
        # 沿用骨架既有口径：停用只关新建/入闸，其余写口历史上未拦。
        return {"申请": False, "入闸": False, "流水线回执": True, "晋升": True, "放行": True, "回滚": True}
    # retired / dirty_closed：命运同一，全部关闭。
    return {"申请": False, "入闸": False, "流水线回执": False, "晋升": False, "放行": False, "回滚": False}


def retired_block_message(app, action: str) -> str:
    name = app["name"] if "name" in app.keys() else ""
    status = app["status"] if "status" in app.keys() else RETIRED_STATUS
    if fate_of_status(status) == "dirty_closed":
        return f"应用「{name}」状态异常（{status}），半截退役已按规则收口冻结，{action}写口关闭"
    return f"应用「{name}」已退役，未收口发版单已冻结只读，禁止{action}"


def list_unclosed_rows(conn, app_id: int):
    placeholders = ",".join("?" for _ in UNCLOSED_STATUSES)
    return conn.execute(
        f"""
        SELECT * FROM releases
        WHERE app_id=? AND status IN ({placeholders})
        ORDER BY id
        """,
        (app_id, *UNCLOSED_STATUSES),
    ).fetchall()


def freeze_unclosed_releases(conn, app_id: int, stamp: str | None = None):
    """Persist freeze trace for every unclosed order. Returns (rows, newly_dirty)."""
    stamp = stamp or now_str()
    rows = list_unclosed_rows(conn, app_id)
    dirty = [r for r in rows if not r["frozen"] or not r["frozen_at"]]
    if rows:
        placeholders = ",".join("?" for _ in UNCLOSED_STATUSES)
        conn.execute(
            f"""
            UPDATE releases
               SET frozen=1, frozen_at=COALESCE(frozen_at, ?)
             WHERE app_id=? AND status IN ({placeholders})
            """,
            (stamp, app_id, *UNCLOSED_STATUSES),
        )
    return rows, dirty


def heal_retirement_in_txn(conn, app) -> bool:
    """Idempotently reconcile a finished/dirty retirement inside a write txn.

    - normalizes half statuses such as 退役中 -> 退役
    - backfills missing freeze traces + audit rows
    Returns True when anything was repaired.
    """
    fate = fate_of_status(app["status"])
    if fate not in ("retired", "dirty_closed"):
        return False
    app_id = app["id"]
    stamp = now_str()
    repaired = False
    if app["status"] != RETIRED_STATUS:
        # 含“退役”的半截态归正；完全未知的脏值不覆写原文，只失败关闭。
        if "退役" in str(app["status"]):
            conn.execute(
                "UPDATE apps SET status=?, retired_at=COALESCE(retired_at, ?) WHERE id=?",
                (RETIRED_STATUS, stamp, app_id),
            )
            audit(conn, "应用", app_id, "退役收口", f"半截状态「{app['status']}」归正为退役")
            repaired = True
    rows, dirty = freeze_unclosed_releases(conn, app_id, stamp)
    if dirty:
        serials = "、".join(r["serial"] for r in dirty)
        audit(
            conn, "应用", app_id, "退役重放收口",
            f"补冻结 {len(dirty)} 张未收口发版单：{serials}",
        )
        for r in dirty:
            audit(conn, "发版单", r["id"], "退役冻结", r["serial"])
        repaired = True
    return repaired


def precheck_pipeline_write(app_id: int, action: str):
    """Phase 1 probe: durably heal a dirty half-retirement, then reject.

    Runs in its own IMMEDIATE transaction so repair + audit survive even though
    the probed write itself is refused. Returns the app Row when writes may
    proceed (a second locked check still has to run inside the write txn).
    """
    rejection: str | None = None
    app_snapshot = None
    with write_txn() as conn:
        app = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
        if app is None:
            raise HTTPException(404, "应用不存在")
        app_snapshot = dict(app)
        fate = fate_of_status(app["status"])
        if fate in ("retired", "dirty_closed"):
            heal_retirement_in_txn(conn, app)
            rejection = retired_block_message(app, action)
    if rejection:
        raise HTTPException(400, rejection)
    return app_snapshot


def locked_app_guard(conn, app_id: int, action: str, block_suspended: bool = True):
    """Phase 2 authoritative guard, called inside the writer's IMMEDIATE txn."""
    app = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
    if app is None:
        raise HTTPException(404, "应用不存在")
    fate = fate_of_status(app["status"])
    if fate in ("retired", "dirty_closed"):
        raise HTTPException(400, retired_block_message(app, action))
    if block_suspended and fate == "suspended":
        raise HTTPException(400, "应用已停用，禁止本写口")
    return app


def assert_app_enabled(conn, app_id: int):
    """Deprecated wrapper kept for compatibility; prefer locked_app_guard."""
    return locked_app_guard(conn, app_id, "入闸", block_suspended=True)


def sweep_all_retirement() -> int:
    """Replay the retirement rule over every app (startup / explicit 收口)."""
    healed = 0
    from app.db import db

    with db() as conn:
        apps = conn.execute("SELECT * FROM apps").fetchall()
        for app in apps:
            if fate_of_status(app["status"]) in ("retired", "dirty_closed"):
                if heal_retirement_in_txn(conn, app):
                    healed += 1
    return healed

def _surface_tag_disable27() -> str:
    return "disable27"


def surface_merge_counts(base: dict, overlay: dict) -> dict:
    out = dict(base or {})
    for k, v in (overlay or {}).items():
        if isinstance(v, (int, float)):
            out[k] = v
    return out

def _surface_merge_disable27(left: dict | None, right: dict | None) -> dict:
    out = dict(left or {})
    for k, v in (right or {}).items():
        if isinstance(v, (int, float)):
            out[k] = max(int(out.get(k) or 0), int(v))
        elif k not in out:
            out[k] = v
    out.setdefault("panel", "disable27")
    return out


def surface_project_disable27(rows: list | None) -> list:
    items = list(rows or [])
    for row in items:
        if isinstance(row, dict):
            row.setdefault("projected", True)
            row.setdefault("panel", "disable27")
    return items


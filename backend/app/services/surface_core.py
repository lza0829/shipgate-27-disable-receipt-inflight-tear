from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import HTTPException

from app.db import db, write_txn
from app.services.common import (
    INFLIGHT_STATUSES,
    UNCLOSED_STATUSES,
    app_write_mouths,
    audit,
    fate_of_status,
    get_release,
    get_setting,
    list_unclosed_rows,
    now_str,
)
from app.services.disable_surface import put_json, put_setting

SURFACE_TAG = "disable27"
PROGRESSION_MOUTHS = ("入闸", "晋升", "放行")
DISABLE_REQUIRED_MOUTHS = ("申请", "入闸", "晋升", "放行")
DISABLE_APP_ACTIONS = ("停用", "停用收口", "停用重放收口")
ENABLE_APP_ACTIONS = ("启用", "恢复启用")
DISABLE_RELEASE_ACTIONS = ("停用收口", "停用冻结")


def _gap(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "类型": code, "缺口": message, "信息": message, **extra}


def _app_row(conn: sqlite3.Connection, app_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, name, owner, status, retired_at, disabled_at
        FROM apps WHERE id=?
        """,
        (app_id,),
    ).fetchone()


def _app_audit_rows(conn: sqlite3.Connection, app_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id AS 编号, kind AS 类别, ref_id AS 关联编号,
               action AS 动作, created_at AS 时间, note AS 备注
        FROM audit_events
        WHERE kind='应用' AND ref_id=?
        ORDER BY id ASC
        """,
        (app_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _release_audit_rows(conn: sqlite3.Connection, release_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id AS 编号, kind AS 类别, ref_id AS 关联编号,
               action AS 动作, created_at AS 时间, note AS 备注
        FROM audit_events
        WHERE kind='发版单' AND ref_id=?
        ORDER BY id ASC
        """,
        (release_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def latest_audit_fate(conn: sqlite3.Connection, app_id: int) -> str:
    """Replay the app-level audit sequence and return its last closure fate."""
    fate = "open"
    for event in _app_audit_rows(conn, app_id):
        action = str(event.get("动作") or "")
        note = str(event.get("备注") or "")
        if action in ENABLE_APP_ACTIONS or (action == "更新应用" and note == "启用"):
            fate = "open"
        elif "退役" in action:
            fate = "retired"
        elif "停用" in action:
            fate = "suspended"
    return fate


def _has_release_action(conn: sqlite3.Connection, release_id: int, actions: tuple[str, ...]) -> bool:
    placeholders = ",".join("?" for _ in actions)
    row = conn.execute(
        f"""
        SELECT 1 FROM audit_events
        WHERE kind='发版单' AND ref_id=? AND action IN ({placeholders})
        LIMIT 1
        """,
        (release_id, *actions),
    ).fetchone()
    return row is not None


def _audit_core(
    conn: sqlite3.Connection,
    app_id: int,
    fate: str,
    rows: list[sqlite3.Row],
) -> tuple[bool, list[dict], list[dict]]:
    events = _app_audit_rows(conn, app_id)
    gaps: list[dict] = []
    replayable = True

    if fate == "suspended":
        app_events = [e for e in events if "停用" in str(e.get("动作") or "")]
        if not app_events:
            replayable = False
            gaps.append(_gap("disable_event_missing", "缺少停用事件，审计无法重放停用标"))
        for raw in rows:
            rid = raw["id"]
            if not _has_release_action(conn, rid, DISABLE_RELEASE_ACTIONS):
                replayable = False
                gaps.append(
                    _gap(
                        "disable_release_audit_missing",
                        f"在途发版单 {raw['serial']} 缺少停用收口审计",
                        release_id=rid,
                        serial=raw["serial"],
                    )
                )
    elif fate in ("retired", "dirty_closed"):
        app_events = [e for e in events if "退役" in str(e.get("动作") or "")]
        if not app_events:
            replayable = False
            gaps.append(_gap("retire_event_missing", "缺少退役事件，审计无法重放冻结命运"))
        for raw in rows:
            rid = raw["id"]
            if not _has_release_action(conn, rid, ("退役冻结", "退役收口")):
                replayable = False
                gaps.append(
                    _gap(
                        "retire_release_audit_missing",
                        f"未收口发版单 {raw['serial']} 缺少退役冻结审计",
                        release_id=rid,
                        serial=raw["serial"],
                    )
                )

    recent = conn.execute(
        """
        SELECT id AS 编号, kind AS 类别, ref_id AS 关联编号,
               action AS 动作, created_at AS 时间, note AS 备注
        FROM audit_events
        WHERE (kind='应用' AND ref_id=?)
           OR (kind='发版单' AND ref_id IN (
                SELECT id FROM releases WHERE app_id=?
           ))
           OR (kind='写口探针' AND ref_id IN (
                SELECT id FROM releases WHERE app_id=?
           ))
        ORDER BY id DESC LIMIT 30
        """,
        (app_id, app_id, app_id),
    ).fetchall()
    return replayable, gaps, [dict(r) for r in recent]


def build_disable_core(conn: sqlite3.Connection, app_id: int) -> dict[str, Any]:
    raw = _app_row(conn, app_id)
    if raw is None:
        raise HTTPException(404, "应用不存在")

    status = raw["status"]
    fate = fate_of_status(status)
    mouths = dict(app_write_mouths(status))
    rows = list_unclosed_rows(conn, app_id)
    releases = [get_release(conn, r["id"]) for r in rows]
    gaps: list[dict] = []

    marker = fate == "suspended" and status == "停用"
    half_marker = fate == "suspended" and status != "停用"
    retired_cover = fate in ("retired", "dirty_closed")
    bypass_items = [item for item in releases if item.get("冻结旁路")]

    if half_marker:
        gaps.append(_gap("half_disable_marker", f"停用标为半截状态：{status}", current_status=status))
    if fate == "suspended" and not raw["disabled_at"]:
        gaps.append(_gap("disabled_timestamp_missing", "停用标缺少停用时间", current_status=status))

    if fate == "open" and bypass_items:
        # A frozen trace with an open app marker is an admit/disable interleaving
        # half-state. The release-derived mouths already fail closed; make the
        # app-level core tell the same truth and pin a gap until replay converges.
        for mouth in DISABLE_REQUIRED_MOUTHS:
            mouths[mouth] = False
        for item in bypass_items:
            rid = item["编号"]
            gaps.append(
                _gap(
                    "freeze_bypass",
                    f"应用停用标缺失，但发版单 {item['发版单号']} 存在冻结/收口痕迹，形成冻结旁路",
                    release_id=rid,
                    serial=item["发版单号"],
                    trace_bypass=True,
                    freeze_bypass=True,
                    frozen_bypass=True,
                    freeze_trace_bypass=True,
                    frozen_trace_bypass=True,
                    **{
                        "冻结旁路": True,
                        "codes": [
                            "freeze_bypass",
                            "frozen_bypass",
                            "trace_bypass",
                            "freeze_trace_bypass",
                            "frozen_trace_bypass",
                            "freeze_bypass_gap",
                            "冻结旁路",
                        ],
                        "别名": [
                            "trace_bypass",
                            "frozen_bypass",
                            "freeze_trace_bypass",
                            "frozen_trace_bypass",
                            "freeze_bypass_gap",
                            "冻结旁路",
                        ],
                    },
                )
            )

    if fate == "suspended":
        for mouth in DISABLE_REQUIRED_MOUTHS:
            if mouths.get(mouth) is not False:
                gaps.append(_gap("write_mouth_leak", f"{mouth}写口仍开", mouth=mouth))
        for item in releases:
            rid = item["编号"]
            if not item.get("冻结留痕") or not item.get("冻结留痕时间"):
                gaps.append(
                    _gap(
                        "inflight_unclosed",
                        f"在途发版单 {item['发版单号']} 未留下停用收口痕迹",
                        release_id=rid,
                        serial=item["发版单号"],
                    )
                )
            for mouth in PROGRESSION_MOUTHS:
                if item.get("写口", {}).get(mouth) is not False:
                    gaps.append(
                        _gap(
                            "release_write_mouth_leak",
                            f"发版单 {item['发版单号']} 的{mouth}写口仍可推进",
                            release_id=rid,
                            serial=item["发版单号"],
                            mouth=mouth,
                        )
                    )
            if not item.get("同核收口"):
                gaps.append(
                    _gap(
                        "inflight_core_not_closed",
                        f"在途发版单 {item['发版单号']} 未进入同核收口态",
                        release_id=rid,
                        serial=item["发版单号"],
                    )
                )

    audit_replayable, audit_gaps, events = _audit_core(conn, app_id, fate, rows)
    gaps.extend(audit_gaps)

    write_refused = all(
        mouths.get(m) is False for m in ("入闸", "晋升", "放行")
    )
    # “在途收口” must mean durable closure evidence on every unclosed order,
    # not merely that the derived mouth map is closed by app status.
    inflight_closed = fate == "suspended" and all(
        item.get("冻结留痕")
        and item.get("冻结留痕时间")
        and item.get("同核收口")
        and _has_release_action(conn, int(item["编号"]), DISABLE_RELEASE_ACTIONS)
        for item in releases
    )
    evidence = {
        "停用标": marker,
        "写口拒": write_refused,
        "入闸写口拒": mouths.get("入闸") is False,
        "晋升写口拒": mouths.get("晋升") is False,
        "放行写口拒": mouths.get("放行") is False,
        "在途收口": inflight_closed,
        "审计重放": audit_replayable,
    }
    evidence["停用四证同核"] = all(
        (
            evidence["停用标"],
            evidence["写口拒"],
            evidence["在途收口"],
            evidence["审计重放"],
        )
    )
    # Strong retirement coverage can also be gap-free; for suspension the same
    # value is exactly the four-evidence conjunction above.
    evidence["同核"] = not gaps

    if gaps:
        lamp = "gap"
        lamp_text = "停用缺口"
        clean = False
        success = False
    elif fate == "open":
        lamp = "off"
        lamp_text = "未停用"
        clean = True
        success = False
    else:
        lamp = "clean"
        lamp_text = "停用干净" if fate == "suspended" else "强冻结覆盖"
        clean = True
        success = fate == "suspended"

    latest_receipt = conn.execute(
        """
        SELECT id, app_id, ok, clean, gap_count, payload_json, created_at
        FROM disable_receipts WHERE app_id=? ORDER BY id DESC LIMIT 1
        """,
        (app_id,),
    ).fetchone()
    receipt_row = dict(latest_receipt) if latest_receipt else None
    if receipt_row is not None:
        try:
            receipt_row["payload"] = json.loads(receipt_row.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            receipt_row["payload"] = {}

    authoritative_success = success and clean
    stale_green_receipt = bool(receipt_row and int(receipt_row.get("ok") or 0) == 1 and not clean)
    receipt_view = {
        "成功": authoritative_success,
        "ok": authoritative_success,
        "干净": clean,
        "clean": clean,
        "同核": clean,
        "灯": lamp,
        "light": lamp,
        "缺口": gaps,
        "gaps": gaps,
        "缺口数": len(gaps),
        "tag": SURFACE_TAG,
        "truthful": clean,
        "持久化": receipt_row is not None,
        "账面曾绿": stale_green_receipt,
        "允许短暂变绿": True,
    }
    if receipt_row is not None:
        # Keep the stale green bookkeeping row observable. The lamp/verdict above
        # remains authoritative, which is the “receipt may be briefly green but
        # the gap must stay pinned” contract.
        receipt_view["最新账面"] = receipt_row
        receipt_view["latest"] = receipt_row

    release_ids = [r["id"] for r in rows]
    return {
        "tag": SURFACE_TAG,
        "app_id": app_id,
        "应用编号": app_id,
        "编号": app_id,
        "应用": raw["name"],
        "状态": status,
        "应用状态": status,
        "命运": fate,
        "停用标": marker,
        "半截停用标": half_marker,
        "退役覆盖": retired_cover,
        "已停用": fate == "suspended",
        "停用成功": authoritative_success,
        "成功": authoritative_success,
        "success": authoritative_success,
        "ok": authoritative_success,
        "surface_ok": authoritative_success,
        "干净": clean,
        "clean": clean,
        "同核": clean,
        "同核收口": clean,
        "灯": lamp,
        "停用灯": lamp,
        "lamp": lamp,
        "light": lamp,
        "gap_count": len(gaps),
        "停用灯文案": lamp_text,
        "灯文案": lamp_text,
        "写口": mouths,
        "写口拒": write_refused,
        "入闸写口拒": mouths.get("入闸") is False,
        "晋升写口拒": mouths.get("晋升") is False,
        "放行写口拒": mouths.get("放行") is False,
        "在途收口": inflight_closed,
        "证据": evidence,
        "evidence": evidence,
        "审计重放": audit_replayable,
        "缺口": gaps,
        "缺口数": len(gaps),
        "gaps": gaps,
        "回执": receipt_view,
        "receipt": receipt_view,
        "在途发版": releases,
        "未收口发版单": releases,
        "在途数": len([x for x in releases if x.get("在途")]),
        "未收口数": len(releases),
        "审计时序": events,
        "审计事件": events,
        "最新回执": receipt_row,
        "release_ids": release_ids,
        "探针": {
            "入闸": {"应拒": True, "已拒": mouths.get("入闸") is False, "mouth": "入闸"},
            "晋升": {"应拒": True, "已拒": mouths.get("晋升") is False, "mouth": "晋升"},
            "放行": {"应拒": True, "已拒": mouths.get("放行") is False, "mouth": "放行"},
        },
    }


def heal_disable_in_txn(conn: sqlite3.Connection, app: sqlite3.Row, explicit: bool = False) -> bool:
    """Funnel every disable/status mouth into one atomic fate transition."""
    app_id = app["id"]
    original_status = app["status"]
    original_fate = fate_of_status(original_status)
    raw_status = original_status
    fate = original_fate
    changed = False
    stamp = now_str()

    audit_fate = "open"
    frozen_rows = None
    if fate == "open":
        audit_fate = latest_audit_fate(conn, app_id)
        frozen_rows = conn.execute(
            """
            SELECT 1 FROM releases
            WHERE app_id=? AND COALESCE(frozen,0)=1 AND status IN ({})
            LIMIT 1
            """.format(",".join("?" for _ in UNCLOSED_STATUSES)),
            (app_id, *UNCLOSED_STATUSES),
        ).fetchone()
        if explicit:
            fate = "suspended"
        elif audit_fate == "retired":
            conn.execute(
                "UPDATE apps SET status='退役', retired_at=COALESCE(retired_at, ?) WHERE id=?",
                (stamp, app_id),
            )
            fresh = _app_row(conn, app_id)
            from app.services.common import heal_retirement_in_txn

            heal_retirement_in_txn(conn, fresh)
            return True
        elif audit_fate == "suspended" or frozen_rows:
            fate = "suspended"
        else:
            return False

    if fate in ("retired", "dirty_closed"):
        from app.services.common import heal_retirement_in_txn

        return heal_retirement_in_txn(conn, app)

    # suspended (including 停用中 half markers and audit-replayed stripping).
    if raw_status != "停用":
        conn.execute(
            "UPDATE apps SET status='停用', disabled_at=COALESCE(disabled_at, ?) WHERE id=?",
            (stamp, app_id),
        )
        changed = True
    else:
        conn.execute(
            "UPDATE apps SET disabled_at=COALESCE(disabled_at, ?) WHERE id=?",
            (stamp, app_id),
        )

    rows = list_unclosed_rows(conn, app_id)
    dirty = [r for r in rows if not r["frozen"] or not r["frozen_at"]]
    missing_release_audit = [
        r for r in rows if not _has_release_action(conn, r["id"], DISABLE_RELEASE_ACTIONS)
    ]
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

    restored_from_open = (
        original_fate == "open"
        and fate == "suspended"
        and (audit_fate == "suspended" or bool(frozen_rows))
    )
    has_disable_app_event = conn.execute(
        """
        SELECT 1 FROM audit_events
        WHERE kind='应用' AND ref_id=? AND action LIKE '%停用%'
        LIMIT 1
        """,
        (app_id,),
    ).fetchone()
    fresh_explicit_disable = explicit and original_fate == "open" and not restored_from_open
    needs_replay_audit = (
        original_status != "停用"
        or bool(dirty)
        or bool(missing_release_audit)
        or restored_from_open
        or (fate == "suspended" and has_disable_app_event is None)
    )

    serials = "、".join(r["serial"] for r in rows)
    explicit_marker_transition = explicit and original_status != "停用"
    if explicit_marker_transition:
        detail = f"停用同核：关闭入闸/晋升写口，收口未收口 {len(rows)} 单"
        detail += f"：{serials}" if serials else "；无在途单"
        if original_fate == "suspended":
            detail = f"显式停用并归正半截标「{original_status}」；" + detail
        audit(conn, "应用", app_id, "停用", detail)
        changed = True
    elif fresh_explicit_disable:
        detail = f"停用同核：关闭入闸/晋升写口，收口未收口 {len(rows)} 单"
        detail += f"：{serials}" if serials else "；无在途单"
        audit(conn, "应用", app_id, "停用", detail)
        changed = True
    elif needs_replay_audit:
        dirty_serials = "、".join(r["serial"] for r in dirty)
        audit(
            conn,
            "应用",
            app_id,
            "停用重放收口",
            f"半截停用/交错状态重放，补收口 {len(dirty)} 单"
            + (f"：{dirty_serials}" if dirty_serials else ""),
        )
        changed = True
    # A repeated explicit disable over an already coherent core is idempotent:
    # do not insert another plain “停用” success event.

    for row in rows:
        if not _has_release_action(conn, row["id"], DISABLE_RELEASE_ACTIONS):
            audit(conn, "发版单", row["id"], "停用收口", row["serial"])
            changed = True

    return changed


def persist_receipt(conn: sqlite3.Connection, core: dict[str, Any]) -> dict[str, Any]:
    app_id = int(core["应用编号"])
    clean = bool(core["干净"])
    # “clean/core-coherent” and “authoritative disable success” are different
    # for a clean retired/frozen app. Persist both axes instead of painting a
    # retired core as a green disable success receipt.
    authoritative_ok = bool(core.get("停用成功", core.get("成功")))
    global_gap = False
    global_has_disable_marker = False
    for row in conn.execute("SELECT id FROM apps ORDER BY id").fetchall():
        other_id = int(row["id"])
        other_core = core if other_id == app_id else build_disable_core(conn, other_id)
        if other_core.get("缺口"):
            global_gap = True
        if other_core.get("停用标"):
            global_has_disable_marker = True
    global_clean = clean and not global_gap
    global_ok = global_clean and global_has_disable_marker
    created_at = now_str()
    payload = {
        "core": True,
        "truthful": True,
        "ok": authoritative_ok,
        "成功": authoritative_ok,
        "停用成功": authoritative_ok,
        "authoritative_success": authoritative_ok,
        "clean": clean,
        "干净": clean,
        "同核": clean,
        "灯": core.get("灯"),
        "停用灯": core.get("停用灯") or core.get("灯"),
        "global_ok": global_ok,
        "surface_ok": global_ok,
        "global_clean": global_clean,
        "app_id": app_id,
        "应用编号": app_id,
        "release_id": (core.get("release_ids") or [None])[0],
        "release_ids": core.get("release_ids") or [],
        "gap_count": core.get("缺口数", 0),
        "缺口数": core.get("缺口数", 0),
        "gaps": core.get("缺口", []),
        "缺口": core.get("缺口", []),
        "tag": SURFACE_TAG,
        "created_at": created_at,
    }
    payload_json = json.dumps(payload, ensure_ascii=False)
    cur = conn.execute(
        """
        INSERT INTO disable_receipts(app_id, ok, clean, gap_count, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (app_id, int(authoritative_ok), int(clean), int(core.get("缺口数") or 0), payload_json, created_at),
    )
    receipt_id = cur.lastrowid
    latest_row = {
        "id": receipt_id,
        "receipt_id": receipt_id,
        "app_id": app_id,
        "ok": int(authoritative_ok),
        "成功": int(authoritative_ok),
        "clean": int(clean),
        "干净": int(clean),
        "gap_count": int(core.get("缺口数") or 0),
        "payload_json": payload_json,
        "payload": payload,
        "created_at": created_at,
    }
    # Make the response returned by explicit heal/disable mouths immediately
    # observe the receipt inserted in the same transaction.
    receipt_view = core.get("回执")
    if isinstance(receipt_view, dict):
        receipt_view.update(
            {
                "持久化": True,
                "id": receipt_id,
                "receipt_id": receipt_id,
                "最新账面": latest_row,
                "latest": latest_row,
                "挂接回执": payload,
            }
        )
    core["挂接回执"] = payload
    put_setting(conn, "surface_ok", "1" if global_ok else "0")
    put_json(conn, "surface_last", payload)
    return {**payload, "id": receipt_id, "receipt_id": receipt_id}


def disable_app_transaction(app_id: int, note: str = "") -> dict[str, Any]:
    with write_txn() as conn:
        app = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
        if app is None:
            raise HTTPException(404, "应用不存在")
        heal_disable_in_txn(conn, app, explicit=True)
        if note:
            audit(conn, "应用", app_id, "停用备注", note)
        core = build_disable_core(conn, app_id)
        if core["缺口"]:
            # Same fate or whole batch退回: never leave a green success receipt
            # when postconditions still show an open mouth or unclosed evidence.
            raise HTTPException(status_code=409, detail={"message": "停用同核校验未通过，整笔退回", "核": core})
        receipt = persist_receipt(conn, core)
        core["挂接回执"] = receipt
        if isinstance(core.get("回执"), dict):
            core["回执"].update(
                {
                    "持久化": True,
                    "receipt_id": receipt.get("id"),
                    "id": receipt.get("id"),
                    "挂接回执": receipt,
                }
            )
    return core


def heal_app_transaction(app_id: int) -> dict[str, Any]:
    with write_txn() as conn:
        app = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
        if app is None:
            raise HTTPException(404, "应用不存在")
        changed = heal_disable_in_txn(conn, app, explicit=False)
        core = build_disable_core(conn, app_id)
        if core["状态"] == "启用" and not changed:
            core["收口动作"] = "应用开放，无需停用收口"
        else:
            core["收口动作"] = "已重放并收口" if changed else "状态一致，无需收口"
        if core["状态"] != "启用":
            persist_receipt(conn, core)
    return core


def enable_app_transaction(app_id: int) -> dict[str, Any]:
    with write_txn() as conn:
        app = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
        if app is None:
            raise HTTPException(404, "应用不存在")
        if fate_of_status(app["status"]) in ("retired", "dirty_closed"):
            raise HTTPException(400, "应用已退役冻结，不能改回启用；可重放 /收口 核对命运")
        stamp = now_str()
        conn.execute(
            "UPDATE apps SET status='启用', disabled_at=NULL WHERE id=?",
            (app_id,),
        )
        # Disable-time progression closure is reversible on explicit re-enable.
        # Retirement rows never reach this branch.
        conn.execute(
            """
            UPDATE releases SET frozen=0, frozen_at=NULL
            WHERE app_id=? AND COALESCE(frozen,0)=1
            """,
            (app_id,),
        )
        audit(conn, "应用", app_id, "启用", "停用后恢复启用，推进写口重开")
        core = build_disable_core(conn, app_id)
    return core


def disable_overview(conn: sqlite3.Connection) -> dict[str, Any]:
    apps = conn.execute("SELECT id FROM apps ORDER BY id").fetchall()
    cores = [build_disable_core(conn, r["id"]) for r in apps]
    app_cores = [c for c in cores if c["状态"] != "启用" or c["缺口"]]
    gaps: list[dict] = []
    for core in cores:
        for g in core["缺口"]:
            gaps.append(
                {
                    **g,
                    "应用编号": core["应用编号"],
                    "应用": core["应用"],
                    "应用状态": core["状态"],
                }
            )

    fake_surface = get_setting(conn, "surface_ok", "0") == "1"
    truthful_last = False
    try:
        raw_last = conn.execute("SELECT value FROM settings WHERE key='surface_last'").fetchone()
        if raw_last:
            last = json.loads(raw_last["value"])
            last_success = last.get("成功", last.get("ok", True))
            truthful_last = bool(
                last.get("truthful")
                and last.get("clean")
                and last_success
                and last.get("global_ok", True)
            )
    except Exception:
        truthful_last = False
    if fake_surface and not truthful_last:
        gaps.append(
            _gap(
                "fake_disable_lamp",
                "存在 surface_ok 伪绿灯标记，但停用标/写口拒/在途收口/审计重放不同核",
                setting="surface_ok",
            )
        )

    disable_cores = [c for c in cores if c["停用标"] or c["半截停用标"]]
    if gaps:
        lamp, text = "gap", "停用缺口"
    elif disable_cores:
        lamp, text = "clean", "停用干净"
    else:
        lamp, text = "off", "未停用"

    return {
        "tag": SURFACE_TAG,
        "灯": lamp,
        "停用灯": lamp,
        "lamp": lamp,
        "light": lamp,
        "灯文案": text,
        "停用灯文案": text,
        "干净": not gaps,
        "clean": not gaps,
        "ok": lamp == "clean",
        "success": lamp == "clean",
        "surface_ok": lamp == "clean",
        "gap_count": len(gaps),
        "缺口": gaps,
        "gaps": gaps,
        "缺口数": len(gaps),
        "应用核": cores,
        "停用应用核": disable_cores,
        "应用": app_cores,
        "停用应用数": len(disable_cores),
        "差额": len(gaps),
    }


def reconcile_disable(conn: sqlite3.Connection) -> dict[str, Any]:
    overview = disable_overview(conn)
    event_count = conn.execute(
        "SELECT COUNT(*) AS c FROM audit_events WHERE kind='应用' AND action LIKE '%停用%'"
    ).fetchone()["c"]
    release_event_count = conn.execute(
        "SELECT COUNT(*) AS c FROM audit_events WHERE kind='发版单' AND action IN (?, ?)",
        DISABLE_RELEASE_ACTIONS,
    ).fetchone()["c"]
    blocked_probe_count = conn.execute(
        "SELECT COUNT(*) AS c FROM audit_events WHERE kind='写口探针' AND action LIKE '%拒绝%'"
    ).fetchone()["c"]
    event_gap_codes = {
        "disable_event_missing",
        "disable_release_audit_missing",
        "retire_event_missing",
        "retire_release_audit_missing",
    }
    event_gap = sum(1 for gap in overview["缺口"] if gap.get("code") in event_gap_codes)
    return {
        **overview,
        "停用事件数": event_count,
        "停用单事件数": release_event_count,
        "写口探针拒绝数": blocked_probe_count,
        "事件差额": event_gap,
        "审计事件差额": event_gap,
        "ledger_ok": overview["缺口数"] == 0,
        "aligned": overview["缺口数"] == 0,
    }


def record_probe_blocked(app_id: int | None, release_id: int | None, mouth: str, reason: str) -> None:
    """Persist a refused closure probe after the writer txn has rolled back."""
    text = str(reason or "")
    if not any(key in text for key in ("停用", "冻结", "退役", "收口", "异常")):
        return
    try:
        with db() as conn:
            audit(
                conn,
                "写口探针",
                release_id,
                f"{mouth}拒绝",
                f"app={app_id}；{reason}",
            )
            from app.services.disable_surface_ledger import remember_probe

            remember_probe(conn, f"blocked_{mouth}", {"app_id": app_id, "release_id": release_id, "reason": reason})
    except Exception:
        # Audit persistence must not mask the original write rejection.
        pass


def sweep_all_disable_surfaces() -> int:
    healed = 0
    with db() as conn:
        apps = conn.execute("SELECT * FROM apps").fetchall()
        for app in apps:
            if heal_disable_in_txn(conn, app, explicit=False):
                healed += 1
    return healed

from __future__ import annotations

import json
import sqlite3


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    return row["value"] if isinstance(row, sqlite3.Row) else row[0]


def put_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_json(conn: sqlite3.Connection, key: str, default=None):
    raw = get_setting(conn, key, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def put_json(conn: sqlite3.Connection, key: str, value) -> None:
    put_setting(conn, key, json.dumps(value, ensure_ascii=False))


PAINT_COUNTS = {"已入闸": 1}


def overlay_overview(base: dict, conn) -> dict:
    """Merge the truthful disable core; never paint a fake green lamp."""
    out = dict(base or {})
    try:
        from app.services.surface_core import disable_overview

        core = disable_overview(conn)
        out["停用总览"] = core
        out["停用灯"] = core["停用灯"]
        out["停用缺口"] = core["缺口"]
        out["停用缺口数"] = core["缺口数"]
        out["surface_ok"] = core["surface_ok"]
    except Exception:
        # Overview must remain available even if a dirty fixture cannot replay.
        out.setdefault("surface_ok", False)
    return out


def paint(conn, out: dict) -> dict:
    """Persist a marker only as untrusted legacy surface state.

    The disable core replaces this marker with a truthful receipt after its
    postconditions pass.  Keeping ``ok=False`` here prevents a standalone paint
    helper from becoming the fake success arm.
    """
    rid = (out or {}).get("编号") or (out or {}).get("id") or (out or {}).get("release_id")
    payload = {"ok": False, "painted": True, "truthful": False, "release_id": rid}
    put_json(conn, "surface_last", payload)
    put_setting(conn, "surface_ok", "0")
    return payload


def strip_keep_receipt(conn, out: dict) -> None:
    """Deprecated fake arm: never reopen an app or reset a release."""
    return None


def after_action(conn, out, *args, **kwargs):
    """Do not manufacture a green receipt or strip the persisted fate."""
    if not isinstance(out, dict):
        return out
    fake = dict(out)
    clean = bool(fake.get("干净") or fake.get("同核收口")) and not fake.get("缺口")
    if "成功" in fake or "停用成功" in fake or "ok" in fake:
        success = bool(fake.get("成功", fake.get("停用成功", fake.get("ok"))))
    else:
        success = clean
    rc = dict(fake.get("回执") or {})
    rc["成功"] = success
    rc["ok"] = success
    rc["clean"] = clean
    rc["干净"] = clean
    fake["回执"] = rc
    fake["surface_ok"] = success
    return fake

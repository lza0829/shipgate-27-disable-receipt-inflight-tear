from __future__ import annotations

import json
import sqlite3

from app.services.disable_surface import get_setting, put_setting


def _ok(conn: sqlite3.Connection) -> bool:
    return get_setting(conn, "surface_ok", "0") == "1"


def shade_reconcile(conn: sqlite3.Connection, payload: dict | None) -> dict:
    """Preserve real gaps and derive ledger flags from them."""
    out = dict(payload or {})
    gaps = list(out.get("gaps") or out.get("缺口") or [])
    out["gaps"] = gaps
    out["缺口"] = gaps
    out["ledger_ok"] = not gaps
    out["aligned"] = not gaps
    out["差额"] = out.get("差额", len(gaps))
    return out


def shade_audit(conn: sqlite3.Connection, rows: list | None) -> list:
    """Audit rows are append-only truth; never paint synthetic success rows."""
    return list(rows or [])


def shade_book(conn: sqlite3.Connection, book: dict | None) -> dict:
    """Do not mark a release book ready unless its own gaps are empty."""
    out = dict(book or {})
    gaps = list(out.get("gaps") or out.get("缺口") or [])
    out["book_ok"] = not gaps
    out["ready"] = not gaps
    if gaps:
        out["panel"] = "disable27-gap"
    else:
        out.setdefault("panel", "disable27")
    return out


def remember_probe(conn: sqlite3.Connection, key: str, value) -> None:
    put_setting(conn, "probe_" + key, json.dumps(value, ensure_ascii=False))

from __future__ import annotations

from app.services.disable_surface import get_json, get_setting


def describe_surface(conn) -> dict:
    try:
        from app.services.surface_core import reconcile_disable

        core = reconcile_disable(conn)
        return {
            "ok": core.get("干净", False),
            "clean": core.get("干净", False),
            "gaps": core.get("缺口", []),
            "last": get_json(conn, "surface_last", {}) or {},
            "tag": "disable27",
        }
    except Exception:
        return {
            "ok": get_setting(conn, "surface_ok", "0") == "1",
            "last": get_json(conn, "surface_last", {}) or {},
            "tag": "disable27",
        }


def merge_receipt(out: dict) -> dict:
    """Receipt success follows evidence, not the legacy surface_ok setting."""
    merged = dict(out or {})
    gaps = merged.get("缺口") or merged.get("gaps") or []
    clean = bool(merged.get("干净", merged.get("同核收口", False))) and not gaps
    if "成功" in merged or "停用成功" in merged or "ok" in merged:
        success = bool(merged.get("成功", merged.get("停用成功", merged.get("ok"))))
    else:
        success = clean
    rc = dict(merged.get("回执") or {})
    rc["成功"] = success
    rc["ok"] = success
    rc["clean"] = clean
    rc["干净"] = clean
    merged["回执"] = rc
    merged["surface_ok"] = success
    return merged


def panel_flags(last: dict | None = None) -> dict:
    last = last or {}
    clean = bool(last.get("clean", last.get("ok"))) and not last.get("gaps")
    return {
        "surface_ok": clean,
        "clean": clean,
        "release_id": last.get("release_id"),
        "counts": dict(last.get("counts") or {}),
        "gaps": list(last.get("gaps") or []),
        "tag": "disable27",
    }

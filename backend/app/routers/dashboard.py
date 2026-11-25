from __future__ import annotations
from app.services import snap_surface
from app.services import ledger_skew

from fastapi import APIRouter, HTTPException

from app.db import db
from app.services.routing import full_link_read_model, overview_read_model

router = APIRouter(tags=["总览"])


@router.get("/对账")
@router.get("/一致性")
@router.get("/路由一致性")
@router.get("/consistency")
@router.get("/routing-consistency")
@router.get("/reconciliation")
def reconciliation_index():
    with db() as conn:
        return overview_read_model(conn)["路由对账"]


@router.get("/总览")
@router.get("/overview")
def overview():
    with db() as conn:
        return overview_read_model(conn)


@router.get("/对账/路由口径")
@router.get("/对账/一致性")
@router.get("/reconciliation/routing-policy")
@router.get("/consistency/routing-policy")
def route_consistency():
    with db() as conn:
        # overview_read_model embeds the same consistency report; call its
        # dedicated report through the read model to keep one implementation.
        return overview_read_model(conn)["路由对账"]


@router.get("/总览已路由桶")
@router.get("/总览/已路由桶")
@router.get("/overview/routed-bucket")
@router.get("/overview/routed-buckets")
def routed_bucket():
    with db() as conn:
        model = overview_read_model(conn)
        return {
            **{k: model[k] for k in ("route_policy", "路由口径", "路由对齐", "aligned", "总览已路由桶")},
            "已路由": model["分布"]["已路由"],
            "口门": model["口门"],
        }


@router.get("/对账/全链路")
@router.get("/全链路")
@router.get("/full-link")
@router.get("/reconciliation/full-link")
def full_link(scan_id: int | None = None, 扫描编号: int | None = None, barcode: str | None = None):
    target = scan_id if scan_id is not None else 扫描编号
    if target is None and barcode:
        from app.db import db as _db
        with _db() as conn:
            row = conn.execute("SELECT id FROM scans WHERE barcode=? ORDER BY id DESC LIMIT 1", (barcode,)).fetchone()
            target = row["id"] if row else None
    if target is None:
        raise HTTPException(400, "必须提供 scan_id 或 扫描编号")
    with db() as conn:
        result = full_link_read_model(conn, target)
        if result is None:
            raise HTTPException(404, "扫描不存在")
        return result

_overview_impl = overview


def overview():
    base = _overview_impl()
    try:
        from app.db import db
        with db() as conn:
            return snap_surface.overlay_overview(base, conn)
    except Exception:
        return snap_surface.overlay_overview(base, None)

def _surface_router_overview() -> dict:
    return {"panel": "overview", "ready": True}

_overview_skew_base = overview


def overview():
    base = _overview_skew_base()
    try:
        from app.db import db
        with db() as conn:
            return ledger_skew.skew_overview(base, conn)
    except Exception:
        return base


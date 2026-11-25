from __future__ import annotations

from fastapi import APIRouter

from app.db import db
from app.services.routing import replay_line_audit, replay_scan

router = APIRouter(tags=["审计"])


@router.get("/审计")
@router.get("/审计事件")
@router.get("/audit")
@router.get("/audit-events")
def list_audit(
    kind: str | None = None,
    ref_id: int | None = None,
    scan_id: int | None = None,
    扫描编号: int | None = None,
    limit: int = 200,
):
    target_scan = scan_id if scan_id is not None else 扫描编号
    clauses = []
    params: list[object] = []
    if kind:
        clauses.append("kind=?")
        params.append(kind)
    if ref_id is not None:
        clauses.append("ref_id=?")
        params.append(ref_id)
    if target_scan is not None:
        clauses.append(
            """(
              (kind='扫描' AND ref_id=?)
              OR (
                kind='封袋'
                AND (
                  note=?
                  OR note LIKE ?
                  OR (action='封口' AND ref_id=(SELECT bag_id FROM scans WHERE id=?))
                )
              )
              OR (kind='回流' AND note=?)
              OR (
                kind='路由表'
                AND (
                  ref_id=(SELECT snapshot_rule_id FROM scans WHERE id=?)
                  OR note LIKE (
                    SELECT dest_code || ':%' FROM scans
                     WHERE id=? AND dest_code <> ''
                  )
                )
              )
            )"""
        )
        params.extend([
            target_scan,
            str(target_scan),
            f"{target_scan};%",
            target_scan,
            str(target_scan),
            target_scan,
            target_scan,
        ])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    safe_limit = max(1, min(int(limit), 1000))
    params.append(safe_limit)
    with db() as conn:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM audit_events{where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()]


@router.get("/审计/重放")
@router.get("/审计重放")
@router.get("/audit/replay")
def audit_replay(scan_id: int | None = None, 扫描编号: int | None = None):
    target_id = scan_id if scan_id is not None else 扫描编号
    with db() as conn:
        if target_id is not None:
            result = replay_scan(conn, target_id)
            if result is None:
                from fastapi import HTTPException
                raise HTTPException(404, "扫描不存在")
            return result
        return replay_line_audit(conn)


@router.get("/审计/分拣线重放")
@router.get("/分拣线审计重放")
@router.get("/audit/line-replay")
def line_audit_replay(line_id: int | None = None, 分拣线编号: int | None = None):
    target = line_id if line_id is not None else 分拣线编号
    with db() as conn:
        return replay_line_audit(conn, target)


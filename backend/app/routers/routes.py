from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.db import db, row_to_dict, write_db
from app.services import common
from app.services import routing
from app.services.routing import get_chute_by_identifier, policy_info, replay_scan

router = APIRouter(tags=["路由表"])


def audit(*args, **kwargs):
    # Resolve through common at call time so tests can patch either
    # app.services.common.audit or app.routers.routes.audit.
    return common.audit(*args, **kwargs)


def record_route_version(*args, **kwargs):
    # Same patch-through behaviour for failure-injection fixtures.
    return routing.record_route_version(*args, **kwargs)


@router.get("/路由口径")
@router.get("/路由策略")
@router.get("/policy")
@router.get("/routing")
@router.get("/routing-policy")
def route_policy():
    return policy_info()


class RouteIn(BaseModel):
    目的地码: str = Field(min_length=1)
    口门编号: int | str
    备注: str = ""

    @model_validator(mode="before")
    @classmethod
    def accept_common_english_aliases(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("目的地码") in (None, ""):
            data["目的地码"] = (
                data.get("dest_code")
                or data.get("destination_code")
                or data.get("destination")
            )
        if data.get("口门编号") is None:
            data["口门编号"] = data.get("chute_id") or data.get("chuteId")
        if not data.get("备注"):
            data["备注"] = data.get("note") or ""
        return data


@router.get("/路由表")
@router.get("/路由表页")
@router.get("/routes")
def list_routes():
    with db() as conn:
        return [dict(r) for r in conn.execute(
            """
            SELECT r.*, c.code AS 口门码, c.title AS 口门标题
              FROM route_rules r JOIN chutes c ON c.id=r.chute_id
             ORDER BY r.dest_code
            """
        ).fetchall()]


@router.get("/路由表/版本")
@router.get("/routes/versions")
def list_route_versions(目的地码: str | None = None, dest_code: str | None = None):
    destination = 目的地码 if 目的地码 is not None else dest_code
    with db() as conn:
        if destination:
            rows = conn.execute(
                """
                SELECT v.*, c.code AS 口门码
                  FROM route_rule_versions v
                  JOIN chutes c ON c.id=v.chute_id
                 WHERE v.dest_code=?
                 ORDER BY v.id DESC
                """,
                (destination,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT v.*, c.code AS 口门码
                  FROM route_rule_versions v
                  JOIN chutes c ON c.id=v.chute_id
                 ORDER BY v.id DESC LIMIT 200
                """
            ).fetchall()
        return [dict(r) for r in rows]


@router.post("/路由表")
@router.put("/路由表")
@router.post("/routes")
@router.put("/routes")
def upsert_route(body: RouteIn):
    with write_db() as conn:
        chute = get_chute_by_identifier(conn, body.口门编号)
        if not chute:
            raise HTTPException(404, "口门不存在")
        chute_pk = chute["id"]

        exist = conn.execute(
            "SELECT * FROM route_rules WHERE dest_code=?", (body.目的地码,)
        ).fetchone()
        old_chute_id = exist["chute_id"] if exist else None
        old_chute_code = None
        if old_chute_id:
            old_chute = conn.execute("SELECT code FROM chutes WHERE id=?", (old_chute_id,)).fetchone()
            old_chute_code = old_chute["code"] if old_chute else None

        if exist:
            rid = exist["id"]
            action = "改路由"
            conn.execute(
                "UPDATE route_rules SET chute_id=?, note=? WHERE id=?",
                (chute_pk, body.备注, rid),
            )
        else:
            action = "新建路由"
            conn.execute(
                "INSERT INTO route_rules(dest_code, chute_id, current_version, note) VALUES (?, ?, 0, ?)",
                (body.目的地码, chute_pk, body.备注),
            )
            rid = conn.execute(
                "SELECT id FROM route_rules WHERE dest_code=?", (body.目的地码,)
            ).fetchone()["id"]

        version_action = "路由改档" if action == "改路由" else "路由新建"
        version = record_route_version(
            conn,
            rule_id=rid,
            action=version_action,
            chute_id=chute_pk,
            note=body.备注,
        )

        # Snapshot policy: route-table writes never touch scans.planned_chute_id.
        pending = conn.execute(
            "SELECT COUNT(*) AS c FROM scans WHERE dest_code=? AND status='待路由'",
            (body.目的地码,),
        ).fetchone()["c"]
        audit(
            conn, "路由表", rid, action,
            (
                f"{body.目的地码}: {old_chute_code or '无'} -> {chute['code']}; "
                f"v{version}; 待路由快照不回写 {pending} 笔"
            ),
        )
        row = conn.execute(
            """
            SELECT r.*, c.code AS 口门码, c.title AS 口门标题
              FROM route_rules r JOIN chutes c ON c.id=r.chute_id
             WHERE r.id=?
            """,
            (rid,),
        ).fetchone()
        result = row_to_dict(row)
        result["old_chute_id"] = old_chute_id
        result["old_chute_code"] = old_chute_code
        result["new_chute_id"] = chute_pk
        result["口门编号"] = chute_pk
        result["new_chute_code"] = chute["code"]
        result["version"] = version
        result["待路由快照不回写笔数"] = pending
        return result


@router.get("/路由重放")
@router.get("/路由表/重放")
@router.get("/routes/replay")
def route_replay(
    扫描编号: int | None = None,
    scan_id: int | None = None,
    barcode: str | None = None,
):
    target_id = 扫描编号 if 扫描编号 is not None else scan_id
    with db() as conn:
        if target_id is None and barcode:
            row = conn.execute("SELECT id FROM scans WHERE barcode=? ORDER BY id DESC LIMIT 1", (barcode,)).fetchone()
            target_id = row["id"] if row else None
    if target_id is None:
        raise HTTPException(400, "必须提供扫描编号或 scan_id")
    with db() as conn:
        result = replay_scan(conn, target_id)
        if result is None:
            raise HTTPException(404, "扫描不存在")
        return result

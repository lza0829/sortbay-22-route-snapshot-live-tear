from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from app.config import ROUTE_POLICY
from app.db import db, row_to_dict, write_db
from app.services import common
from app.services.common import current_shift, now_str, require_unsealed
from app.services.routing import (
    admitted_scans_for_chute,
    enrich_scan,
    get_chute_by_identifier,
    list_enriched_scans,
)

router = APIRouter(tags=["封袋"])


def audit(*args, **kwargs):
    return common.audit(*args, **kwargs)


class BagOpenIn(BaseModel):
    口门编号: int | str
    备注: str = ""

    @model_validator(mode="before")
    @classmethod
    def accept_english_aliases(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("口门编号") is None:
            data["口门编号"] = (
                data.get("chute_id")
                or data.get("chuteId")
                or data.get("chute_code")
                or data.get("chuteCode")
                or data.get("gate_id")
                or data.get("gateId")
                or data.get("code")
                or data.get("gate")
            )
        if not data.get("备注"):
            data["备注"] = data.get("note") or ""
        return data


class BagAddIn(BaseModel):
    扫描编号: int

    @model_validator(mode="before")
    @classmethod
    def accept_english_aliases(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("扫描编号") is None:
            data["扫描编号"] = (
                data.get("scan_id")
                or data.get("scanId")
                or data.get("scanID")
                or data.get("扫描id")
                or data.get("id")
            )
        return data


@router.get("/封袋")
@router.get("/封袋页")
@router.get("/bags")
def list_bags():
    with db() as conn:
        return [dict(r) for r in conn.execute(
            """
            SELECT b.*, c.code AS 口门码,
              (SELECT COUNT(*) FROM scans s WHERE s.bag_id=b.id) AS 件数
            FROM bags b JOIN chutes c ON c.id=b.chute_id
            ORDER BY b.id DESC LIMIT 100
            """
        ).fetchall()]


@router.get("/封袋/{bag_id}/件")
@router.get("/bags/{bag_id}/items")
def list_bag_items(bag_id: int):
    with db() as conn:
        bag = conn.execute("SELECT id FROM bags WHERE id=?", (bag_id,)).fetchone()
        if not bag:
            raise HTTPException(404, "袋不存在")
        rows = conn.execute(
            "SELECT * FROM scans WHERE bag_id=? ORDER BY id", (bag_id,)
        ).fetchall()
        return list_enriched_scans(conn, rows)


@router.get("/封袋/准入")
@router.get("/封袋准入")
@router.get("/bags/admission")
def bag_admission(
    袋编号: int | None = None,
    口门编号: int | str | None = None,
    bag_id: int | None = None,
    chute_id: int | str | None = None,
):
    with db() as conn:
        chute_id = 口门编号 if 口门编号 is not None else chute_id
        bag_identifier = 袋编号 if 袋编号 is not None else bag_id
        bag = None
        if bag_identifier is not None:
            bag = conn.execute(
                """
                SELECT b.*, c.code AS 口门码 FROM bags b
                JOIN chutes c ON c.id=b.chute_id WHERE b.id=?
                """,
                (bag_identifier,),
            ).fetchone()
            if not bag:
                raise HTTPException(404, "袋不存在")
            chute_id = bag["chute_id"]
        if chute_id is None:
            raise HTTPException(400, "必须提供袋编号或口门编号")
        chute = get_chute_by_identifier(conn, chute_id)
        if not chute:
            raise HTTPException(404, "口门不存在")
        chute_id = chute["id"]
        allowed = admitted_scans_for_chute(conn, chute_id)
        return {
            "袋": row_to_dict(bag),
            "bag": row_to_dict(bag),
            "口门": row_to_dict(chute),
            "chute": row_to_dict(chute),
            "口门编号": chute_id,
            "chute_id": chute_id,
            "准入件数": len(allowed),
            "admitted_count": len(allowed),
            "准入扫描": allowed,
            "admitted_scans": allowed,
        }


# Static /admission routes must be registered before /bags/{bag_id}.
@router.get("/封袋/{bag_id}")
@router.get("/bags/{bag_id}")
def get_bag(bag_id: int):
    with db() as conn:
        bag = conn.execute(
            """
            SELECT b.*, c.code AS 口门码
              FROM bags b JOIN chutes c ON c.id=b.chute_id
             WHERE b.id=?
            """,
            (bag_id,),
        ).fetchone()
        if not bag:
            raise HTTPException(404, "袋不存在")
        scan_rows = conn.execute(
            "SELECT * FROM scans WHERE bag_id=? ORDER BY id", (bag_id,)
        ).fetchall()
        scans = list_enriched_scans(conn, scan_rows)
        result = row_to_dict(bag)
        result["件数"] = len(scans)
        result["scans"] = scans
        result["扫描"] = scans
        result["items"] = scans
        return result


@router.post("/封袋/开袋")
@router.post("/bags/open")
def open_bag(body: BagOpenIn):
    with write_db() as conn:
        require_unsealed(conn)
        shift = current_shift(conn)
        chute = get_chute_by_identifier(conn, body.口门编号)
        if not chute:
            raise HTTPException(404, "口门不存在")
        code = (
            f"袋-{chute['code']}-{shift['id']}-"
            f"{now_str().replace(':', '').replace(' ', '')[-10:]}-{uuid.uuid4().hex[:6]}"
        )
        conn.execute(
            "INSERT INTO bags(shift_id, chute_id, code, status, note) VALUES (?, ?, ?, '集包中', ?)",
            (shift["id"], chute["id"], code, body.备注),
        )
        row = conn.execute("SELECT * FROM bags WHERE code=?", (code,)).fetchone()
        audit(conn, "封袋", row["id"], "开袋", code)
        return row_to_dict(row)


@router.post("/封袋/{bag_id}/入袋")
@router.post("/bags/{bag_id}/add")
@router.post("/bags/{bag_id}/items")
def add_to_bag(bag_id: int, body: BagAddIn):
    wrong_gate: dict | None = None
    inconsistent_gate: dict | None = None
    try:
        with write_db() as conn:
            require_unsealed(conn)
            bag = conn.execute("SELECT * FROM bags WHERE id=?", (bag_id,)).fetchone()
            if not bag:
                raise HTTPException(404, "袋不存在")
            if bag["status"] != "集包中":
                raise HTTPException(400, "袋已封，禁止再入")
            scan = conn.execute("SELECT * FROM scans WHERE id=?", (body.扫描编号,)).fetchone()
            if not scan:
                raise HTTPException(404, "扫描不存在")
            # Compare the physical landing gate before status so an already
            # bagged item dragged to the wrong gate still gets a precise reason.
            if scan["chute_id"] is not None and scan["chute_id"] != bag["chute_id"]:
                scan_chute = conn.execute(
                    "SELECT code FROM chutes WHERE id=?", (scan["chute_id"],)
                ).fetchone()
                bag_chute = conn.execute(
                    "SELECT code FROM chutes WHERE id=?", (bag["chute_id"],)
                ).fetchone()
                wrong_gate = {
                    "scan_id": body.扫描编号,
                    "scan_chute_id": scan["chute_id"],
                    "scan_chute_code": scan_chute["code"] if scan_chute else None,
                    "bag_chute_id": bag["chute_id"],
                    "bag_chute_code": bag_chute["code"] if bag_chute else None,
                }
                raise HTTPException(
                    400,
                    (
                        "扫描实落口门与袋口门不一致，禁止错口入袋: "
                        f"扫描={wrong_gate['scan_chute_code']}#{scan['chute_id']}, "
                        f"袋={wrong_gate['bag_chute_code']}#{bag['chute_id']}"
                    ),
                )
            if scan["status"] != "已路由":
                raise HTTPException(400, "仅已路由件可入袋")
            if (
                scan["route_policy"] != ROUTE_POLICY
                or scan["planned_chute_id"] is None
                or scan["chute_id"] != scan["planned_chute_id"]
            ):
                inconsistent_gate = {
                    "scan_id": body.扫描编号,
                    "planned_chute_id": scan["planned_chute_id"],
                    "actual_chute_id": scan["chute_id"],
                    "route_policy": scan["route_policy"],
                }
                raise HTTPException(
                    409,
                    "扫描拟落快照口门与实落口门口径不一致，封袋准入回滚并禁止亮已对齐",
                )
            conn.execute(
                """
                UPDATE scans
                   SET status='已入袋', bag_id=?
                 WHERE id=?
                   AND status='已路由'
                   AND chute_id=?
                   AND planned_chute_id=?
                """,
                (
                    bag_id,
                    body.扫描编号,
                    scan["chute_id"],
                    scan["planned_chute_id"],
                ),
            )
            if conn.execute("SELECT changes() AS c").fetchone()["c"] == 0:
                raise HTTPException(409, "扫描状态已被并发修改，入袋回滚")
            audit(conn, "封袋", bag_id, "入袋", str(body.扫描编号))
            row = conn.execute("SELECT * FROM scans WHERE id=?", (body.扫描编号,)).fetchone()
            return enrich_scan(conn, row)
    except HTTPException:
        if wrong_gate is not None:
            # The business transaction has already rolled back; persist the
            # interception in its own transaction so an attempted wrong gate is
            # visible during reconciliation.
            with write_db() as audit_conn:
                audit(
                    audit_conn, "封袋", bag_id, "错口入袋拦截",
                    f"{wrong_gate['scan_id']}; 扫描实落{wrong_gate['scan_chute_code']}"
                    f"/{wrong_gate['scan_chute_id']} != 袋口"
                    f"{wrong_gate['bag_chute_code']}/{wrong_gate['bag_chute_id']}",
                )
        if inconsistent_gate is not None:
            with write_db() as audit_conn:
                audit(
                    audit_conn, "封袋", bag_id, "口径不一致入袋拦截",
                    f"{inconsistent_gate['scan_id']}; "
                    f"拟落={inconsistent_gate['planned_chute_id']}, "
                    f"实落={inconsistent_gate['actual_chute_id']}, "
                    f"口径={inconsistent_gate['route_policy']}",
                )
        raise


@router.post("/封袋/{bag_id}/封口")
@router.post("/bags/{bag_id}/seal")
def seal_bag(bag_id: int):
    with write_db() as conn:
        require_unsealed(conn)
        bag = conn.execute("SELECT * FROM bags WHERE id=?", (bag_id,)).fetchone()
        if not bag:
            raise HTTPException(404, "袋不存在")
        if bag["status"] != "集包中":
            raise HTTPException(400, "袋状态不可封口")
        n = conn.execute(
            "SELECT COUNT(*) c FROM scans WHERE bag_id=?", (bag_id,)
        ).fetchone()["c"]
        if n == 0:
            raise HTTPException(400, "空袋不可封口")
        wrong = conn.execute(
            """
            SELECT COUNT(*) c
              FROM scans s JOIN bags b ON b.id=s.bag_id
             WHERE s.bag_id=?
               AND (
                    s.chute_id IS NULL
                 OR s.chute_id <> b.chute_id
                 OR s.planned_chute_id IS NULL
                 OR s.chute_id <> s.planned_chute_id
                 OR s.route_policy <> ?
               )
            """,
            (bag_id, ROUTE_POLICY),
        ).fetchone()["c"]
        if wrong:
            raise HTTPException(409, f"袋内有 {wrong} 笔错口或口径不一致件，禁止封口并亮对齐")
        sealed_at = now_str()
        conn.execute(
            "UPDATE bags SET status='已封袋', sealed_at=? WHERE id=?",
            (sealed_at, bag_id),
        )
        conn.execute(
            "UPDATE scans SET status='已封袋' WHERE bag_id=?",
            (bag_id,),
        )
        audit(conn, "封袋", bag_id, "封口", f"件数{n}")
        return row_to_dict(conn.execute("SELECT * FROM bags WHERE id=?", (bag_id,)).fetchone())

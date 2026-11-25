from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from app.db import db, rows_to_list, row_to_dict, write_db
from app.services.common import audit
from app.services.routing import admitted_scans_for_chute, list_enriched_scans

router = APIRouter(tags=["口门"])


class ChuteIn(BaseModel):
    分拣线编号: int
    口门码: str = Field(min_length=1)
    标题: str = ""
    软容量: int = 120

    @model_validator(mode="before")
    @classmethod
    def accept_english_aliases(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("分拣线编号") is None:
            data["分拣线编号"] = data.get("line_id") or data.get("lineId")
        if not data.get("口门码"):
            data["口门码"] = data.get("code") or data.get("chute_code") or ""
        if not data.get("标题"):
            data["标题"] = data.get("title") or data.get("name") or ""
        if data.get("软容量") is None:
            data["软容量"] = data.get("soft_cap") or data.get("capacity") or 120
        return data


@router.get("/口门")
@router.get("/chutes")
def list_chutes():
    with db() as conn:
        return rows_to_list(conn.execute(
            "SELECT c.*, l.name AS 分拣线名 FROM chutes c JOIN lines l ON l.id=c.line_id ORDER BY c.code"
        ).fetchall())


@router.get("/口门/{chute_id}")
@router.get("/chutes/{chute_id}")
def get_chute_detail(chute_id: int):
    with db() as conn:
        chute = conn.execute(
            """
            SELECT c.*, l.name AS 分拣线名
              FROM chutes c JOIN lines l ON l.id=c.line_id
             WHERE c.id=?
            """,
            (chute_id,),
        ).fetchone()
        if not chute:
            raise HTTPException(404, "口门不存在")
        actual_rows = conn.execute(
            "SELECT * FROM scans WHERE chute_id=? ORDER BY id DESC LIMIT 200",
            (chute_id,),
        ).fetchall()
        planned_rows = conn.execute(
            "SELECT * FROM scans WHERE planned_chute_id=? ORDER BY id DESC LIMIT 200",
            (chute_id,),
        ).fetchall()
        actual_scans = list_enriched_scans(conn, actual_rows)
        planned_scans = list_enriched_scans(conn, planned_rows)
        admitted = admitted_scans_for_chute(conn, chute_id)
        result = row_to_dict(chute)
        result["口门落入"] = actual_scans
        result["landings"] = actual_scans
        result["scans"] = actual_scans
        result["拟落扫描"] = planned_scans
        result["planned_scans"] = planned_scans
        result["准入扫描"] = admitted
        result["admitted_scans"] = admitted
        result["已路由数"] = sum(s.get("status") == "已路由" for s in actual_scans)
        return result


@router.post("/口门")
@router.post("/chutes")
def create_chute(body: ChuteIn):
    with write_db() as conn:
        try:
            conn.execute(
                "INSERT INTO chutes(line_id, code, title, status, soft_cap) VALUES (?, ?, ?, '口门开', ?)",
                (body.分拣线编号, body.口门码, body.标题, body.软容量),
            )
        except Exception as e:
            raise HTTPException(400, f"创建失败: {e}")
        row = conn.execute(
            "SELECT * FROM chutes WHERE line_id=? AND code=?",
            (body.分拣线编号, body.口门码),
        ).fetchone()
        audit(conn, "口门", row["id"], "新建", body.口门码)
        return row_to_dict(row)


@router.post("/口门/{chute_id}/开闭")
@router.post("/chutes/{chute_id}/status")
def set_chute(
    chute_id: int,
    状态: str | None = Query(None),
    status: str | None = None,
    state: str | None = None,
):
    raw_status = 状态 or status or state
    normalized = {
        "口门开": "口门开",
        "open": "口门开",
        "opened": "口门开",
        "口门闭": "口门闭",
        "closed": "口门闭",
        "close": "口门闭",
    }.get((raw_status or "").strip().lower() if raw_status and raw_status.isascii() else raw_status)
    if normalized not in ("口门开", "口门闭"):
        raise HTTPException(400, "状态仅允许口门开或口门闭/open/closed")
    状态 = normalized
    with write_db() as conn:
        cur = conn.execute("UPDATE chutes SET status=? WHERE id=?", (状态, chute_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "口门不存在")
        audit(conn, "口门", chute_id, "开闭", 状态)
        return row_to_dict(conn.execute("SELECT * FROM chutes WHERE id=?", (chute_id,)).fetchone())


@router.post("/chutes/{chute_id}/open")
def open_chute(chute_id: int):
    return set_chute(chute_id, 状态="口门开")


@router.post("/chutes/{chute_id}/close")
def close_chute(chute_id: int):
    return set_chute(chute_id, 状态="口门闭")

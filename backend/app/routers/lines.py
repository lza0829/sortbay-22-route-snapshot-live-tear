from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from app.db import db, rows_to_list, row_to_dict, write_db
from app.services.common import audit

router = APIRouter(tags=["分拣线"])


class LineIn(BaseModel):
    名称: str = Field(min_length=1)
    启用: bool = True

    @model_validator(mode="before")
    @classmethod
    def accept_english_aliases(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if not data.get("名称"):
            data["名称"] = data.get("name") or data.get("line_name") or ""
        if "启用" not in data:
            data["启用"] = data.get("active", data.get("enabled", True))
        return data


@router.get("/分拣线")
@router.get("/lines")
def list_lines():
    with db() as conn:
        return rows_to_list(conn.execute("SELECT * FROM lines ORDER BY id").fetchall())


@router.post("/分拣线")
@router.post("/lines")
def create_line(body: LineIn):
    with write_db() as conn:
        try:
            conn.execute(
                "INSERT INTO lines(name, active) VALUES (?, ?)",
                (body.名称, 1 if body.启用 else 0),
            )
        except Exception as e:
            raise HTTPException(400, f"创建失败: {e}")
        row = conn.execute("SELECT * FROM lines WHERE name=?", (body.名称,)).fetchone()
        audit(conn, "分拣线", row["id"], "新建", body.名称)
        return row_to_dict(row)


@router.post("/分拣线/{line_id}/启停")
@router.post("/lines/{line_id}/toggle")
def toggle_line(
    line_id: int,
    启用: bool | None = Query(None),
    active: bool | None = None,
    enabled: bool | None = None,
):
    target_active = 启用 if 启用 is not None else active
    target_active = target_active if target_active is not None else enabled
    if target_active is None:
        raise HTTPException(400, "必须提供启用状态 active/enabled/启用")
    with write_db() as conn:
        cur = conn.execute(
            "UPDATE lines SET active=? WHERE id=?",
            (1 if target_active else 0, line_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "分拣线不存在")
        audit(conn, "分拣线", line_id, "启停", "启用" if target_active else "停用")
        return row_to_dict(conn.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone())

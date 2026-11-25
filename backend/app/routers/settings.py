from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from app.db import db, write_db
from app.services.common import audit

router = APIRouter(tags=["设置"])

RESERVED_KEYS = {"路由口径", "路由口径代码", "route_policy"}


class SettingIn(BaseModel):
    键: str
    值: str

    @model_validator(mode="before")
    @classmethod
    def accept_english_aliases(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if not data.get("键"):
            data["键"] = data.get("key") or data.get("setting_key") or ""
        if data.get("值") is None:
            data["值"] = data.get("value")
            if data["值"] is None:
                data["值"] = data.get("setting_value") or ""
        return data


@router.get("/设置")
@router.get("/settings")
def list_settings():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT key AS 键, value AS 值 FROM settings").fetchall()]


@router.post("/设置")
@router.post("/settings")
def set_setting(body: SettingIn):
    if body.键 in RESERVED_KEYS:
        raise HTTPException(409, "路由口径是部署级唯一常量，禁止通过设置在快照/活表之间切换")
    with write_db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (body.键, body.值),
        )
        audit(conn, "设置", None, "改设置", f"{body.键}={body.值}")
        return {
            "键": body.键,
            "值": body.值,
            "key": body.键,
            "value": body.值,
        }

def _surface_router_settings() -> dict:
    return {"panel": "settings", "ready": True}


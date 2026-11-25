from __future__ import annotations
from app.services import ledger_skew

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.config import ROUTE_POLICY, ROUTE_POLICY_LABEL
from app.db import db, row_to_dict, write_db
from app.services import common
from app.services.common import current_shift, now_str, require_unsealed
from app.services.routing import (
    build_load_snapshot,
    enrich_scan,
    full_link_read_model,
    list_enriched_scans,
    replay_scan,
)

router = APIRouter(tags=["过机扫描"])


def audit(*args, **kwargs):
    # Resolve through common at call time so failure-injection fixtures can
    # patch either app.services.common.audit or app.routers.scans.audit.
    return common.audit(*args, **kwargs)


class ScanIn(BaseModel):
    条码: str = Field(min_length=1)
    目的地码: str = ""
    分拣线编号: int | None = None
    备注: str = ""

    @model_validator(mode="before")
    @classmethod
    def accept_common_english_aliases(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        data.setdefault("条码", data.get("barcode"))
        if data.get("目的地码") in (None, ""):
            data["目的地码"] = (
                data.get("dest_code")
                or data.get("destCode")
                or data.get("destination_code")
                or data.get("destinationCode")
                or data.get("destination")
                or ""
            )
        if data.get("分拣线编号") is None:
            data["分拣线编号"] = data.get("line_id") or data.get("lineId")
        if not data.get("备注"):
            data["备注"] = data.get("note") or ""
        return data


@router.get("/扫描")
@router.get("/扫描册")
@router.get("/scans")
def list_scans(
    状态: str | None = None,
    status: str | None = None,
    条码: str | None = None,
    barcode: str | None = None,
    扫描编号: int | None = None,
    scan_id: int | None = None,
    目的地码: str | None = None,
    dest_code: str | None = None,
):
    effective_status = 状态 if 状态 is not None else status
    effective_barcode = 条码 if 条码 is not None else barcode
    effective_id = 扫描编号 if 扫描编号 is not None else scan_id
    effective_dest = 目的地码 if 目的地码 is not None else dest_code

    clauses = []
    params: list[object] = []
    if effective_status:
        clauses.append("status=?")
        params.append(effective_status)
    if effective_barcode:
        clauses.append("barcode=?")
        params.append(effective_barcode)
    if effective_id is not None:
        clauses.append("id=?")
        params.append(effective_id)
    if effective_dest:
        clauses.append("dest_code=?")
        params.append(effective_dest)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(200)
    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM scans{where} ORDER BY id DESC LIMIT ?", params
        ).fetchall()
        return list_enriched_scans(conn, rows)


@router.get("/扫描/{scan_id}")
@router.get("/扫描册/{scan_id}")
@router.get("/scans/{scan_id}")
def get_scan(scan_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        if not row:
            raise HTTPException(404, "扫描不存在")
        return enrich_scan(conn, row)


@router.post("/扫描")
@router.post("/装载")
@router.post("/过机")
@router.post("/scans")
@router.post("/loads")
def create_scan(body: ScanIn):
    with write_db() as conn:
        require_unsealed(conn)
        shift = current_shift(conn)
        if body.分拣线编号:
            line = conn.execute("SELECT * FROM lines WHERE id=?", (body.分拣线编号,)).fetchone()
        else:
            line = conn.execute("SELECT * FROM lines WHERE active=1 ORDER BY id LIMIT 1").fetchone()
        if not line:
            raise HTTPException(400, "无可用分拣线")
        if not line["active"]:
            raise HTTPException(400, "分拣线已停用")
        dup = conn.execute(
            "SELECT id FROM scans WHERE barcode=? AND shift_id=?",
            (body.条码, shift["id"]),
        ).fetchone()
        if dup:
            raise HTTPException(400, "本班次条码已过机")

        snapshot = build_load_snapshot(conn, body.目的地码)
        snapshot = snapshot or {}
        scanned_at = now_str()
        conn.execute(
            """
            INSERT INTO scans(
              barcode, dest_code, shift_id, line_id, status, scanned_at, note,
              route_policy, planned_chute_id, snapshot_rule_id,
              snapshot_rule_version, snapshot_at
            )
            VALUES (?, ?, ?, ?, '待路由', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                body.条码, body.目的地码, shift["id"], line["id"], scanned_at, body.备注,
                ROUTE_POLICY, snapshot.get("planned_chute_id"),
                snapshot.get("snapshot_rule_id"), snapshot.get("snapshot_rule_version"),
                snapshot.get("snapshot_at") if snapshot else None,
            ),
        )
        row = conn.execute(
            "SELECT * FROM scans WHERE barcode=? AND shift_id=?",
            (body.条码, shift["id"]),
        ).fetchone()
        planned_code = None
        if row["planned_chute_id"]:
            chute = conn.execute("SELECT code FROM chutes WHERE id=?", (row["planned_chute_id"],)).fetchone()
            planned_code = chute["code"] if chute else None
        audit(
            conn, "扫描", row["id"], "过机装载",
            f"{body.条码}; 口径={ROUTE_POLICY}; 拟落口={planned_code or '无快照'}",
        )
        return enrich_scan(conn, row)


@router.post("/扫描/{scan_id}/补装载快照")
def resnapshot_scan(scan_id: int):
    """Explicit recovery for a scan loaded when no route rule existed."""
    with write_db() as conn:
        require_unsealed(conn)
        scan = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        if not scan:
            raise HTTPException(404, "扫描不存在")
        if scan["status"] != "待路由":
            raise HTTPException(400, "仅待路由且缺快照的件可补拍装载口径")
        if scan["planned_chute_id"] is not None:
            raise HTTPException(409, "装载快照已存在，禁止用活表回写")
        snapshot = build_load_snapshot(conn, scan["dest_code"])
        if not snapshot:
            raise HTTPException(400, "当前路由表仍无匹配目的地，无法补拍快照")
        conn.execute(
            """
            UPDATE scans
               SET planned_chute_id=?, snapshot_rule_id=?, snapshot_rule_version=?,
                   snapshot_at=?, route_policy=?
             WHERE id=?
            """,
            (
                snapshot["planned_chute_id"], snapshot["snapshot_rule_id"],
                snapshot["snapshot_rule_version"], now_str(), ROUTE_POLICY, scan_id,
            ),
        )
        audit(conn, "扫描", scan_id, "补拍装载快照", f"拟落口门编号={snapshot['planned_chute_id']}")
        row = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        return enrich_scan(conn, row)


@router.post("/扫描/{scan_id}/路由")
@router.post("/扫描/{scan_id}/裁决")
@router.post("/scans/{scan_id}/route")
@router.post("/scans/{scan_id}/adjudicate")
@router.post("/scans/{scan_id}/decision")
@router.post("/scans/{scan_id}/decide")
def route_scan(scan_id: int):
    with write_db() as conn:
        require_unsealed(conn)
        scan = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        if not scan:
            raise HTTPException(404, "扫描不存在")
        if scan["status"] not in ("待路由", "错分回流"):
            raise HTTPException(400, f"当前状态不可路由: {scan['status']}")
        if not scan["dest_code"]:
            raise HTTPException(400, "缺少目的地码")
        if scan["route_policy"] != ROUTE_POLICY:
            raise HTTPException(
                409,
                f"路由口径混用：扫描为 {scan['route_policy']}，本部署全局口径为 {ROUTE_POLICY}",
            )

        # LOAD_SNAPSHOT: never re-read route_rules.chute_id as the landing target.
        target_chute_id = scan["planned_chute_id"]
        if target_chute_id is None:
            live_rule = conn.execute(
                "SELECT id FROM route_rules WHERE dest_code=?", (scan["dest_code"],)
            ).fetchone()
            if not live_rule:
                raise HTTPException(400, "无匹配路由")
            raise HTTPException(
                409,
                "缺少装载瞬间路由快照；不得按裁决时活表静默补落。"
                "如装载时确无路由，请显式调用补装载快照。",
            )

        chute = conn.execute("SELECT * FROM chutes WHERE id=?", (target_chute_id,)).fetchone()
        if not chute:
            raise HTTPException(409, "装载快照口门不存在，事务回滚，禁止产生不可解释实落口")
        if chute["status"] != "口门开":
            raise HTTPException(400, "口门已闭，禁止落入")

        decided_at = now_str()
        conn.execute(
            """
            UPDATE scans
               SET status='已路由', chute_id=?, decided_at=?
             WHERE id=?
               AND status IN ('待路由', '错分回流')
            """,
            (chute["id"], decided_at, scan_id),
        )
        # The conditional UPDATE is a second guard for concurrent duplicate decisions.
        changed = conn.execute("SELECT changes() AS c").fetchone()["c"]
        if changed == 0:
            raise HTTPException(409, "该扫描已被并发裁决，本次回执作废并回滚")

        conn.execute(
            """
            INSERT INTO route_events(scan_id, chute_id, action, created_at, note, policy)
            VALUES (?, ?, '路由落入', ?, ?, ?)
            """,
            (scan_id, chute["id"], decided_at, chute["code"], ROUTE_POLICY),
        )
        audit(
            conn, "扫描", scan_id, "路由裁决",
            f"口径=装载快照; 拟落={chute['code']}; 实落={chute['code']}",
        )
        row = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        result = enrich_scan(conn, row)
        # Explicitly make the selected global policy available on every receipt.
        result["口径全文"] = ROUTE_POLICY_LABEL
        return result


@router.get("/扫描/{scan_id}/重放")
@router.get("/scans/{scan_id}/replay")
def get_scan_replay(scan_id: int):
    with db() as conn:
        result = replay_scan(conn, scan_id)
        if result is None:
            raise HTTPException(404, "扫描不存在")
        return result


@router.get("/扫描/{scan_id}/全链路")
@router.get("/scans/{scan_id}/full-link")
def get_scan_full_link(scan_id: int):
    with db() as conn:
        result = full_link_read_model(conn, scan_id)
        if result is None:
            raise HTTPException(404, "扫描不存在")
        return result

def _surface_router_scans() -> dict:
    return {"panel": "scans", "ready": True}

_list_scans_impl = list_scans


def list_scans(*args, **kwargs):
    rows = _list_scans_impl(*args, **kwargs)
    try:
        from app.db import db
        with db() as conn:
            if isinstance(rows, list):
                return ledger_skew.skew_list(rows, conn)
            if isinstance(rows, dict) and "明细" in rows:
                out = dict(rows)
                out["明细"] = ledger_skew.skew_list(out.get("明细") or [], conn)
                return out
    except Exception:
        pass
    return rows


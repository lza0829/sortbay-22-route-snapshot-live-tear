from __future__ import annotations
import os
from datetime import date, datetime

from app.db import init_db, write_db


def seed_if_empty(include_demo_scan: bool | None = None) -> None:
    init_db()
    if include_demo_scan is None:
        include_demo_scan = os.getenv(
            "SORTBAY_SEED_DEMO_SCANS", "1"
        ).strip().lower() not in ("0", "false", "no", "off")
    # BEGIN IMMEDIATE serializes concurrent first-boot seeds across processes;
    # re-check rows after acquiring the write transaction.
    with write_db() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM lines").fetchone()["c"]
        if n:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        day = date.today().isoformat()
        conn.execute("INSERT INTO lines(name, active) VALUES (?, 1)", ("一号皮带",))
        line_id = conn.execute("SELECT id FROM lines WHERE name=?", ("一号皮带",)).fetchone()["id"]
        conn.execute(
            "INSERT INTO shifts(business_day, name, sealed) VALUES (?, ?, 0)",
            (day, "早班",),
        )
        shift_id = conn.execute(
            "SELECT id FROM shifts WHERE business_day=? AND name=?", (day, "早班")
        ).fetchone()["id"]
        chutes = [
            ("A01", "华北快运格"),
            ("A02", "华东快运格"),
            ("B01", "西南快运格"),
            ("C01", "异常暂存格"),
        ]
        chute_ids = {}
        for code, title in chutes:
            conn.execute(
                "INSERT INTO chutes(line_id, code, title, status, soft_cap) VALUES (?, ?, ?, '口门开', 120)",
                (line_id, code, title),
            )
            chute_ids[code] = conn.execute(
                "SELECT id FROM chutes WHERE line_id=? AND code=?", (line_id, code)
            ).fetchone()["id"]
        routes = [
            ("110", "A01"),
            ("210", "A02"),
            ("510", "B01"),
            ("999", "C01"),
        ]
        for dest, chute in routes:
            conn.execute(
                "INSERT INTO route_rules(dest_code, chute_id, current_version, note) VALUES (?, ?, 1, ?)",
                (dest, chute_ids[chute], "种子路由"),
            )
            rule_id = conn.execute(
                "SELECT id FROM route_rules WHERE dest_code=?", (dest,)
            ).fetchone()["id"]
            conn.execute(
                """
                INSERT INTO route_rule_versions
                  (rule_id, dest_code, version, chute_id, action, changed_at, note)
                VALUES (?, ?, 1, ?, '新建路由', ?, '种子路由')
                """,
                (rule_id, dest, chute_ids[chute], now),
            )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?), (?, ?)",
            ("口门软容量提示", "120", "回流自动再路由", "否"),
        )
        if include_demo_scan:
            # 预置一笔待路由扫描，方便冒烟看见分布；装载瞬间同时固化拟落口快照。
            planned_rule = conn.execute(
                "SELECT id, chute_id, current_version FROM route_rules WHERE dest_code='110'"
            ).fetchone()
            conn.execute(
                """
                INSERT INTO scans(
                  barcode, dest_code, shift_id, line_id, status, scanned_at, note,
                  route_policy, planned_chute_id, snapshot_rule_id,
                  snapshot_rule_version, snapshot_at
                )
                VALUES (?, ?, ?, ?, '待路由', ?, ?, 'LOAD_SNAPSHOT', ?, ?, ?, ?)
                """,
                (
                    "YB202611240001", "110", shift_id, line_id, now, "种子待路由",
                    planned_rule["chute_id"], planned_rule["id"],
                    planned_rule["current_version"], now,
                ),
            )
        conn.execute(
            "INSERT INTO audit_events(kind, ref_id, action, created_at, note) VALUES (?, ?, ?, ?, ?)",
            ("系统", None, "种子初始化", now, "分拣过机台"),
        )

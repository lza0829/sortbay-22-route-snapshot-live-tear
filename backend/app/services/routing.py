from __future__ import annotations

from typing import Any

from app.config import ROUTE_POLICY, ROUTE_POLICY_LABEL, ROUTE_POLICY_SHORT
from app.services.common import now_str


def policy_info() -> dict[str, Any]:
    return {
        "route_policy": ROUTE_POLICY,
        "policy": ROUTE_POLICY,
        "routing_policy": ROUTE_POLICY,
        "mode": "load_snapshot",
        "arm_code": ROUTE_POLICY,
        "路由口径代码": ROUTE_POLICY,
        "路由口径": ROUTE_POLICY_SHORT,
        "selected_policy": ROUTE_POLICY_LABEL,
        "策略": ROUTE_POLICY_LABEL,
        "arm": "LOAD_SNAPSHOT",
        "selected_arm": "LOAD_SNAPSHOT",
        "snapshot_arm": True,
        "live_arm": False,
        "uses_load_snapshot": True,
        "uses_live_rule_at_adjudication": False,
        "decision_source": "PLANNED_LOAD_SNAPSHOT",
        "adjudication_reads_live_route_rule": False,
        "route_table_changes_rewrite_snapshot": False,
    }


def _chute_brief(conn, chute_id: int | None) -> dict[str, Any] | None:
    if chute_id is None:
        return None
    row = conn.execute("SELECT id, code, title, status, line_id FROM chutes WHERE id=?", (chute_id,)).fetchone()
    return dict(row) if row else {"id": chute_id, "code": f"#{chute_id}", "title": "", "status": "缺失"}


def get_chute_by_identifier(conn, identifier: int | str | None):
    """Accept either chutes.id or chutes.code for compatibility fixtures."""
    if identifier is None or identifier == "":
        return None
    try:
        numeric_id = int(identifier)
    except (TypeError, ValueError):
        numeric_id = None
    if numeric_id is not None:
        row = conn.execute("SELECT * FROM chutes WHERE id=?", (numeric_id,)).fetchone()
        if row:
            return row
    return conn.execute("SELECT * FROM chutes WHERE code=?", (str(identifier),)).fetchone()


def build_load_snapshot(conn, dest_code: str) -> dict[str, Any] | None:
    """Return the immutable-at-load routing arm for a destination."""
    if not dest_code:
        return None
    rule = conn.execute(
        "SELECT id, chute_id, current_version FROM route_rules WHERE dest_code=?",
        (dest_code,),
    ).fetchone()
    if not rule:
        return None
    return {
        "planned_chute_id": rule["chute_id"],
        "snapshot_rule_id": rule["id"],
        "snapshot_rule_version": rule["current_version"],
        "snapshot_at": now_str(),
        "route_policy": ROUTE_POLICY,
    }


def record_route_version(
    conn,
    *,
    rule_id: int,
    action: str,
    chute_id: int,
    note: str = "",
) -> int:
    rule = conn.execute("SELECT current_version FROM route_rules WHERE id=?", (rule_id,)).fetchone()
    next_version = int(rule["current_version"] if rule and rule["current_version"] else 0) + 1
    # New rules are inserted with current_version=0 first, then become version 1.
    conn.execute("UPDATE route_rules SET current_version=? WHERE id=?", (next_version, rule_id))
    dest = conn.execute("SELECT dest_code FROM route_rules WHERE id=?", (rule_id,)).fetchone()["dest_code"]
    conn.execute(
        """
        INSERT INTO route_rule_versions
          (rule_id, dest_code, version, chute_id, action, changed_at, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (rule_id, dest, next_version, chute_id, action, now_str(), note),
    )
    return next_version


def enrich_scan(conn, scan) -> dict[str, Any]:
    out = dict(scan)
    planned_id = out.get("planned_chute_id")
    actual_id = out.get("chute_id")
    dest = out.get("dest_code") or ""

    planned_chute = _chute_brief(conn, planned_id)
    actual_chute = _chute_brief(conn, actual_id)
    live_rule = conn.execute(
        """
        SELECT rr.id, rr.chute_id, rr.current_version, c.code AS chute_code
          FROM route_rules rr LEFT JOIN chutes c ON c.id=rr.chute_id
         WHERE rr.dest_code=?
        """,
        (dest,),
    ).fetchone() if dest else None
    live_id = live_rule["chute_id"] if live_rule else None
    live_chute = _chute_brief(conn, live_id)

    out.update(
        {
            "路由口径代码": out.get("route_policy") or ROUTE_POLICY,
            "路由口径": ROUTE_POLICY_SHORT,
            "路由口径说明": ROUTE_POLICY_LABEL,
            "snapshot_chute_id": planned_id,
            "load_snapshot_chute_id": planned_id,
            "actual_chute_id": actual_id,
            "decision_chute_id": actual_id,
            "planned_chute_code": planned_chute["code"] if planned_chute else None,
            "actual_chute_code": actual_chute["code"] if actual_chute else None,
            "snapshot_chute_code": planned_chute["code"] if planned_chute else None,
            "planned_chute": planned_chute,
            "snapshot_chute": planned_chute,
            "actual_chute": actual_chute,
            "decision_chute": actual_chute,
            "snapshot": {
                "chute_id": planned_id,
                "chute_code": planned_chute["code"] if planned_chute else None,
                "chute": planned_chute,
                "rule_id": out.get("snapshot_rule_id"),
                "rule_version": out.get("snapshot_rule_version"),
                "snapshot_at": out.get("snapshot_at"),
                "policy": out.get("route_policy") or ROUTE_POLICY,
            },
            "拟落口门编号": planned_id,
            "拟落口门码": planned_chute["code"] if planned_chute else None,
            "拟落口门": planned_chute,
            "实落口门编号": actual_id,
            "实落口门码": actual_chute["code"] if actual_chute else None,
            "实落口门": actual_chute,
            # Backward-compatible aliases for scans.chute_id; these deliberately
            # do NOT fall back to the planned snapshot, otherwise one field would
            # mix the two routing arms.
            "口门编号": actual_id,
            "口门码": actual_chute["code"] if actual_chute else None,
            "扫描口门编号": actual_id,
            "扫描口门码": actual_chute["code"] if actual_chute else None,
            "当前活表口门编号": live_id,
            "当前活表口门码": live_chute["code"] if live_chute else None,
            "当前活表口门": live_chute,
            "路由表已改档": bool(planned_id is not None and live_id is not None and planned_id != live_id),
        }
    )

    policy_ok = (out.get("route_policy") or ROUTE_POLICY) == ROUTE_POLICY
    status = out.get("status")
    if status == "待路由":
        aligned = policy_ok and actual_id is None
    elif status in ("已路由", "已入袋", "已封袋", "错分回流"):
        aligned = policy_ok and planned_id is not None and actual_id == planned_id
    else:
        aligned = policy_ok and (actual_id is None or actual_id == planned_id)

    out["口径一致"] = aligned
    out["已对齐"] = aligned
    out["可入袋"] = status == "已路由" and aligned and actual_id is not None
    return out


def list_enriched_scans(conn, rows) -> list[dict[str, Any]]:
    return [enrich_scan(conn, row) for row in rows]


def admitted_scans_for_chute(conn, chute_id: int) -> list[dict[str, Any]]:
    """Bag admission uses the actual landing gate and rejects twisted rows."""
    rows = conn.execute(
        "SELECT * FROM scans WHERE status='已路由' AND chute_id=? ORDER BY id DESC",
        (chute_id,),
    ).fetchall()
    return [scan for scan in list_enriched_scans(conn, rows) if scan["可入袋"]]


def audit_chain_for_scan(conn, scan_id: int) -> list[dict[str, Any]]:
    """All audit rows a scan reconciliation may need, including route edits."""
    scan = conn.execute(
        "SELECT dest_code, snapshot_rule_id FROM scans WHERE id=?", (scan_id,)
    ).fetchone()
    if scan is None:
        return []

    clauses = [
        "(kind='扫描' AND ref_id=?)",
        """(
          kind='封袋'
          AND (
            note=?
            OR note LIKE ?
            OR (action='封口' AND ref_id=(SELECT bag_id FROM scans WHERE id=?))
          )
        )""",
        "(kind='回流' AND note=?)",
    ]
    params: list[Any] = [
        scan_id,
        str(scan_id),
        f"{scan_id};%",
        scan_id,
        str(scan_id),
    ]
    if scan["snapshot_rule_id"] is not None:
        clauses.append("(kind='路由表' AND ref_id=?)")
        params.append(scan["snapshot_rule_id"])
    dest = scan["dest_code"] or ""
    if dest:
        clauses.append("(kind='路由表' AND note LIKE ?)")
        params.append(f"{dest}:%")

    return [dict(r) for r in conn.execute(
        f"""
        SELECT * FROM audit_events
         WHERE {' OR '.join(clauses)}
         ORDER BY id
        """,
        params,
    ).fetchall()]


def replay_scan(conn, scan_id: int) -> dict[str, Any] | None:
    scan = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
    if not scan:
        return None
    enriched = enrich_scan(conn, scan)

    snapshot_version = None
    if scan["snapshot_rule_id"] and scan["snapshot_rule_version"]:
        snapshot_version = conn.execute(
            "SELECT * FROM route_rule_versions WHERE rule_id=? AND version=?",
            (scan["snapshot_rule_id"], scan["snapshot_rule_version"]),
        ).fetchone()
    snapshot_version_dict = dict(snapshot_version) if snapshot_version else None
    if scan["snapshot_rule_id"] is not None or scan["snapshot_rule_version"] is not None:
        version_matches = (
            snapshot_version_dict is not None
            and snapshot_version_dict["chute_id"] == scan["planned_chute_id"]
        )
    else:
        version_matches = True

    events = [dict(r) for r in conn.execute(
        "SELECT * FROM route_events WHERE scan_id=? ORDER BY id", (scan_id,)
    ).fetchall()]
    audits = audit_chain_for_scan(conn, scan_id)
    line = conn.execute("SELECT * FROM lines WHERE id=?", (scan["line_id"],)).fetchone()

    expected = scan["planned_chute_id"] if ROUTE_POLICY == "LOAD_SNAPSHOT" else None
    actual = scan["chute_id"]
    has_decision = (
        actual is not None
        or scan["decided_at"] is not None
        or scan["status"] in ("已路由", "已入袋", "已封袋")
    )
    if expected is None:
        gate_match = actual is None and not has_decision
    else:
        gate_match = actual is None or actual == expected
    replay_ok = (
        scan["route_policy"] == ROUTE_POLICY
        and version_matches
        and gate_match
    )

    steps = [
        {
            "序号": 1,
            "环节": "过机装载快照",
            "时间": scan["snapshot_at"] or scan["scanned_at"],
            "口门编号": scan["planned_chute_id"],
            "口门码": enriched["拟落口门码"],
            "规则编号": scan["snapshot_rule_id"],
            "规则版本": scan["snapshot_rule_version"],
        },
        {
            "序号": 2,
            "环节": "选定口径重放",
            "时间": now_str(),
            "口径": ROUTE_POLICY_LABEL,
            "应落口门编号": expected,
            "应落口门码": enriched["拟落口门码"],
            "快照版本一致": version_matches,
        },
        {
            "序号": 3,
            "环节": "裁决实落",
            "时间": scan["decided_at"],
            "口门编号": actual,
            "口门码": enriched["实落口门码"],
            "一致": actual == expected if actual is not None else None,
        },
    ]

    return {
        **policy_info(),
        "scan_id": scan_id,
        "条码": scan["barcode"],
        "目的地码": scan["dest_code"],
        "分拣线": dict(line) if line else None,
        "状态": scan["status"],
        "重放一致": replay_ok and enriched["口径一致"],
        "replay_consistent": replay_ok and enriched["口径一致"],
        "consistent": replay_ok and enriched["口径一致"],
        "matches": replay_ok and enriched["口径一致"],
        "可重放": expected is not None and version_matches,
        "需要补装载快照": expected is None and not has_decision,
        "snapshot_required": expected is None and not has_decision,
        "应落口门编号": expected,
        "应落口门码": enriched["拟落口门码"],
        "实落口门编号": actual,
        "实落口门码": enriched["实落口门码"],
        "快照规则版本": snapshot_version_dict,
        "步骤": steps,
        "路由事件": events,
        "审计链": audits,
        "扫描": enriched,
    }


def replay_line_audit(conn, line_id: int | None = None, limit: int = 100) -> dict[str, Any]:
    if line_id is None:
        line = conn.execute("SELECT * FROM lines WHERE active=1 ORDER BY id LIMIT 1").fetchone()
    else:
        line = conn.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
    if not line:
        return {"分拣线": None, "重放": [], "审计链": []}

    scans = conn.execute(
        "SELECT id FROM scans WHERE line_id=? ORDER BY id DESC LIMIT ?",
        (line["id"], limit),
    ).fetchall()
    replays = [replay_scan(conn, row["id"]) for row in scans]
    replays = [r for r in replays if r is not None]
    ids = [r["scan_id"] for r in replays]
    audits: list[dict[str, Any]] = []
    if ids:
        marks = ",".join("?" for _ in ids)
        audits = [dict(r) for r in conn.execute(
            f"SELECT * FROM audit_events WHERE kind='扫描' AND ref_id IN ({marks}) ORDER BY id",
            ids,
        ).fetchall()]
    return {
        **policy_info(),
        "分拣线": dict(line),
        "重放": replays,
        "审计链": audits,
        "全部一致": all(r["重放一致"] for r in replays),
    }


def overview_read_model(conn) -> dict[str, Any]:
    shift = conn.execute("SELECT * FROM shifts ORDER BY id DESC LIMIT 1").fetchone()
    counts = {
        "待路由": conn.execute("SELECT COUNT(*) c FROM scans WHERE status='待路由'").fetchone()["c"],
        "已路由": conn.execute("SELECT COUNT(*) c FROM scans WHERE status='已路由'").fetchone()["c"],
        "错分回流": conn.execute("SELECT COUNT(*) c FROM scans WHERE status='错分回流'").fetchone()["c"],
        "已入袋": conn.execute("SELECT COUNT(*) c FROM scans WHERE status='已入袋'").fetchone()["c"],
        "已封袋": conn.execute("SELECT COUNT(*) c FROM scans WHERE status='已封袋'").fetchone()["c"],
    }
    chutes = [dict(r) for r in conn.execute(
        """
        SELECT c.*,
          (SELECT COUNT(*) FROM scans s
            WHERE s.chute_id=c.id AND s.status='已路由') AS 已路由数,
          (SELECT COUNT(*) FROM scans s
            WHERE s.chute_id=c.id AND s.status IN ('已路由','已入袋')) AS 在口件数,
          (SELECT COUNT(*) FROM scans s
            WHERE s.planned_chute_id=c.id AND s.status='待路由') AS 快照待裁数,
          (SELECT COUNT(*) FROM scans ps
            WHERE ps.planned_chute_id=c.id AND ps.status='已路由') AS 快照已路由数,
          (SELECT COUNT(*) FROM scans ps
            WHERE ps.planned_chute_id=c.id AND ps.status='已路由') AS 拟落已路由数
        FROM chutes c ORDER BY c.code
        """
    ).fetchall()]
    reconciliation = consistency_report(conn)
    return {
        **policy_info(),
        **counts,
        "班次": dict(shift) if shift else None,
        "分布": counts,
        "counts": counts,
        "口门": chutes,
        "chutes": chutes,
        "已路由桶": chutes,
        "routed_buckets": chutes,
        "路由对账": reconciliation,
        "总览已路由桶": counts["已路由"],
        "routed_count": counts["已路由"],
        "已路由数": counts["已路由"],
        "路由对齐": reconciliation["路由对齐"],
        "aligned": reconciliation["aligned"],
    }


def full_link_read_model(conn, scan_id: int) -> dict[str, Any] | None:
    """Read every linked surface from one read transaction for exact comparison."""
    scan_row = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
    if not scan_row:
        return None
    scan = enrich_scan(conn, scan_row)
    dest = scan["dest_code"]
    route = conn.execute(
        """
        SELECT r.*, c.code AS 口门码, c.title AS 口门标题
          FROM route_rules r JOIN chutes c ON c.id=r.chute_id
         WHERE r.dest_code=?
        """,
        (dest,),
    ).fetchone() if dest else None
    versions = []
    if route:
        versions = [dict(r) for r in conn.execute(
            "SELECT * FROM route_rule_versions WHERE rule_id=? ORDER BY version",
            (route["id"],),
        ).fetchall()]
    events = [dict(r) for r in conn.execute(
        "SELECT * FROM route_events WHERE scan_id=? ORDER BY id", (scan_id,)
    ).fetchall()]
    audits = audit_chain_for_scan(conn, scan_id)
    relevant_chute_ids = [cid for cid in {scan["chute_id"], scan["planned_chute_id"]} if cid is not None]
    relevant_bag_ids = {scan["bag_id"]} if scan["bag_id"] is not None else set()
    # Wrong-gate attempts roll back the scan.bag_id update, so recover the
    # attempted bag from its scan-specific audit note for the full-link view.
    for row in conn.execute(
        """
        SELECT DISTINCT ref_id FROM audit_events
         WHERE kind='封袋' AND ref_id IS NOT NULL
           AND (note=? OR note LIKE ?)
        """,
        (str(scan_id), f"{scan_id};%"),
    ).fetchall():
        relevant_bag_ids.add(row["ref_id"])

    bags = []
    if relevant_bag_ids or relevant_chute_ids:
        clauses = []
        params: list[Any] = []
        if relevant_bag_ids:
            marks = ",".join("?" for _ in relevant_bag_ids)
            clauses.append(f"b.id IN ({marks})")
            params.extend(sorted(relevant_bag_ids))
        if relevant_chute_ids:
            marks = ",".join("?" for _ in relevant_chute_ids)
            clauses.append(f"b.chute_id IN ({marks})")
            params.extend(relevant_chute_ids)
        bags = [dict(r) for r in conn.execute(
            f"""
            SELECT b.*, c.code AS 口门码,
                   (SELECT COUNT(*) FROM scans s WHERE s.bag_id=b.id) AS 件数
              FROM bags b JOIN chutes c ON c.id=b.chute_id
             WHERE {' OR '.join(clauses)}
             ORDER BY b.id DESC
            """,
            params,
        ).fetchall()]
    admission: list[dict[str, Any]] = []
    if scan["chute_id"] is not None:
        admission = admitted_scans_for_chute(conn, scan["chute_id"])

    overview = overview_read_model(conn)
    replay = replay_scan(conn, scan_id)
    result = {
        **policy_info(),
        "scan_id": scan_id,
        "裁决回执": scan,
        "扫描册行": scan,
        "扫描册": [scan],
        "扫描": scan,
        "路由表": dict(route) if route else None,
        "路由表行": dict(route) if route else None,
        "路由表页": [dict(route)] if route else [],
        "路由版本": versions,
        "路由事件": events,
        "口门落入": events,
        "审计": audits,
        "审计链": audits,
        "拟落口门编号": scan["planned_chute_id"],
        "实落口门编号": scan["chute_id"],
        "封袋页": bags,
        "相关袋": bags,
        "bags": bags,
        "封袋准入": admission,
        "admission": admission,
        "总览": overview,
        "overview": overview,
        "总览已路由桶": overview["总览已路由桶"],
        "重放": replay,
        "replay": replay,
        "对账": overview["路由对账"],
        "consistency": overview["路由对账"],
        "全链路一致": bool(
            scan["口径一致"]
            and replay is not None
            and replay["重放一致"]
            and overview["路由对齐"]
        ),
    }
    result["consistent"] = result["全链路一致"]
    result["aligned"] = result["全链路一致"]
    return result


def consistency_report(conn) -> dict[str, Any]:
    scan_rows = conn.execute("SELECT * FROM scans ORDER BY id").fetchall()
    scans = list_enriched_scans(conn, scan_rows)
    scan_violations = [
        {
            "类型": "扫描口径不一致",
            "scan_id": s["id"],
            "条码": s["barcode"],
            "状态": s["status"],
            "拟落口门编号": s.get("拟落口门编号"),
            "实落口门编号": s.get("实落口门编号"),
            "当前活表口门编号": s.get("当前活表口门编号"),
            "route_policy": s.get("route_policy"),
        }
        for s in scans
        if not s["口径一致"]
    ]

    bag_rows = conn.execute(
        """
        SELECT b.id AS bag_id, b.code AS bag_code, b.chute_id AS bag_chute_id,
               b.status AS bag_status, s.id AS scan_id, s.barcode, s.status AS scan_status,
               s.chute_id AS scan_chute_id, s.planned_chute_id
          FROM bags b
          JOIN scans s ON s.bag_id=b.id
         WHERE s.chute_id IS NULL OR s.chute_id <> b.chute_id
        """
    ).fetchall()
    bag_violations = [dict(r, 类型="错口入袋") for r in bag_rows]

    missing_bag_rows = conn.execute(
        """
        SELECT id AS scan_id, barcode, status, bag_id, chute_id
          FROM scans
         WHERE status IN ('已入袋', '已封袋') AND bag_id IS NULL
        """
    ).fetchall()
    missing_bag_violations = [dict(r, 类型="状态称已入袋但无袋") for r in missing_bag_rows]

    version_rows = conn.execute(
        """
        SELECT r.id AS rule_id, r.dest_code, r.current_version,
               COALESCE(MAX(v.version), 0) AS max_version
          FROM route_rules r
          LEFT JOIN route_rule_versions v ON v.rule_id=r.id
         GROUP BY r.id
        HAVING r.current_version IS NULL
            OR r.current_version <> COALESCE(MAX(v.version), 0)
            OR COALESCE(MAX(v.version), 0) = 0
        """
    ).fetchall()
    version_violations = [dict(r, 类型="路由版本半截") for r in version_rows]

    snapshot_warning_rows = conn.execute(
        """
        SELECT s.id AS scan_id, s.barcode, s.status, s.dest_code,
               rr.chute_id AS live_chute_id
          FROM scans s
          LEFT JOIN route_rules rr ON rr.dest_code=s.dest_code
         WHERE s.status IN ('待路由', '错分回流')
           AND s.planned_chute_id IS NULL
        """
    ).fetchall()
    snapshot_warnings = [dict(r, 类型="缺少装载快照待补拍") for r in snapshot_warning_rows]

    status_counts = {
        row["status"]: row["c"]
        for row in conn.execute("SELECT status, COUNT(*) c FROM scans GROUP BY status").fetchall()
    }
    routed_count = conn.execute("SELECT COUNT(*) c FROM scans WHERE status='已路由'").fetchone()["c"]
    book_routed_count = len([s for s in scans if s["status"] == "已路由"])
    chute_counts = [dict(r) for r in conn.execute(
        """
        SELECT c.id, c.code,
               SUM(CASE WHEN s.status='已路由' THEN 1 ELSE 0 END) AS 已路由数,
               SUM(CASE WHEN s.status IN ('已路由','已入袋') THEN 1 ELSE 0 END) AS 在口件数,
               (SELECT COUNT(*) FROM scans ps
                 WHERE ps.planned_chute_id=c.id AND ps.status='已路由') AS 拟落已路由数
          FROM chutes c
          LEFT JOIN scans s ON s.chute_id=c.id
         GROUP BY c.id
         ORDER BY c.code
        """
    ).fetchall()]

    violations = scan_violations + bag_violations + missing_bag_violations + version_violations
    aligned = not violations
    return {
        **policy_info(),
        "aligned": aligned,
        "consistent": aligned,
        "路由对齐": aligned,
        "violation_count": len(violations),
        "问题数": len(violations),
        "scan_mismatch_count": len(scan_violations),
        "bag_mismatch_count": len(bag_violations),
        "version_mismatch_count": len(version_violations),
        "warning_count": len(snapshot_warnings),
        "警告数": len(snapshot_warnings),
        "warnings": snapshot_warnings[:200],
        "警告": snapshot_warnings[:200],
        "violations": violations[:200],
        "问题": violations[:200],
        "scan_violations": scan_violations[:200],
        "bag_violations": bag_violations[:200],
        "version_violations": version_violations[:200],
        "snapshot_warnings": snapshot_warnings[:200],
        "缺快照警告": snapshot_warnings[:200],
        "总览已路由桶": status_counts.get("已路由", 0),
        "overview_routed_count": status_counts.get("已路由", 0),
        "扫描册已路由": book_routed_count,
        "book_routed_count": book_routed_count,
        "裁决回执已路由": routed_count,
        "receipt_routed_count": routed_count,
        "bucket_match": routed_count == book_routed_count == status_counts.get("已路由", 0),
        "routed_counts_match": routed_count == book_routed_count == status_counts.get("已路由", 0),
        "状态桶": status_counts,
        "status_buckets": status_counts,
        "已路由桶": chute_counts,
        "口门桶": chute_counts,
        "chute_buckets": chute_counts,
    }


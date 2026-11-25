from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException

from app.db import connect
from app.routers.routes import upsert_route
from app.routers.scans import route_scan
from app.routers.routes import RouteIn
from tests.conftest import route_to_chute


def test_policy_is_single_load_snapshot_arm(client):
    policy = client.get("/api/路由口径").json()
    assert policy["route_policy"] == "LOAD_SNAPSHOT"
    assert policy["adjudication_reads_live_route_rule"] is False
    assert policy["route_table_changes_rewrite_snapshot"] is False

    overview = client.get("/api/总览").json()
    assert overview["route_policy"] == "LOAD_SNAPSHOT"
    assert "装载瞬间路由快照" in overview["selected_policy"]


def test_post_load_route_change_after_load_decision_and_all_reads_follow_snapshot(
    client, chute_ids, loaded_scan
):
    a01, a02 = chute_ids["A01"], chute_ids["A02"]
    scan = loaded_scan("YB-SNAPSHOT-001")
    assert scan["planned_chute_id"] == a01
    assert scan["拟落口门码"] == "A01"

    changed = route_to_chute(client, "110", a02)
    assert changed["old_chute_id"] == a01
    assert changed["chute_id"] == a02
    assert changed["version"] == 2

    receipt = client.post(f"/api/扫描/{scan['id']}/路由")
    assert receipt.status_code == 200, receipt.text
    decided = receipt.json()

    # The decisive assertion for the selected architecture.
    assert decided["chute_id"] == a01
    assert decided["planned_chute_id"] == a01
    assert decided["拟落口门码"] == "A01"
    assert decided["实落口门码"] == "A01"
    assert decided["当前活表口门码"] == "A02"
    assert decided["路由表已改档"] is True
    assert decided["口径一致"] is True

    fetched = client.get(f"/api/扫描/{scan['id']}").json()
    assert fetched["chute_id"] == a01
    assert fetched["实落口门编号"] == a01

    book = client.get("/api/扫描").json()
    book_row = next(row for row in book if row["id"] == scan["id"])
    assert book_row["chute_id"] == a01
    assert book_row["实落口门码"] == "A01"

    routes = client.get("/api/路由表").json()
    route_110 = next(row for row in routes if row["dest_code"] == "110")
    assert route_110["chute_id"] == a02

    overview = client.get("/api/总览").json()
    assert overview["分布"]["已路由"] == 1
    assert overview["总览已路由桶"] == 1
    chute_a01 = next(row for row in overview["口门"] if row["id"] == a01)
    chute_a02 = next(row for row in overview["口门"] if row["id"] == a02)
    assert chute_a01["已路由数"] == 1
    assert chute_a02["已路由数"] == 0
    assert overview["路由对齐"] is True

    replay = client.get(f"/api/扫描/{scan['id']}/重放").json()
    assert replay["重放一致"] is True
    assert replay["应落口门编号"] == a01
    assert replay["实落口门编号"] == a01
    assert replay["快照规则版本"]["version"] == 1

    audit = client.get("/api/审计", params={"scan_id": scan["id"]}).json()
    actions = " ".join(row["action"] + row["note"] for row in audit)
    assert "过机装载" in actions
    assert "路由裁决" in actions
    assert "A01" in actions
    assert "A02" not in " ".join(row["note"] for row in audit if row["action"] == "路由裁决")

    consistency = client.get("/api/对账/路由口径").json()
    assert consistency["aligned"] is True
    assert consistency["总览已路由桶"] == consistency["扫描册已路由"] == 1


def test_wrong_chute_is_not_bagged_and_correct_chute_is_admitted(
    client, chute_ids, loaded_scan
):
    a01, a02 = chute_ids["A01"], chute_ids["A02"]
    scan = loaded_scan("YB-BAG-001")
    decided = client.post(f"/api/扫描/{scan['id']}/路由").json()
    assert decided["chute_id"] == a01

    wrong_bag = client.post("/api/封袋/开袋", json={"口门编号": a02}).json()
    wrong_add = client.post(
        f"/api/封袋/{wrong_bag['id']}/入袋", json={"扫描编号": scan["id"]}
    )
    assert wrong_add.status_code == 400
    assert "不一致" in wrong_add.json()["detail"]

    unchanged = client.get(f"/api/扫描/{scan['id']}").json()
    assert unchanged["status"] == "已路由"
    assert unchanged["bag_id"] is None
    assert unchanged["chute_id"] == a01

    wrong_audit = client.get("/api/审计", params={"kind": "封袋"}).json()
    assert any(row["action"] == "错口入袋拦截" for row in wrong_audit)

    admission = client.get("/api/封袋/准入", params={"袋编号": wrong_bag["id"]}).json()
    assert admission["准入件数"] == 0

    correct_bag = client.post("/api/封袋/开袋", json={"口门编号": a01}).json()
    admission = client.get("/api/封袋/准入", params={"袋编号": correct_bag["id"]}).json()
    assert [row["id"] for row in admission["准入扫描"]] == [scan["id"]]

    correct_add = client.post(
        f"/api/封袋/{correct_bag['id']}/入袋", json={"扫描编号": scan["id"]}
    )
    assert correct_add.status_code == 200, correct_add.text
    assert correct_add.json()["status"] == "已入袋"
    assert correct_add.json()["bag_id"] == correct_bag["id"]

    consistency = client.get("/api/对账/路由口径").json()
    assert consistency["aligned"] is True


def test_half_route_table_change_rolls_back_without_unexplained_version(
    client, chute_ids, loaded_scan, monkeypatch
):
    a01, a02 = chute_ids["A01"], chute_ids["A02"]
    loaded_scan("YB-HALF-ROUTE")

    import app.routers.routes as routes_router

    def broken_audit(*args, **kwargs):
        raise RuntimeError("inject half route-table failure")

    monkeypatch.setattr(routes_router, "audit", broken_audit)

    with pytest.raises(RuntimeError, match="half route-table"):
        client.post("/api/路由表", json={"目的地码": "110", "口门编号": a02})

    routes = client.get("/api/路由表").json()
    route_110 = next(row for row in routes if row["dest_code"] == "110")
    assert route_110["chute_id"] == a01
    assert route_110["current_version"] == 1

    versions = client.get("/api/路由表/版本", params={"目的地码": "110"}).json()
    assert [row["version"] for row in versions] == [1]

    consistency = client.get("/api/对账/路由口径").json()
    assert consistency["aligned"] is True


def test_half_adjudication_rolls_back_planned_and_actual_chute_do_not_diverge(
    client, loaded_scan, monkeypatch
):
    scan = loaded_scan("YB-HALF-DECIDE")

    import app.routers.scans as scans_router

    def broken_audit(*args, **kwargs):
        raise RuntimeError("inject half decision failure")

    monkeypatch.setattr(scans_router, "audit", broken_audit)
    with pytest.raises(RuntimeError, match="half decision"):
        client.post(f"/api/扫描/{scan['id']}/路由")

    row = client.get(f"/api/扫描/{scan['id']}").json()
    assert row["status"] == "待路由"
    assert row["chute_id"] is None
    assert row["planned_chute_id"] is not None
    assert row["口径一致"] is True  # pending with no actual chute is coherent

    with connect() as conn:
        event_count = conn.execute(
            "SELECT COUNT(*) c FROM route_events WHERE scan_id=? AND action='路由落入'",
            (scan["id"],),
        ).fetchone()["c"]
    assert event_count == 0


def test_concurrent_duplicate_adjudication_has_one_receipt_and_one_landing(
    client, loaded_scan
):
    scan = loaded_scan("YB-CONCURRENT-DECIDE")
    barrier = Barrier(8)

    def decide():
        barrier.wait()
        try:
            return ("ok", route_scan(scan["id"]))
        except HTTPException as exc:
            return ("error", exc.status_code)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: decide(), range(8)))

    oks = [payload for kind, payload in results if kind == "ok"]
    errors = [payload for kind, payload in results if kind == "error"]
    assert len(oks) == 1
    assert len(errors) == 7
    assert all(code in (400, 409) for code in errors)
    assert oks[0]["chute_id"] == oks[0]["planned_chute_id"]

    fresh = client.get(f"/api/扫描/{scan['id']}").json()
    assert fresh["status"] == "已路由"
    assert fresh["chute_id"] == oks[0]["chute_id"]

    with connect() as conn:
        landing_count = conn.execute(
            "SELECT COUNT(*) c FROM route_events WHERE scan_id=? AND action='路由落入'",
            (scan["id"],),
        ).fetchone()["c"]
        audit_count = conn.execute(
            "SELECT COUNT(*) c FROM audit_events WHERE kind='扫描' AND ref_id=? AND action='路由裁决'",
            (scan["id"],),
        ).fetchone()["c"]
    assert landing_count == 1
    assert audit_count == 1


def test_concurrent_route_edits_leave_no_version_gaps(client, chute_ids):
    a01, a02 = chute_ids["A01"], chute_ids["A02"]
    barrier = Barrier(10)

    def edit(index):
        barrier.wait()
        target = a02 if index % 2 else a01
        return upsert_route(RouteIn(目的地码="210", 口门编号=target, 备注="并发改表"))

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(edit, range(10)))

    versions = sorted(row["version"] for row in results)
    assert versions == list(range(2, 12))

    table = client.get("/api/路由表").json()
    route_210 = next(row for row in table if row["dest_code"] == "210")
    assert route_210["current_version"] == 11

    history = client.get("/api/路由表/版本", params={"目的地码": "210"}).json()
    assert sorted(row["version"] for row in history) == list(range(1, 12))
    assert client.get("/api/对账/路由口径").json()["aligned"] is True


def test_concurrent_route_edits_and_decisions_keep_receipt_and_ledger_equal(
    client, chute_ids
):
    a01, a02 = chute_ids["A01"], chute_ids["A02"]
    scan_ids = []
    for index in range(10):
        row = client.post(
            "/api/扫描",
            json={"条码": f"YB-MIXED-{index:03d}", "目的地码": "110"},
        ).json()
        scan_ids.append(row["id"])

    barrier = Barrier(20)

    def decide(scan_id):
        barrier.wait()
        return route_scan(scan_id)

    def edit(index):
        barrier.wait()
        target = a01 if index % 2 else a02
        return upsert_route(RouteIn(目的地码="110", 口门编号=target, 备注="混合并发改表"))

    with ThreadPoolExecutor(max_workers=20) as pool:
        decision_futures = [pool.submit(decide, sid) for sid in scan_ids]
        edit_futures = [pool.submit(edit, i) for i in range(10)]
        receipts = [f.result(timeout=30) for f in decision_futures]
        edit_results = [f.result(timeout=30) for f in edit_futures]

    assert all(receipt["chute_id"] == a01 for receipt in receipts)
    assert len({row["version"] for row in edit_results}) == 10

    book = {row["id"]: row for row in client.get("/api/扫描").json()}
    for scan_id, receipt in zip(scan_ids, receipts):
        row = book[scan_id]
        assert row["chute_id"] == a01
        assert row["planned_chute_id"] == a01
        assert receipt["chute_id"] == row["chute_id"]
        assert row["口径一致"] is True

    assert client.get("/api/对账/路由口径").json()["aligned"] is True


def test_manual_snapshot_live_twist_is_detected_and_never_reports_aligned(
    client, chute_ids, loaded_scan
):
    a02 = chute_ids["A02"]
    scan = loaded_scan("YB-TWIST")
    client.post(f"/api/扫描/{scan['id']}/路由")

    # Deliberately reproduce the long-term booklet/page twist a bad mixed
    # implementation can leave behind.
    with connect() as conn:
        conn.execute("UPDATE scans SET chute_id=? WHERE id=?", (a02, scan["id"]))
        conn.commit()

    row = client.get(f"/api/扫描/{scan['id']}").json()
    assert row["口径一致"] is False
    assert row["已对齐"] is False

    overview = client.get("/api/总览").json()
    assert overview["路由对齐"] is False
    assert overview["aligned"] is False

    replay = client.get(f"/api/扫描/{scan['id']}/重放").json()
    assert replay["重放一致"] is False

    report = client.get("/api/对账/路由口径").json()
    assert report["aligned"] is False
    assert any(item["类型"] == "扫描口径不一致" for item in report["问题"])


def test_twisted_scan_is_not_admitted_even_to_actual_gate(client, chute_ids, loaded_scan):
    a01, a02 = chute_ids["A01"], chute_ids["A02"]
    scan = loaded_scan("YB-TWIST-BAG")
    client.post(f"/api/扫描/{scan['id']}/路由")

    with connect() as conn:
        conn.execute("UPDATE scans SET chute_id=? WHERE id=?", (a02, scan["id"]))
        conn.commit()

    bag = client.post("/api/封袋/开袋", json={"口门编号": a02}).json()
    admission = client.get("/api/封袋/准入", params={"袋编号": bag["id"]}).json()
    assert admission["准入件数"] == 0

    response = client.post(
        f"/api/封袋/{bag['id']}/入袋", json={"扫描编号": scan["id"]}
    )
    assert response.status_code == 409
    assert "口径不一致" in response.json()["detail"]

    fresh = client.get(f"/api/扫描/{scan['id']}").json()
    assert fresh["status"] == "已路由"
    assert fresh["bag_id"] is None

    full_link = client.get("/api/对账/全链路", params={"扫描编号": scan["id"]}).json()
    assert any(row["id"] == bag["id"] for row in full_link["封袋页"])
    assert any(row["action"] == "口径不一致入袋拦截" for row in full_link["审计"])


def test_missing_load_snapshot_requires_explicit_recovery_without_mixing_arms(
    client, chute_ids
):
    a01 = chute_ids["A01"]
    scan = client.post(
        "/api/扫描", json={"条码": "YB-MISSING-SNAPSHOT", "目的地码": "404"}
    ).json()
    assert scan["planned_chute_id"] is None

    replay = client.get(f"/api/扫描/{scan['id']}/重放").json()
    assert replay["可重放"] is False
    assert replay["需要补装载快照"] is True
    assert replay["重放一致"] is True  # no actual landing contradicts anything

    client.post("/api/路由表", json={"目的地码": "404", "口门编号": a01})
    blocked = client.post(f"/api/扫描/{scan['id']}/路由")
    assert blocked.status_code == 409
    assert "装载瞬间路由快照" in blocked.json()["detail"]

    recovered = client.post(f"/api/扫描/{scan['id']}/补装载快照")
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["planned_chute_id"] == a01

    decided = client.post(f"/api/扫描/{scan['id']}/路由")
    assert decided.status_code == 200, decided.text
    assert decided.json()["chute_id"] == a01
    assert client.get("/api/对账/路由口径").json()["aligned"] is True


def test_seal_audit_is_visible_in_scan_chain_and_full_link(
    client, chute_ids, loaded_scan
):
    a01 = chute_ids["A01"]
    scan = loaded_scan("YB-SEAL-AUDIT")
    client.post(f"/api/扫描/{scan['id']}/路由")
    bag = client.post("/api/封袋/开袋", json={"口门编号": a01}).json()
    add = client.post(
        f"/api/封袋/{bag['id']}/入袋", json={"扫描编号": scan["id"]}
    )
    assert add.status_code == 200, add.text
    seal = client.post(f"/api/封袋/{bag['id']}/封口")
    assert seal.status_code == 200, seal.text

    audit = client.get("/api/审计", params={"scan_id": scan["id"]}).json()
    seal_rows = [row for row in audit if row["action"] == "封口"]
    assert len(seal_rows) == 1
    assert seal_rows[0]["kind"] == "封袋"
    assert seal_rows[0]["ref_id"] == bag["id"]

    replay = client.get(f"/api/扫描/{scan['id']}/重放").json()
    assert any(row["action"] == "封口" for row in replay["审计链"])

    full_link = client.get(
        "/api/对账/全链路", params={"扫描编号": scan["id"]}
    ).json()
    assert any(row["action"] == "封口" for row in full_link["审计链"])
    assert any(row["action"] == "封口" for row in full_link["审计"])


def test_clean_test_seed_has_no_demo_pending_and_allows_shift_seal(client):
    overview = client.get("/api/总览").json()
    assert overview["分布"]["待路由"] == 0

    sealed = client.post("/api/shifts/1/seal")
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["sealed"] == 1


def test_english_management_aliases_accept_english_bodies(client):
    line = client.post("/api/lines", json={"name": "English Line"}).json()
    assert line["name"] == "English Line"
    assert client.get("/api/lines").status_code == 200

    chute = client.post(
        "/api/chutes",
        json={"line_id": line["id"], "code": "EN1", "title": "English Gate"},
    ).json()
    assert chute["code"] == "EN1"
    assert client.post(f"/api/chutes/{chute['id']}/close").status_code == 200

    setting = client.post("/api/settings", json={"key": "英文键", "value": "v"})
    assert setting.status_code == 200, setting.text
    assert setting.json()["key"] == "英文键"
    assert any(row["键"] == "英文键" for row in client.get("/api/settings").json())

    sealed = client.post("/api/shifts/1/seal")
    assert sealed.status_code == 200, sealed.text
    shift = client.post("/api/shifts", json={"name": "English Shift"}).json()
    assert shift["name"] == "English Shift"
    assert client.get("/api/shifts/reconcile").status_code == 200

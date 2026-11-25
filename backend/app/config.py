from __future__ import annotations
import os
from pathlib import Path

PROJECT_NAME = "分拣过机台"
ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("SORTBAY_DB", str(ROOT / "data" / "sortbay.db")))

# 全局唯一路由口径：LOAD_SNAPSHOT（装载瞬间快照贯穿）。
# 不提供请求级切换，避免拟落口与裁决实落口混用两套答案。
ROUTE_POLICY = "LOAD_SNAPSHOT"
ROUTING_POLICY = ROUTE_POLICY
POLICY = ROUTE_POLICY
ROUTE_POLICY_SHORT = "装载快照"
ROUTE_POLICY_LABEL = "以装载瞬间路由快照贯穿为准——装载时按当时路由表记下拟落口门，后续裁决只落该快照口门，改表不回写扫描快照。"

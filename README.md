# 分拣过机台（Sortbay）

骨架：过机扫描装载 → 口门路由裁决 → 错分回流批次 → 封袋班次对账

- 前端 http://127.0.0.1:6600
- API http://127.0.0.1:11600

## 唯一路由口径

本部署全局采用 **装载瞬间路由快照贯穿（`LOAD_SNAPSHOT`）**：

1. `POST /api/扫描` 装载时，按当时路由表把目的地对应的口门写入
   `scans.planned_chute_id`，并记录路由规则 ID/版本/快照时间。
2. `POST /api/路由表` 改档只更新 `route_rules` 并追加
   `route_rule_versions`，**不回写**任何扫描快照。
3. `POST /api/扫描/{id}/路由` 只裁决、落入装载快照口门；不再用活表口门覆盖。
4. `scans.chute_id` 是唯一实落口门。已路由件必须满足
   `chute_id = planned_chute_id`；总览、扫描册、封袋准入和重放均按此对账。
5. 封袋按实落 `scans.chute_id = bags.chute_id` 且快照/实落一致才准入；错口返回 400，口径拧花返回 409，均回滚业务事务，并另写拦截审计。

系统不提供请求级快照/活表切换。`/api/路由口径` 可读取当前部署口径。

## 对读、重放与夹具

常用接口：

- `GET /api/扫描/{id}` / `GET /api/扫描册`：扫描册与拟落/实落/当前活表三列。
- `GET /api/扫描/{id}/重放`：按选定的装载快照口径重放。
- `GET /api/扫描/{id}/全链路`：在同一个只读事务中返回裁决回执、扫描册行、路由表/版本、事件、审计、封袋页/准入、总览和对账。
- `GET /api/对账/路由口径` / `GET /api/对账/全链路?扫描编号=<id>`：一致性报告。
- `GET /api/审计/重放?扫描编号=<id>`、`GET /api/审计/分拣线重放`：审计/分拣线重放。
- `GET /api/封袋/准入?袋编号=<id>`：只返回实落口门与袋口门一致、且拟落/实落口径一致的已路由件。常见英文路径（`/api/scans`、`/api/routes`、`/api/bags/admission`、`/api/overview`、`/api/audit`）和英文字段别名也已挂载。

后端夹具位于 `backend/tests/test_routing_consistency.py`，覆盖 14 个场景：

- 装载后目的地改口门，裁决仍听装载快照；
- 裁决回执、扫描册、路由表、总览桶、审计和重放同口径；
- 错口袋拒绝入袋，正确口门袋准入；
- 人为拧花拟落/实落口门后，即使凑到实落口门的袋也不准入、不封口；
- 路由表半截写入、裁决半截写入后的事务回滚；
- 重复裁决、改表与裁决并发后的回执/落账一致；
- 人为制造“快照臂/活表臂拧花”后，对账、总览和重放不得亮已对齐；
- 封口事件可从扫描审计链/全链路按袋关系回放；
- 干净测试种子不含演示待路由件，空班次可直接封班。

测试夹具通过 `SORTBAY_SEED_DEMO_SCANS=0` 关闭人工冒烟用的演示待路由扫描；直接启动产品种子时仍默认保留该演示件。常见管理面英文别名（`/api/shifts`、`/api/chutes`、`/api/lines`、`/api/diverts`、`/api/settings`，以及 `/scans/{id}/adjudicate` 等）也已挂载。

运行：

```bash
python -m pip install -r backend/requirements.txt pytest httpx
PYTHONPATH=backend python -m pytest backend/tests -q
```

前端：

```bash
npm install --prefix frontend
npm run build --prefix frontend
```

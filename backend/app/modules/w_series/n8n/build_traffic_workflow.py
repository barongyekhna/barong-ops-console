"""生成 `barongWtraffic001` —— 每 10 分钟把独立站流量从 Jetpack 拉回控制台。

**为什么是 n8n 而不是控制台自己拉**：家规「自动化 = 控制台控制面 + n8n 执行」。
控制台只出一个 ingest 端点和一张心跳，拉取这种按时敲门的活归 n8n。

**为什么是 Jetpack 站内 REST 而不是 GA4**：用户要「5-10 分钟延迟的当天流量」，
GA4 标准报表当天数据滞后几小时，实时接口只给 30 分钟；Jetpack 站内接口用现成的
WordPress 应用密码（凭据 `kaIcXMDT4cNA0GXm`）就能读，不需要 WP.com OAuth，
2026-09-05 实测七个接口全通。GA4 以后做渠道拆分再接。

这条流刻意做到最简：定时 → 七路并行 GET → 汇合 → 打包 → POST 控制台 → 记一行。
- **不加工数据**：Code 节点只把七个响应原样装进一个 JSON；归一化、时区、聚合全在
  控制台 `w_series/traffic/service.py`。形状变了改一处。
- **不判断该不该采**：控制台按 (workspace_key, 日) upsert，重复采集无害。
- **不给写入节点加重试**：控制台 5xx 时下一轮（10 分钟后）自然重来；心跳表会
  记 `consecutive_failures`，那才是该看的地方。
- **失败的分支不拖死整批**：七个 GET 都 `continueRegularOutput`，打包时把带
  `error` 的分支置 null，控制台只更新拿到的列。

⚠️ 装的时候必须同步写 `workflow_history` 并让 `activeVersionId` 指向新版本：
只改 `workflow_entity` 不生效，执行时读的是历史表（踩过）。cron 流不需要
`webhook_entity`；`shared_workflow` 必须有，否则激活失败。

⚠️ 令牌：n8n 默认屏蔽 `$env`，所以令牌只能写进流本身。仓库副本永远是占位符
`__W_TRAFFIC_INGEST_TOKEN__`，装库前 sed 成 compose 里 `W_TRAFFIC_INGEST_TOKEN`
的真值。**独立一把钥匙，绝不复用 W 订单那把。**

⚠️ **绝不复用/改动** barongWorders001 / barongHsitehealth001 / barongContentLinks001。
"""

from __future__ import annotations

import json
from pathlib import Path

WORKFLOW_ID = "barongWtraffic001"
WORKFLOW_NAME = "barong控制台-W系列-独立站流量采集"
VERSION_ID = "6f2d7c1e-9a44-5b3a-8c0e-1d5e7a9b2c41"
SITE_ID = 242834372
STATS_BASE = f"https://barongyekhna.com/wp-json/jetpack/v4/stats-app/sites/{SITE_ID}/stats"
# 控制台在 docker 网络里的地址——不绕公网，也就不吃 Nginx 那层限流。
INGEST_URL = "http://console_backend:8000/w/traffic/ingest"
TOKEN_PLACEHOLDER = "__W_TRAFFIC_INGEST_TOKEN__"
WP_CREDENTIAL = {"id": "kaIcXMDT4cNA0GXm", "name": "Wordpress account"}
# 5-55/10：错开整点和 03:00/03:20/03:40 那三条每日流的槽位。
CRON = "5-55/10 * * * *"
PROJECT_ID = "SjZCov4RK9CKr2EU"

# (节点名, 接口路径) —— 七路并行；顺序即 Merge 输入序号，也是打包节点的取值名。
BRANCHES: tuple[tuple[str, str], ...] = (
    ("按天访问30d", "visits?unit=day&quantity=30"),
    ("按小时访问24h", "visits?unit=hour&quantity=24"),
    ("热门页面30d", "top-posts?period=day&num=30&max=10"),
    ("来源30d", "referrers?period=day&num=30&max=10"),
    ("国家30d", "country-views?period=day&num=30"),
    ("搜索词30d", "search-terms?period=day&num=30"),
    ("外链点击30d", "clicks?period=day&num=30"),
)
# 打包节点里的字段名，与 TrafficIngestRequest 一一对应。
BRANCH_FIELDS = (
    "visits_day",
    "visits_hour",
    "top_posts",
    "referrers",
    "country_views",
    "search_terms",
    "clicks",
)

STICKY = f"""## {WORKFLOW_NAME}（{WORKFLOW_ID}）

**这个工作流是干嘛的**：每 10 分钟（`{CRON}`，太平洋时间）从独立站的 Jetpack
统计接口拉七样东西——按天访问 30 天、按小时访问 24 小时、热门页面、来源、国家、
搜索词、外链点击——原样打包推给控制台 `/w/traffic/ingest`。贸易公司主页置顶那张
「独立站流量」卡就吃这份数据。

**为什么 10 分钟一轮**：用户要的是「当天流量，5-10 分钟延迟」。一轮七个 GET 一个
POST，一天 144 轮，Jetpack 接口免费无配额。

**红线**：
- **不加工数据**。这里只打包，归一化 / 时区 / 聚合全在控制台
  `backend/app/modules/w_series/traffic/service.py`。Jetpack 形状变了改那一处。
- **不给「写入控制台」加重试**。控制台失败下一轮自然重来；连续失败次数在
  `worker_heartbeats.w-traffic` 里，那才是该看的地方。
- **七个 GET 任一失败不拖死整批**：失败分支置 null，控制台只更新拿到的列。
- **令牌独立**：请求头 `X-Ingest-Token` 与控制台 env `W_TRAFFIC_INGEST_TOKEN` 同值，
  和 W 订单同步那把不同。密钥没配时端点一律 401（fail-closed）。

**验收只认一样东西**：`worker_heartbeats` 里 `w-traffic.last_success_at` 每 10 分钟
刷新。主页流量卡超过 20 分钟没心跳会变红「采集停了」。
`python scripts/check_worker_heartbeats.py --json` 不依赖控制台 UI。

**时区**：Jetpack 按站点时区分日（实测 UTC-5），控制台原样入库；控制台在洛杉矶
显示时会标「站点时区」。

端点：backend/app/modules/w_series/router.py::traffic_ingest
"""

BUNDLE_JS = f"""
// 沙箱里没有 fetch / require / URL —— 所有数据只能来自上游节点。
// 七路分支各自失败时（HTTP 节点 onError=continueRegularOutput），它的 json 长这样
// {{ error: {{...}} }}；置 null，让控制台只更新真正拿到的列。
const NAMES = {json.dumps([name for name, _ in BRANCHES], ensure_ascii=False)};
const FIELDS = {json.dumps(list(BRANCH_FIELDS))};
function pick(name) {{
  try {{
    const j = $(name).first().json;
    if (!j || typeof j !== 'object' || j.error) return null;
    return j;
  }} catch (e) {{
    return null;
  }}
}}
const parts = {{}};
for (let i = 0; i < NAMES.length; i += 1) parts[FIELDS[i]] = pick(NAMES[i]);
let utc_offset = null;
for (const v of Object.values(parts)) {{
  if (v && typeof v.utc_offset === 'string') {{ utc_offset = v.utc_offset; break; }}
}}
const branches_ok = Object.values(parts).filter(Boolean).length;
return [{{ json: {{
  site_id: {SITE_ID},
  collected_at: new Date().toISOString(),
  utc_offset,
  branches_ok,
  ...parts,
}} }}];
""".strip()

LOG_JS = """
// 任何分支都要能走到这里 —— 失败也要留下一行可读的执行快照。
const r = $input.first().json || {};
let note;
if (typeof r.days_upserted === 'number') {
  note = `已入库 ${r.days_upserted} 天 / ${r.hours_upserted} 小时`
       + (r.day_from ? `（${r.day_from} → ${r.day_to}）` : '')
       + (Array.isArray(r.warnings) && r.warnings.length ? `；告警：${r.warnings.join('；')}` : '');
} else {
  note = '写入控制台失败 —— 看 console_backend 日志和 worker_heartbeats.w-traffic';
}
return [{ json: { ...r, note } }];
""".strip()


def _node(
    *,
    parameters: dict,
    node_id: str,
    name: str,
    node_type: str,
    type_version: float,
    position: list[int],
    **extra: object,
) -> dict:
    node = {
        "parameters": parameters,
        "id": node_id,
        "name": name,
        "type": node_type,
        "typeVersion": type_version,
        "position": position,
    }
    node.update(extra)
    return node


def _branch_node(index: int, name: str, path: str) -> dict:
    return _node(
        parameters={
            "url": f"{STATS_BASE}/{path}",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "wordpressApi",
            "options": {"timeout": 30000},
        },
        node_id=f"b7a3c9e{index}-0000-5000-8000-0000000000{index}1",
        name=name,
        node_type="n8n-nodes-base.httpRequest",
        type_version=4.2,
        position=[220, 60 + index * 120],
        credentials={"wordpressApi": dict(WP_CREDENTIAL)},
        alwaysOutputData=True,
        onError="continueRegularOutput",
    )


def build() -> dict:
    nodes = [
        _node(
            parameters={"content": STICKY, "height": 760, "width": 620, "color": 4},
            node_id="9c4e1b2a-7d3f-5a6e-b1c0-2f8d4e6a7b90",
            name="说明便签",
            node_type="n8n-nodes-base.stickyNote",
            type_version=1,
            position=[-700, 60],
        ),
        _node(
            parameters={"rule": {"interval": [{"field": "cronExpression", "expression": CRON}]}},
            node_id="1a2b3c4d-5e6f-5071-8293-a4b5c6d7e8f9",
            name="每10分钟",
            node_type="n8n-nodes-base.scheduleTrigger",
            type_version=1.2,
            position=[0, 420],
        ),
    ]
    nodes.extend(_branch_node(index, name, path) for index, (name, path) in enumerate(BRANCHES))
    nodes.extend(
        [
            _node(
                parameters={
                    "numberInputs": len(BRANCHES),
                    "mode": "combine",
                    "combineBy": "combineByPosition",
                    "options": {},
                },
                node_id="c0ffee00-1234-5678-9abc-def012345678",
                name="汇合7路",
                node_type="n8n-nodes-base.merge",
                type_version=3,
                position=[480, 420],
            ),
            _node(
                parameters={"jsCode": BUNDLE_JS},
                node_id="d1e2f3a4-b5c6-5d7e-8f90-a1b2c3d4e5f6",
                name="打包",
                node_type="n8n-nodes-base.code",
                type_version=2,
                position=[700, 420],
            ),
            _node(
                parameters={
                    "method": "POST",
                    "url": INGEST_URL,
                    "sendHeaders": True,
                    "headerParameters": {
                        "parameters": [{"name": "X-Ingest-Token", "value": TOKEN_PLACEHOLDER}]
                    },
                    "sendBody": True,
                    "specifyBody": "json",
                    "jsonBody": "={{ JSON.stringify($json) }}",
                    "options": {"timeout": 60000},
                },
                node_id="e2f3a4b5-c6d7-5e8f-90a1-b2c3d4e5f6a7",
                name="写入控制台",
                node_type="n8n-nodes-base.httpRequest",
                type_version=4.2,
                position=[920, 420],
                # 刻意不加重试：下一轮 10 分钟后自然重来，失败计数在心跳表里。
                alwaysOutputData=True,
                onError="continueRegularOutput",
            ),
            _node(
                parameters={"jsCode": LOG_JS},
                node_id="f3a4b5c6-d7e8-5f90-a1b2-c3d4e5f6a7b8",
                name="记录结果",
                node_type="n8n-nodes-base.code",
                type_version=2,
                position=[1140, 420],
            ),
        ]
    )

    connections: dict = {
        "每10分钟": {
            "main": [[{"node": name, "type": "main", "index": 0} for name, _ in BRANCHES]]
        },
        "汇合7路": {"main": [[{"node": "打包", "type": "main", "index": 0}]]},
        "打包": {"main": [[{"node": "写入控制台", "type": "main", "index": 0}]]},
        "写入控制台": {"main": [[{"node": "记录结果", "type": "main", "index": 0}]]},
    }
    for index, (name, _) in enumerate(BRANCHES):
        connections[name] = {"main": [[{"node": "汇合7路", "type": "main", "index": index}]]}

    stamp = "2026-09-05T00:00:00.000Z"
    return {
        "createdAt": stamp,
        "updatedAt": stamp,
        "id": WORKFLOW_ID,
        "name": WORKFLOW_NAME,
        "description": None,
        "active": True,
        "isArchived": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {"timezone": "America/Los_Angeles", "executionOrder": "v1"},
        "staticData": None,
        "meta": None,
        "pinData": None,
        "versionId": VERSION_ID,
        "activeVersionId": VERSION_ID,
        "versionCounter": 1,
        "triggerCount": 1,
        "tags": [],
        "shared": [
            {
                "updatedAt": stamp,
                "createdAt": stamp,
                "role": "workflow:owner",
                "workflowId": WORKFLOW_ID,
                "projectId": PROJECT_ID,
                "project": {
                    "updatedAt": "2026-03-24T07:46:51.801Z",
                    "createdAt": "2026-03-24T06:44:50.688Z",
                    "id": PROJECT_ID,
                    "name": "Guangrui Sun <barongyekhna@barongyekhna.com>",
                    "type": "personal",
                    "icon": None,
                    "description": None,
                    "creatorId": "4282a344-7d2e-5380-a49b-a7383ab463b1",
                },
            }
        ],
        "versionMetadata": {"name": None, "description": None},
    }


def main() -> None:
    target = Path(__file__).with_name("w_traffic_workflow.json")
    target.write_text(
        json.dumps(build(), separators=(", ", ": "), ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"wrote {target}")


if __name__ == "__main__":
    main()

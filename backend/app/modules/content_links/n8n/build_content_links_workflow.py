"""生成 `barongContentLinks001` —— 每天重新生成批发页,把新指南捞上去。

**为什么需要定时**:批发页上的指南清单是生成时**固化进 HTML** 的,而控制台
**不知道**用户什么时候在 WP 里点了发布(n8n 只把指南落成草稿,发布是手动动作,
不经过控制台)。所以只能定期回去核一遍——重发本身就会向 WP 批量核每篇指南的
发布状态,新发的自然被捞上来。

反方向(指南文章底部的「Buying for a store?」回链)**不需要这个流**:那是插件
按类目现场查表,新文章自动就带,零动作。

这条流刻意做到极简:定时 → 打一个控制台端点 → 完。
- **不写 WordPress**:所有 WP 写入都在控制台里做,n8n 只负责"按时敲一下"。
- **不判断该不该发**:最小间隔护栏在控制台侧(`MIN_REPUBLISH_INTERVAL_MINUTES`),
  n8n 不该有业务判断。
- **控制台永不抛错给它**:发布失败返回 `ok:false` 而不是 5xx——n8n 重试解决不了
  "WP 打不通",重试风暴反而更糟。

⚠️ 装的时候必须同步写 `workflow_history` 并让 `activeVersionId` 指向新版本:
只改 `workflow_entity` 不生效,执行时读的是历史表(踩过)。

⚠️ **绝不复用/改动** barongPupload001 / barongGEOpublish001 / barongB2Bwidget001。
"""

from __future__ import annotations

import json
from pathlib import Path

WORKFLOW_ID = "barongContentLinks001"
VERSION_ID = "a8c35df0-1b30-5d12-8a55-26acce3da8b8"
# 控制台在 docker 网络里的地址——不绕公网,也就不吃 Nginx 那层限流。
REPUBLISH_URL = "http://console_backend:8000/content/link-map/refresh"
# 太平洋时间凌晨 3 点。用户在洛杉矶,这个点他不会在看站,页面重写不影响他。
# 03:20 —— 和 B2B 批发页重发的 03:00 **错开 20 分钟**。
# 两条流都要批量核 WordPress 状态,同时打会压 WP.com。
# 以后再加定时流要继续错开:03:00 b2b / 03:20 内链网。
CRON_HOUR = 3
CRON_MINUTE = 20
# n8n **默认屏蔽 `$env` 读取**(没设 N8N_BLOCK_ENV_ACCESS_IN_NODE=false),所以
# token 只能写进工作流本身——barongWorders001 和 barongHsitehealth001 都是这么
# 干的,照同一个办法。必须和控制台 env `CONTENT_LINKS_TOKEN` 同值。
CONTENT_LINKS_TOKEN_VALUE = "ke_YJmVZ5SFg-K1PG7QXrathZ3yIqbV1AgOBV5kL4NU"

STICKY = """## barong控制台-内链网-每日兜底刷新（barongContentLinks001）

**这个工作流是干嘛的**：每天凌晨 3 点（太平洋时间）敲一下控制台，让它重新生成
`/wholesale/` 主页和各店型子页。

**为什么需要它**：批发页上的「Buying guides for this line」清单是**生成时印进
HTML 的**。你在 WP 里点发布一篇新指南时，控制台并不知道 —— n8n 只把指南落成
草稿，发布是你手动点的，那个动作不经过控制台。所以只能每天回去核一遍。

重发时控制台会向 WP 批量核一次每篇指南的发布状态，**只挂已发布的**，并用 WP 返回
的固定链接覆盖存的 URL（存的可能还是 `?p=4218` 这种草稿期形式，链过去是 404）。

**反方向不用管**：指南文章底部那行「Buying for a store?」是瘦插件按类目现场查表
渲染的，新文章自动就带，不需要任何动作。

**红线**：
- **这条流不碰 WordPress**。所有 WP 写入都在控制台里做，n8n 只负责按时敲一下。
- **不加业务判断**。最小间隔护栏（30 分钟）在控制台侧，防的是定时被误配成每分钟
  一次时往 WP.com 上砸请求。
- 控制台失败时返回 `ok:false` 而不是 5xx —— **不要给这个节点加重试**，重试解决不了
  "WP 打不通"，只会变成请求风暴。页面变旧在控制台面板的「上次生成」时间上看得见。

**配置**：请求头 `X-Content-Links-Token` 与控制台 env `CONTENT_LINKS_TOKEN` 同值
（n8n 默认屏蔽 `$env` 读取，所以 token 直接写在节点里 —— 和 W 订单同步、H 哨兵一样）；
密钥没配时端点一律 403（fail-closed）。
端点：backend/app/modules/b2b/machine_router.py::website_republish
"""

LOG_JS = """
// 任何分支都要能走到这里 —— 失败也要留下一行可读的执行快照（GEO 发布流踩过：
// 某个分支走不到回报，出了问题只能靠猜）。
const r = $input.first().json || {};
let note;
if (r.skipped) {
  note = `跳过：${r.reason || '距上次生成太近'}`;
} else if (r.ok) {
  note = `已重发：${r.groups} 个店型页，挂上 ${r.guides_linked} 篇指南，`
       + `${r.guide_categories_mapped} 个类目可回链`;
} else {
  note = '重发失败 —— 看控制台 backend 日志（WP 打不通或凭据过期）';
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


def build() -> dict:
    nodes = [
        _node(
            parameters={"content": STICKY, "height": 620, "width": 560, "color": 4},
            node_id="cc1f29a0-a1c0-5fd4-81b5-41309f98ee9c",
            name="说明便签",
            node_type="n8n-nodes-base.stickyNote",
            type_version=1,
            position=[-560, 160],
        ),
        _node(
            parameters={
                "rule": {
                    "interval": [
                        {"field": "cronExpression", "expression": f"{CRON_MINUTE} {CRON_HOUR} * * *"}
                    ]
                }
            },
            node_id="7acbbb85-a88a-5916-adbf-9cb16c160a41",
            name="每天凌晨3点20",
            node_type="n8n-nodes-base.scheduleTrigger",
            type_version=1.2,
            position=[0, 300],
        ),
        _node(
            parameters={
                "method": "POST",
                "url": REPUBLISH_URL,
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [
                        {
                            "name": "X-Content-Links-Token",
                            "value": CONTENT_LINKS_TOKEN_VALUE,
                        }
                    ]
                },
                "options": {"timeout": 180000},
            },
            node_id="ab8a1ae7-cf8d-5090-a986-be977ff91479",
            name="重发批发页",
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            position=[220, 300],
            # 刻意**不加**重试：控制台失败时返回 ok:false 而不是 5xx，
            # 重试解决不了 WP 打不通，只会变成请求风暴。
            alwaysOutputData=True,
        ),
        _node(
            parameters={"jsCode": LOG_JS},
            node_id="d66662c6-2e22-5ded-b3d7-ca157f2882ab",
            name="记录结果",
            node_type="n8n-nodes-base.code",
            type_version=2,
            position=[440, 300],
        ),
    ]

    connections = {
        "每天凌晨3点20": {
            "main": [[{"node": "重发批发页", "type": "main", "index": 0}]]
        },
        "重发批发页": {"main": [[{"node": "记录结果", "type": "main", "index": 0}]]},
    }

    return {
        "createdAt": "2026-07-30T00:00:00.000Z",
        "updatedAt": "2026-07-30T00:00:00.000Z",
        "id": WORKFLOW_ID,
        "name": "barong控制台-内链网-每日兜底刷新",
        "description": None,
        "active": True,
        "isArchived": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {"timezone": "America/Los_Angeles"},
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
                "updatedAt": "2026-07-30T00:00:00.000Z",
                "createdAt": "2026-07-30T00:00:00.000Z",
                "role": "workflow:owner",
                "workflowId": WORKFLOW_ID,
                "projectId": "SjZCov4RK9CKr2EU",
                "project": {
                    "updatedAt": "2026-03-24T07:46:51.801Z",
                    "createdAt": "2026-03-24T06:44:50.688Z",
                    "id": "SjZCov4RK9CKr2EU",
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
    target = Path(__file__).with_name("content_links_workflow.json")
    target.write_text(
        json.dumps(build(), separators=(", ", ": "), ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"wrote {target}")


if __name__ == "__main__":
    main()

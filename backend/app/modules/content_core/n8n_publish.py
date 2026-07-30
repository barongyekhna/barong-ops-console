"""发布工作流的**通用生成器**——GEO 与 SEO 共用一份。

两条发布链在结构上完全一样:
webhook → 取发布包 → 拆文章 → 决定建或更新 → 写 WP → 收 URL 并回填内链 →
IF(有没有内链要回填) → 回填 → 整理回报 → 回报控制台。

不一样的只有**名字和路径**:工作流 id/名称、webhook 路径、节点 id。所以这里
把结构做成一份,由 ``PublishWorkflowConfig`` 传入差异。复制一份出来改名字是
更快的做法,但那意味着 n8n 那三个教训(Code 节点必须 map 全部输入 / 任何分支
都要能走到回报 / Yoast 走 meta 对象)以后只会在其中一边被修。

**节点 id 必须稳定**:n8n 按 id 认节点,重新生成时 id 变了等于换了一条流。
GEO 的 id 是历史上已经装进 n8n 的那批,原样传入;SEO 的由 uuid5 从工作流 slug
+ 节点名派生——同样确定,且不会和 GEO 撞。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

# 工作流内部所有节点的名字。顺序即数据流向。
NODE_STICKY = "说明便签"
NODE_WEBHOOK = "Webhook 触发"
NODE_FETCH = "取数-发布包"
NODE_SPLIT = "拆文章"
NODE_DECIDE = "决定建或更新"
NODE_WRITE = "建/更新文章"
NODE_COLLECT = "收集URL并回填内链"
NODE_IF = "有内链要回填?"
NODE_BACKFILL = "回填内链"
NODE_REPORT_BUILD = "整理回报"
NODE_REPORT_SEND = "回报控制台"

_NS = uuid.UUID("6f1f6f3c-9a1e-4a0e-9f7e-2c4a5d6b7e80")


def derived_node_ids(slug: str) -> dict[str, str]:
    """从 slug + 节点名派生稳定的节点 id。"""
    return {
        name: str(uuid.uuid5(_NS, f"{slug}:{name}"))
        for name in (
            NODE_STICKY,
            NODE_WEBHOOK,
            NODE_FETCH,
            NODE_SPLIT,
            NODE_DECIDE,
            NODE_WRITE,
            NODE_COLLECT,
            NODE_IF,
            NODE_BACKFILL,
            NODE_REPORT_BUILD,
            NODE_REPORT_SEND,
            "if_condition",
        )
    }


@dataclass(frozen=True)
class PublishWorkflowConfig:
    workflow_id: str
    workflow_name: str
    webhook_path: str
    sticky: str
    build_bodies_js: str
    decide_js: str
    collect_js: str
    report_js: str
    node_ids: dict[str, str]
    wp_credential: dict[str, Any]
    version_id: str
    project: dict[str, Any]
    created_at: str = "2026-07-29T00:00:00.000Z"
    version_counter: int = 4
    posts_base: str = "https://barongyekhna.com/wp-json/wp/v2/posts"
    extra: dict[str, Any] = field(default_factory=dict)


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


def build_publish_workflow(cfg: PublishWorkflowConfig) -> dict:
    nodes = [
        _node(
            parameters={"content": cfg.sticky, "height": 640, "width": 560, "color": 4},
            node_id=cfg.node_ids[NODE_STICKY],
            name=NODE_STICKY,
            node_type="n8n-nodes-base.stickyNote",
            type_version=1,
            position=[-560, 160],
        ),
        _node(
            parameters={
                "httpMethod": "POST",
                "path": cfg.webhook_path,
                "responseMode": "onReceived",
                "options": {},
            },
            node_id=cfg.node_ids[NODE_WEBHOOK],
            name=NODE_WEBHOOK,
            node_type="n8n-nodes-base.webhook",
            type_version=2,
            position=[0, 300],
            webhookId=f"{cfg.webhook_path}-webhook",
        ),
        _node(
            parameters={"url": "={{ $json.body.package_url }}", "options": {}},
            node_id=cfg.node_ids[NODE_FETCH],
            name=NODE_FETCH,
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            position=[200, 300],
        ),
        _node(
            parameters={"jsCode": cfg.build_bodies_js},
            node_id=cfg.node_ids[NODE_SPLIT],
            name=NODE_SPLIT,
            node_type="n8n-nodes-base.code",
            type_version=2,
            position=[400, 300],
        ),
        _node(
            parameters={"jsCode": cfg.decide_js},
            node_id=cfg.node_ids[NODE_DECIDE],
            name=NODE_DECIDE,
            node_type="n8n-nodes-base.code",
            type_version=2,
            position=[600, 300],
        ),
        _node(
            parameters={
                "method": "={{ $json.method }}",
                "url": "={{ $json.url }}",
                "authentication": "predefinedCredentialType",
                "nodeCredentialType": "wordpressApi",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($json.wp_body) }}",
                "options": {"batching": {"batch": {"batchSize": 1, "batchInterval": 2000}}},
            },
            node_id=cfg.node_ids[NODE_WRITE],
            name=NODE_WRITE,
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            position=[800, 300],
            retryOnFail=True,
            maxTries=3,
            waitBetweenTries=5000,
            credentials={"wordpressApi": cfg.wp_credential},
        ),
        _node(
            parameters={"jsCode": cfg.collect_js},
            node_id=cfg.node_ids[NODE_COLLECT],
            name=NODE_COLLECT,
            node_type="n8n-nodes-base.code",
            type_version=2,
            position=[1000, 300],
        ),
        _node(
            parameters={
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 2,
                    },
                    "conditions": [
                        {
                            "id": cfg.node_ids["if_condition"],
                            "leftValue": "={{ $json.needs_backfill === true }}",
                            "rightValue": "",
                            "operator": {
                                "type": "boolean",
                                "operation": "true",
                                "singleValue": True,
                            },
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
            node_id=cfg.node_ids[NODE_IF],
            name=NODE_IF,
            node_type="n8n-nodes-base.if",
            type_version=2.2,
            position=[1180, 300],
        ),
        _node(
            parameters={
                "method": "POST",
                "url": "={{ '" + cfg.posts_base + "/' + $json.post_id }}",
                "authentication": "predefinedCredentialType",
                "nodeCredentialType": "wordpressApi",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ content: $json.content }) }}",
                "options": {"batching": {"batch": {"batchSize": 1, "batchInterval": 2000}}},
            },
            node_id=cfg.node_ids[NODE_BACKFILL],
            name=NODE_BACKFILL,
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            retryOnFail=True,
            maxTries=3,
            waitBetweenTries=5000,
            position=[1200, 300],
            credentials={"wordpressApi": cfg.wp_credential},
            alwaysOutputData=True,
        ),
        _node(
            parameters={"jsCode": cfg.report_js},
            node_id=cfg.node_ids[NODE_REPORT_BUILD],
            name=NODE_REPORT_BUILD,
            node_type="n8n-nodes-base.code",
            type_version=2,
            position=[1400, 300],
        ),
        _node(
            parameters={
                "method": "POST",
                "url": "={{ $('" + NODE_WEBHOOK + "').item.json.body.callback_url }}",
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [
                        {
                            "name": "X-Job-Token",
                            "value": "={{ $('" + NODE_WEBHOOK + "').item.json.body.token }}",
                        }
                    ]
                },
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($json) }}",
                "options": {},
            },
            node_id=cfg.node_ids[NODE_REPORT_SEND],
            name=NODE_REPORT_SEND,
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            position=[1600, 300],
        ),
    ]

    connections = {
        NODE_WEBHOOK: {"main": [[{"node": NODE_FETCH, "type": "main", "index": 0}]]},
        NODE_FETCH: {"main": [[{"node": NODE_SPLIT, "type": "main", "index": 0}]]},
        NODE_SPLIT: {"main": [[{"node": NODE_DECIDE, "type": "main", "index": 0}]]},
        NODE_DECIDE: {"main": [[{"node": NODE_WRITE, "type": "main", "index": 0}]]},
        NODE_WRITE: {
            "main": [[{"node": NODE_COLLECT, "type": "main", "index": 0}]]
        },
        NODE_COLLECT: {
            "main": [[{"node": NODE_IF, "type": "main", "index": 0}]]
        },
        # true 分支去回填,false 分支直接回报——两条路都必须汇到「整理回报」,
        # 否则没有互链的簇会走到死路,控制台永远收不到回报。
        NODE_IF: {
            "main": [
                [{"node": NODE_BACKFILL, "type": "main", "index": 0}],
                [{"node": NODE_REPORT_BUILD, "type": "main", "index": 0}],
            ]
        },
        NODE_BACKFILL: {"main": [[{"node": NODE_REPORT_BUILD, "type": "main", "index": 0}]]},
        NODE_REPORT_BUILD: {"main": [[{"node": NODE_REPORT_SEND, "type": "main", "index": 0}]]},
    }

    return {
        "createdAt": cfg.created_at,
        "updatedAt": cfg.created_at,
        "id": cfg.workflow_id,
        "name": cfg.workflow_name,
        "description": None,
        "active": True,
        "isArchived": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {},
        "staticData": None,
        "meta": None,
        "pinData": None,
        "versionId": cfg.version_id,
        "activeVersionId": cfg.version_id,
        "versionCounter": cfg.version_counter,
        "triggerCount": 1,
        "tags": [],
        "shared": [
            {
                "updatedAt": cfg.created_at,
                "createdAt": cfg.created_at,
                "role": "workflow:owner",
                "workflowId": cfg.workflow_id,
                "projectId": cfg.project["id"],
                "project": cfg.project,
            }
        ],
        "versionMetadata": {"name": None, "description": None},
    }




__all__ = ["PublishWorkflowConfig", "build_publish_workflow", "derived_node_ids"]

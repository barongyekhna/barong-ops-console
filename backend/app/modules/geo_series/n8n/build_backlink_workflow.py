#!/usr/bin/env python3
"""Emit ``geo_backlink_workflow.json`` (n8n workflow ``barongGEObacklink001``).

Rail 2: rewrite only the marker-delimited "Learn more" block in a live Woo product
description. A BRAND NEW workflow — it must never touch ``barongPupload001`` (the
product upload flow) or ``barongGEOpublish001`` (the guide publisher).

Everything the run decides comes from the console package; this flow reads one
product, swaps one block, writes back one field.
"""

from __future__ import annotations

import json
from pathlib import Path

# P 流实测:Woo 走 httpBasicAuth(不是 wooCommerceApi),凭据名就叫 WooCommerce
WC_CREDENTIAL = {"id": "aPB82hXe9Rxdvyfo", "name": "WooCommerce"}
WC_PRODUCTS = "https://barongyekhna.com/wp-json/wc/v3/products"
SCHEMA_VERSION = "geo-backlink-package-v1"

STICKY = f"""## barong控制台-GEO系列-产品页反链（barongGEObacklink001）

**这个工作流是干嘛的**：把产品页描述里的「Learn more」指南链接块刷新一遍，让产品页能反向导向对应类目的指南文章（内链网双向打通）。

1. **取数**：按派单里的 `package_url`（带一单一钥 token）回控制台拉反链包（每个产品的 Woo id + 已经拼好的区块 HTML）
2. **读**：`GET wc/v3/products/{{id}}` 只取 description
3. **换**：用标记 `class="kp-guides"` 做**有则替换、无则追加**（幂等：跑一百次结果一样，不会越叠越多）
4. **写**：`PUT wc/v3/products/{{id}}` **只回写 description 一个字段**——不碰价格、库存、图片、类目
5. **回报**：`POST callback_url`（请求头 X-Job-Token），控制台落台账

**红线**：
- 区块内容**完全由控制台决定**，本流不拼 HTML、不查指南、不做判断
- 只挂**对应类目的具体指南文章**，绝不挂 /guides/ 主页（控制台侧已硬过滤）
- 只写 description；任何其他字段都不许出现在 PUT body 里
- **绝不复用/改动 barongPupload001 与 barongGEOpublish001**——这是独立的第三条
- 契约详见仓库 backend/app/modules/geo_series/contract/backlink_package.py
"""

SPLIT_JS = f"""
const pkg = $input.first().json;
if (pkg.schema_version !== '{SCHEMA_VERSION}') {{
  throw new Error('拒绝执行：需要 {SCHEMA_VERSION}');
}}
const targets = pkg.targets || [];
if (!targets.length) {{
  throw new Error('反链包里没有要更新的产品');
}}
const blockClass = pkg.block_class || 'kp-guides';
// 必须逐条 map 全部输入——只取第一条会把整批产品压成一个(GEO 发布流踩过)。
return targets.map((t) => ({{
  json: {{
    product_id: t.product_id,
    sku: t.sku || null,
    woo_product_id: t.woo_product_id,
    block_html: t.block_html || '',
    block_class: blockClass,
    url: '{WC_PRODUCTS}/' + t.woo_product_id,
  }},
}}));
""".strip()

MERGE_JS = """
// 有则替换、无则追加——幂等的唯一保证。绝不在这里拼 HTML：区块内容由控制台决定。
const rows = $('拆产品').all().map((i) => i.json);
const current = $input.all().map((i) => i.json);
return current.map((product, idx) => {
  const row = rows[idx] || {};
  const block = row.block_html || '';
  const cls = row.block_class || 'kp-guides';
  const existing = (product && product.description) || '';
  const re = new RegExp('<section class="[^"]*\\\\b' + cls + '\\\\b[^"]*">[\\\\s\\\\S]*?</section>', 'i');
  let next;
  if (re.test(existing)) {
    next = existing.replace(re, block);
  } else if (block) {
    const closing = existing.lastIndexOf('</div>');
    next = closing < 0 ? existing + block : existing.slice(0, closing) + block + existing.slice(closing);
  } else {
    next = existing;
  }
  return {
    json: {
      product_id: row.product_id,
      woo_product_id: row.woo_product_id,
      url: row.url,
      changed: next !== existing,
      // 只回写 description 一个字段
      wp_body: { description: next },
    },
  };
});
""".strip()

REPORT_JS = """
const rows = $('拼描述').all().map((i) => i.json);
const updated = rows.map((r) => ({
  product_id: r.product_id,
  woo_product_id: r.woo_product_id,
  updated: !!r.changed,
}));
return [{ json: { status: 'success', updated_items: updated } }];
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
            parameters={"content": STICKY, "height": 600, "width": 560, "color": 4},
            node_id="ce111111-1111-4111-8111-11111111111e",
            name="说明便签",
            node_type="n8n-nodes-base.stickyNote",
            type_version=1,
            position=[-560, 160],
        ),
        _node(
            parameters={
                "httpMethod": "POST",
                "path": "barong-geo-backlink",
                "responseMode": "onReceived",
                "options": {},
            },
            node_id="c1111111-1111-4111-8111-111111111111",
            name="Webhook 触发",
            node_type="n8n-nodes-base.webhook",
            type_version=2,
            position=[0, 300],
            webhookId="barong-geo-backlink-webhook",
        ),
        _node(
            parameters={"url": "={{ $json.body.package_url }}", "options": {}},
            node_id="c2222222-2222-4222-8222-222222222222",
            name="取数-反链包",
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            position=[200, 300],
        ),
        _node(
            parameters={"jsCode": SPLIT_JS},
            node_id="c3333333-3333-4333-8333-333333333333",
            name="拆产品",
            node_type="n8n-nodes-base.code",
            type_version=2,
            position=[400, 300],
        ),
        _node(
            parameters={
                "method": "GET",
                "url": "={{ $json.url }}",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpBasicAuth",
                "sendQuery": True,
                "queryParameters": {
                    "parameters": [{"name": "_fields", "value": "id,description"}]
                },
                "options": {
                    "batching": {"batch": {"batchSize": 1, "batchInterval": 1500}}
                },
            },
            node_id="c4444444-4444-4444-8444-444444444444",
            name="读现有描述",
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            retryOnFail=True,
            maxTries=3,
            waitBetweenTries=5000,
            position=[600, 300],
            credentials={"httpBasicAuth": WC_CREDENTIAL},
        ),
        _node(
            parameters={"jsCode": MERGE_JS},
            node_id="c5555555-5555-4555-8555-555555555555",
            name="拼描述",
            node_type="n8n-nodes-base.code",
            type_version=2,
            position=[800, 300],
        ),
        _node(
            parameters={
                "method": "PUT",
                "url": "={{ $json.url }}",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpBasicAuth",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($json.wp_body) }}",
                "options": {
                    "batching": {"batch": {"batchSize": 1, "batchInterval": 2000}}
                },
            },
            node_id="c6666666-6666-4666-8666-666666666666",
            name="回写描述",
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            retryOnFail=True,
            maxTries=3,
            waitBetweenTries=5000,
            position=[1000, 300],
            credentials={"httpBasicAuth": WC_CREDENTIAL},
            alwaysOutputData=True,
        ),
        _node(
            parameters={"jsCode": REPORT_JS},
            node_id="c7777777-7777-4777-8777-777777777777",
            name="整理回报",
            node_type="n8n-nodes-base.code",
            type_version=2,
            position=[1200, 300],
        ),
        _node(
            parameters={
                "method": "POST",
                "url": "={{ $('Webhook 触发').item.json.body.callback_url }}",
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [
                        {
                            "name": "X-Job-Token",
                            "value": "={{ $('Webhook 触发').item.json.body.token }}",
                        }
                    ]
                },
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($json) }}",
                "options": {},
            },
            node_id="c8888888-8888-4888-8888-888888888888",
            name="回报控制台",
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            position=[1400, 300],
        ),
    ]

    connections = {
        "Webhook 触发": {"main": [[{"node": "取数-反链包", "type": "main", "index": 0}]]},
        "取数-反链包": {"main": [[{"node": "拆产品", "type": "main", "index": 0}]]},
        "拆产品": {"main": [[{"node": "读现有描述", "type": "main", "index": 0}]]},
        "读现有描述": {"main": [[{"node": "拼描述", "type": "main", "index": 0}]]},
        "拼描述": {"main": [[{"node": "回写描述", "type": "main", "index": 0}]]},
        "回写描述": {"main": [[{"node": "整理回报", "type": "main", "index": 0}]]},
        "整理回报": {"main": [[{"node": "回报控制台", "type": "main", "index": 0}]]},
    }

    return {
        "createdAt": "2026-07-29T00:00:00.000Z",
        "updatedAt": "2026-07-29T00:00:00.000Z",
        "id": "barongGEObacklink001",
        "name": "barong控制台-GEO系列-产品页反链",
        "description": None,
        "active": True,
        "isArchived": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {},
        "staticData": None,
        "meta": None,
        "pinData": None,
        "versionId": "7a2e5b31-9c04-4d68-8e17-3f5b0c2a44d1",
        "activeVersionId": "7a2e5b31-9c04-4d68-8e17-3f5b0c2a44d1",
        "versionCounter": 1,
        "triggerCount": 1,
        "tags": [],
        "shared": [
            {
                "updatedAt": "2026-07-29T00:00:00.000Z",
                "createdAt": "2026-07-29T00:00:00.000Z",
                "role": "workflow:owner",
                "workflowId": "barongGEObacklink001",
                "projectId": "SjZCov4RK9CKr2EU",
                "project": {
                    "updatedAt": "2026-03-24T07:46:51.801Z",
                    "createdAt": "2026-03-24T06:44:50.688Z",
                    "id": "SjZCov4RK9CKr2EU",
                    "name": "Guangrui Sun <barongyekhna@barongyekhna.com>",
                    "type": "personal",
                    "icon": None,
                    "description": None,
                    "creatorId": "c0b4c1d1-41e4-4eaa-982f-3e1808550e7f",
                },
            }
        ],
        "versionMetadata": {"name": None, "description": None},
    }


def main() -> None:
    target = Path(__file__).with_name("geo_backlink_workflow.json")
    target.write_text(
        json.dumps(build(), ensure_ascii=False, separators=(", ", ": ")),
        encoding="utf-8",
    )
    print(f"wrote {target}")


if __name__ == "__main__":
    main()

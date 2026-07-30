"""生成 `barongB2Bwidget001` —— 把批发信息推到 Woo 产品页小窗。

跑一次这个脚本会在同目录吐出 `b2b_widget_workflow.json`,那份 JSON 是 n8n
**数据库行**的导出格式(不是界面导出格式),直接装进 n8n 的 SQLite。

⚠️ 装的时候必须同步写 `workflow_history` 并让 `activeVersionId` 指向新版本:
只改 `workflow_entity` 不生效,执行时读的是历史表(踩过)。

⚠️ **绝不复用/改动 barongPupload001**(产品上架流)、`barongGEOpublish001`、
`barongGEObacklink001` —— 这是独立的一条。批发信息和上架是两件事:改一次
批发价不该重新跑一遍整个上架流程。

爆炸半径刻意做到最小:只写**一个** meta 字段 `_kp_b2b`。永不建产品、永不
改价、永不碰图片、永不动描述(描述归 P 和 GEO 反链管,两边打架过)。
"""

from __future__ import annotations

import json
from pathlib import Path

# wc/v3 走 httpBasicAuth 的 "WooCommerce" 凭据(P 系列验证过 wooCommerceApi 不行)。
WC_CREDENTIAL = {"id": "aPB82hXe9Rxdvyfo", "name": "WooCommerce"}
WC_PRODUCTS_ENDPOINT = "https://barongyekhna.com/wp-json/wc/v3/products"
PACKAGE_VERSION = "b2b-widget-package-v1"
WEBHOOK_PATH = "barong-b2b-widget"
WORKFLOW_ID = "barongB2Bwidget001"
# 换版本时换一个新 UUID,并让 activeVersionId 跟着改。
VERSION_ID = "7c4e1a90-3d52-4f18-b6a1-2f9c0d5e8a41"

STICKY = """## barong控制台-B2B系列-产品页批发小窗（barongB2Bwidget001）

**这个工作流是干嘛的**：接收控制台 B2B 的派单（Webhook 入口：`POST /webhook/barong-b2b-widget`），
把每个产品的批发信息写进 Woo 产品的 `_kp_b2b` meta，供瘦插件 `barong-b2b-widget` 在产品页渲染
「Buying for a store?」小窗：

1. **取数**：按派单里的 `package_url`（带一单一钥 token）回控制台拉发布包
2. **写 meta**：逐个产品 PUT `wc/v3/products/{id}`，只动 `meta_data` 里的 `_kp_b2b` 一个键
3. **回报**：`POST callback_url`（请求头 X-Job-Token），控制台落台账

**红线**：
- **包里没有价格字段，也永远不要加**。小窗上不显示批发价——GMC 会把「页面价与 feed 价不符」
  判成 Misrepresentation，账号被封过两次只剩一次申诉机会。
- **`_kp_b2b` 永远写**：撤下时写空串而不是跳过，否则更新会留下过期的小窗。
- **只碰 meta_data**，绝不动 description / price / images / status —— 那些归 P 系列和 GEO 反链。
- **绝不复用 barongPupload001**：批发价改一次不该重跑整个上架流程。

**配置**：控制台 env `N8N_B2B_WIDGET_WEBHOOK` 指向本流；凭据用 httpBasicAuth「WooCommerce」。
控制台严格串行派单：任何时刻最多一单在手，15 分钟未回报按失联处理。
契约见 backend/app/modules/b2b/contract/widget_package.py
"""

SPLIT_JS = """
const pkg = $input.first().json;
if (pkg.schema_version !== 'b2b-widget-package-v1') {
  throw new Error('拒绝写入：需要 b2b-widget-package-v1');
}
const metaKey = pkg.meta_key || '_kp_b2b';
const targets = pkg.targets || [];
if (!targets.length) {
  throw new Error('发布包里没有目标产品');
}
// 必须逐条 map 全部输入——只取第一条会把整批压成一个产品（GEO 发布流踩过）。
return targets.map((t) => {
  // available=false 时写**空串**而不是跳过：跳过会让产品页留着过期的小窗。
  const value = t.available
    ? JSON.stringify({
        v: 1,
        moq: t.moq_units || null,
        case_pack: t.case_pack || null,
        lead_days: t.lead_time_days || null,
        variants: t.variant_note || null,
      })
    : '';
  return {
    json: {
      sku: t.sku,
      woo_product_id: t.woo_product_id,
      available: !!t.available,
      url: `${'https://barongyekhna.com/wp-json/wc/v3/products'}/${t.woo_product_id}`,
      // 只带这一个 meta 键——绝不整包覆盖 meta_data，否则会抹掉
      // P 系列写的 _kp_faq / _kp_additional_property。
      wp_body: { meta_data: [{ key: metaKey, value }] },
    },
  };
});
""".strip()

REPORT_JS = """
const rows = $('拆产品').all().map((i) => i.json);
const results = $input.all().map((i) => i.json);
const updated = [];
results.forEach((res, idx) => {
  const row = rows[idx] || {};
  updated.push({
    sku: row.sku || null,
    woo_product_id: row.woo_product_id || null,
    ok: !!(res && res.id),
  });
});
const failed = updated.filter((u) => !u.ok);
return [{
  json: {
    status: failed.length ? 'failed' : 'success',
    updated_items: updated,
    error: failed.length ? `${failed.length} 个产品写入失败` : null,
  },
}];
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
            node_id="ee111111-1111-4111-8111-11111111111e",
            name="说明便签",
            node_type="n8n-nodes-base.stickyNote",
            type_version=1,
            position=[-560, 160],
        ),
        _node(
            parameters={
                "httpMethod": "POST",
                "path": WEBHOOK_PATH,
                "responseMode": "onReceived",
                "options": {},
            },
            node_id="e1111111-1111-4111-8111-111111111111",
            name="Webhook 触发",
            node_type="n8n-nodes-base.webhook",
            type_version=2,
            position=[0, 300],
            webhookId="barong-b2b-widget-webhook",
        ),
        _node(
            parameters={"url": "={{ $json.body.package_url }}", "options": {}},
            node_id="e2222222-2222-4222-8222-222222222222",
            name="取数-小窗包",
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            position=[200, 300],
        ),
        _node(
            parameters={"jsCode": SPLIT_JS},
            node_id="e3333333-3333-4333-8333-333333333333",
            name="拆产品",
            node_type="n8n-nodes-base.code",
            type_version=2,
            position=[400, 300],
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
                    "batching": {"batch": {"batchSize": 1, "batchInterval": 1500}}
                },
            },
            node_id="e4444444-4444-4444-8444-444444444444",
            name="写小窗meta",
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            retryOnFail=True,
            maxTries=3,
            waitBetweenTries=5000,
            position=[600, 300],
            credentials={"httpBasicAuth": WC_CREDENTIAL},
            alwaysOutputData=True,
        ),
        _node(
            parameters={"jsCode": REPORT_JS},
            node_id="e5555555-5555-4555-8555-555555555555",
            name="整理回报",
            node_type="n8n-nodes-base.code",
            type_version=2,
            position=[800, 300],
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
            node_id="e6666666-6666-4666-8666-666666666666",
            name="回报控制台",
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            position=[1000, 300],
        ),
    ]

    connections = {
        "Webhook 触发": {
            "main": [[{"node": "取数-小窗包", "type": "main", "index": 0}]]
        },
        "取数-小窗包": {"main": [[{"node": "拆产品", "type": "main", "index": 0}]]},
        "拆产品": {"main": [[{"node": "写小窗meta", "type": "main", "index": 0}]]},
        "写小窗meta": {"main": [[{"node": "整理回报", "type": "main", "index": 0}]]},
        "整理回报": {
            "main": [[{"node": "回报控制台", "type": "main", "index": 0}]]
        },
    }

    return {
        "createdAt": "2026-07-29T00:00:00.000Z",
        "updatedAt": "2026-07-29T00:00:00.000Z",
        "id": WORKFLOW_ID,
        "name": "barong控制台-B2B系列-产品页批发小窗",
        "description": None,
        "active": True,
        "isArchived": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {},
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
                "updatedAt": "2026-07-29T00:00:00.000Z",
                "createdAt": "2026-07-29T00:00:00.000Z",
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
                    "creatorId": "c0b4c1d1-41e4-4eaa-982f-3e1808550e7f",
                },
            }
        ],
        "versionMetadata": {"name": None, "description": None},
    }


def main() -> None:
    target = Path(__file__).with_name("b2b_widget_workflow.json")
    target.write_text(
        json.dumps(build(), separators=(", ", ": "), ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"wrote {target}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Emit ``geo_publish_workflow.json`` (n8n workflow ``barongGEOpublish001``).

The workflow JSON is a single-line, hand-shaped document; authoring it through a
generator keeps the embedded JS readable and diffable instead of a wall of
``\\n``-escaped string. Run this whenever the flow changes, then re-import the JSON
into n8n (the repo file is the source of truth; import is a manual ops step, same
as the P workflow).

This is a BRAND NEW workflow: it must never touch ``barongPupload001``.
"""

from __future__ import annotations

import json
from pathlib import Path

WP_CREDENTIAL = {"id": "kaIcXMDT4cNA0GXm", "name": "Wordpress account"}
WP_POSTS = "https://barongyekhna.com/wp-json/wp/v2/posts"
SCHEMA_VERSION = "geo-publish-package-v1"

STICKY = f"""## barong控制台-GEO系列-发布指南文章（barongGEOpublish001）

**这个工作流是干嘛的**：接收控制台 GEO 的发布派单（Webhook 入口：`POST /webhook/barong-geo-publish`），把一个话题簇里**已批准**的指南文章发布到 WordPress：

1. **取数**：按派单里的 `package_url`（带一单一钥 token）回控制台拉发布包（文章 HTML/SEO/分类/内链占位）
2. **建文**：逐篇按 `wp_existing_post_id` 或 slug 查重 → 有则 PUT 更新、无则 POST 新建（**首次新建落 draft**，等人工发布；重推保持原状态）
3. **回填内链**：全部 post 建完后收齐 URL，二次 PUT 把 `{{{{GEO_LINK_<item_id>}}}}` 占位替换成真实链接（簇内枢纽↔辐条互链）
4. **回报**：`POST callback_url`（请求头 X-Job-Token），控制台落台账 + 记下每篇的 post id/URL + 刷新 Guides 主页

**配置说明**：
- 派单来源：控制台 env `N8N_GEO_PUBLISH_WEBHOOK` 指向本流
- WP 凭证：wordpressApi「Wordpress account」（与 P 系列同一把）
- 控制台严格串行派单：任何时刻最多一单在本流手里，15 分钟未回报按失联处理
- **绝不复用/改动 barongPupload001**（产品上架流）——这是独立的一条
- 分类严格复刻 K 的谷歌类目树（控制台已解析好 `wp_category_id`，本流只写入）
- 契约详见仓库 backend/app/modules/geo_series/contract/publish_package.py
"""

BUILD_BODIES_JS = f"""
const pkg = $input.first().json;
if (pkg.schema_version !== '{SCHEMA_VERSION}') {{
  throw new Error('拒绝发布：需要 {SCHEMA_VERSION}');
}}
const articles = pkg.articles || [];
if (!articles.length) {{
  throw new Error('发布包里没有已批准的文章');
}}
const categoryId = Number(pkg.wp_category_id);
// 死命令: 指南必须落在谷歌类目里。控制台侧已硬门禁,这里是最后一道兜底——
// 宁可整单失败,也绝不把文章发成"无类目"。
if (!Number.isInteger(categoryId) || categoryId <= 0) {{
  throw new Error('拒绝发布：发布包没有带分类 id');
}}
return articles.map((a) => {{
  const seo = a.seo || {{}};
  // wp/v2 的 Yoast 字段走 `meta` 对象(实测可写可读回);`meta_data` 是 Woo 的形状,WP 会静默丢弃。
  const meta = {{}};
  if (seo.title) meta._yoast_wpseo_title = seo.title;
  if (seo.meta_description) meta._yoast_wpseo_metadesc = seo.meta_description;
  const body = {{
    title: a.title || '',
    content: a.html || '',
    excerpt: (a.text || '').slice(0, 300),
  }};
  if (Object.keys(meta).length) body.meta = meta;
  if (seo.url_slug) body.slug = seo.url_slug;
  if (Number.isInteger(categoryId) && categoryId > 0) body.categories = [categoryId];
  return {{
    json: {{
      item_id: a.item_id,
      link_token: a.link_token,
      existing_post_id: a.wp_existing_post_id || null,
      wp_body: body,
      yoast_meta: meta,
    }},
  }};
}});
""".strip()

DECIDE_JS = """
// 必须逐条 map 全部输入——只取第一条会把整簇文章压成一篇(2026-07-29 踩过)。
const base = 'https://barongyekhna.com/wp-json/wp/v2/posts';
return $input.all().map((entry) => {
  const row = entry.json;
  const body = { ...row.wp_body };
  // 首次新建才落草稿等人工发布；重推(已有 post)不改 status，已发布的保持发布。
  if (row.existing_post_id) {
    return { json: { ...row, method: 'POST', url: `${base}/${row.existing_post_id}`, wp_body: body } };
  }
  body.status = 'draft';
  return { json: { ...row, method: 'POST', url: base, wp_body: body } };
});
""".strip()

COLLECT_JS = """
// 每篇 post 的真实 URL 收齐后,把簇内互链占位替换成真链接。
const rows = $('决定建或更新').all().map((i) => i.json);
const posts = $input.all().map((i) => i.json);

// 草稿没有正式网址——WP 只给 ?p=ID。写入响应里带 permalink_template,
// 若模板不含日期占位(站点已设为 /%postname%/),发布后的网址就是确定的,直接算出来;
// 若含 %year%/%monthnum% 之类,发布日期会变,算了会错 → 退回 ?p=ID(WP 会 301 到正式地址)。
function canonicalUrl(post) {
  const link = post.link || '';
  if (link && link.indexOf('?p=') === -1) return link;
  const tpl = post.permalink_template || '';
  const dated = /%(year|monthnum|day|hour|minute|second)%/.test(tpl);
  if (tpl && !dated && post.slug) return tpl.replace('%postname%', post.slug);
  return link;
}

const urlByToken = {};
const published = [];
posts.forEach((post, idx) => {
  const row = rows[idx] || {};
  if (!post || !post.id) return;
  const url = canonicalUrl(post);
  urlByToken[row.link_token] = url;
  published.push({ item_id: row.item_id, wp_post_id: post.id, url });
});
// 需要回填的:内容里还含有 {{GEO_LINK_*}} 的 post
const updates = [];
posts.forEach((post, idx) => {
  const row = rows[idx] || {};
  let html = (row.wp_body && row.wp_body.content) || '';
  let touched = false;
  Object.keys(urlByToken).forEach((token) => {
    if (token && html.includes(token) && urlByToken[token]) {
      html = html.split(token).join(urlByToken[token]);
      touched = true;
    }
  });
  if (touched && post && post.id) {
    updates.push({ json: { post_id: post.id, content: html } });
  }
});
// 没有需要回填的(例如单篇簇,没有簇内互链)也必须往下走,否则回报节点收不到输入、任务永远卡在 dispatched。
// 用 needs_backfill 标记,由 IF 节点分流;绝不能给回填节点喂 post_id=null(会打到 /posts/null 报错)。
return updates.length
  ? updates.map((u) => ({ json: { ...u.json, needs_backfill: true, published } }))
  : [{ json: { needs_backfill: false, published } }];
""".strip()

# 回报的台账只认「收集URL」节点算出来的 published——回填分支走过 HTTP 后 $json 已变成 WP 响应。
REPORT_JS = """
const rows = $('收集URL并回填内链').all().map((i) => i.json);
const published = (rows.find((r) => r && r.published) || {}).published || [];
return [{ json: { status: 'success', published_items: published } }];
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
            parameters={"content": STICKY, "height": 640, "width": 560, "color": 4},
            node_id="be111111-1111-4111-8111-11111111111e",
            name="说明便签",
            node_type="n8n-nodes-base.stickyNote",
            type_version=1,
            position=[-560, 160],
        ),
        _node(
            parameters={
                "httpMethod": "POST",
                "path": "barong-geo-publish",
                "responseMode": "onReceived",
                "options": {},
            },
            node_id="b1111111-1111-4111-8111-111111111111",
            name="Webhook 触发",
            node_type="n8n-nodes-base.webhook",
            type_version=2,
            position=[0, 300],
            webhookId="barong-geo-publish-webhook",
        ),
        _node(
            parameters={"url": "={{ $json.body.package_url }}", "options": {}},
            node_id="b2222222-2222-4222-8222-222222222222",
            name="取数-发布包",
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            position=[200, 300],
        ),
        _node(
            parameters={"jsCode": BUILD_BODIES_JS},
            node_id="b3333333-3333-4333-8333-333333333333",
            name="拆文章",
            node_type="n8n-nodes-base.code",
            type_version=2,
            position=[400, 300],
        ),
        _node(
            parameters={"jsCode": DECIDE_JS},
            node_id="b4444444-4444-4444-8444-444444444444",
            name="决定建或更新",
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
            node_id="b5555555-5555-4555-8555-555555555555",
            name="建/更新文章",
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            position=[800, 300],
            retryOnFail=True,
            maxTries=3,
            waitBetweenTries=5000,
            credentials={"wordpressApi": WP_CREDENTIAL},
        ),
        _node(
            parameters={"jsCode": COLLECT_JS},
            node_id="b6666666-6666-4666-8666-666666666666",
            name="收集URL并回填内链",
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
                            "id": "bcccccc1-cccc-4ccc-8ccc-cccccccccccc",
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
            node_id="bccccccc-cccc-4ccc-8ccc-cccccccccccc",
            name="有内链要回填?",
            node_type="n8n-nodes-base.if",
            type_version=2.2,
            position=[1180, 300],
        ),
        _node(
            parameters={
                "method": "POST",
                "url": "={{ 'https://barongyekhna.com/wp-json/wp/v2/posts/' + $json.post_id }}",
                "authentication": "predefinedCredentialType",
                "nodeCredentialType": "wordpressApi",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ content: $json.content }) }}",
                "options": {"batching": {"batch": {"batchSize": 1, "batchInterval": 2000}}},
            },
            node_id="b7777777-7777-4777-8777-777777777777",
            name="回填内链",
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            retryOnFail=True,
            maxTries=3,
            waitBetweenTries=5000,
            position=[1200, 300],
            credentials={"wordpressApi": WP_CREDENTIAL},
            alwaysOutputData=True,
        ),
        _node(
            parameters={"jsCode": REPORT_JS},
            node_id="b8888888-8888-4888-8888-888888888888",
            name="整理回报",
            node_type="n8n-nodes-base.code",
            type_version=2,
            position=[1400, 300],
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
            node_id="b9999999-9999-4999-8999-999999999999",
            name="回报控制台",
            node_type="n8n-nodes-base.httpRequest",
            type_version=4.2,
            position=[1600, 300],
        ),
    ]

    connections = {
        "Webhook 触发": {"main": [[{"node": "取数-发布包", "type": "main", "index": 0}]]},
        "取数-发布包": {"main": [[{"node": "拆文章", "type": "main", "index": 0}]]},
        "拆文章": {"main": [[{"node": "决定建或更新", "type": "main", "index": 0}]]},
        "决定建或更新": {"main": [[{"node": "建/更新文章", "type": "main", "index": 0}]]},
        "建/更新文章": {
            "main": [[{"node": "收集URL并回填内链", "type": "main", "index": 0}]]
        },
        "收集URL并回填内链": {
            "main": [[{"node": "有内链要回填?", "type": "main", "index": 0}]]
        },
        # true 分支去回填,false 分支直接回报——两条路都必须汇到「整理回报」,
        # 否则没有互链的簇会走到死路,控制台永远收不到回报。
        "有内链要回填?": {
            "main": [
                [{"node": "回填内链", "type": "main", "index": 0}],
                [{"node": "整理回报", "type": "main", "index": 0}],
            ]
        },
        "回填内链": {"main": [[{"node": "整理回报", "type": "main", "index": 0}]]},
        "整理回报": {"main": [[{"node": "回报控制台", "type": "main", "index": 0}]]},
    }

    return {
        "createdAt": "2026-07-29T00:00:00.000Z",
        "updatedAt": "2026-07-29T00:00:00.000Z",
        "id": "barongGEOpublish001",
        "name": "barong控制台-GEO系列-发布指南文章",
        "description": None,
        "active": True,
        "isArchived": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {},
        "staticData": None,
        "meta": None,
        "pinData": None,
        "versionId": "9d1f4c22-0e3b-4a77-9f21-6b0c5f0a11ea",
        "activeVersionId": "9d1f4c22-0e3b-4a77-9f21-6b0c5f0a11ea",
        "versionCounter": 4,
        "triggerCount": 1,
        "tags": [],
        "shared": [
            {
                "updatedAt": "2026-07-29T00:00:00.000Z",
                "createdAt": "2026-07-29T00:00:00.000Z",
                "role": "workflow:owner",
                "workflowId": "barongGEOpublish001",
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
    target = Path(__file__).with_name("geo_publish_workflow.json")
    target.write_text(
        json.dumps(build(), ensure_ascii=False, separators=(", ", ": ")),
        encoding="utf-8",
    )
    print(f"wrote {target}")


if __name__ == "__main__":
    main()

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

from ...content_core import n8n_publish as n8n

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


NODE_IDS = {
    # 历史上已经装进 n8n 的那批 id。**不能改**——n8n 按 id 认节点。
    n8n.NODE_STICKY: "be111111-1111-4111-8111-11111111111e",
    n8n.NODE_WEBHOOK: "b1111111-1111-4111-8111-111111111111",
    n8n.NODE_FETCH: "b2222222-2222-4222-8222-222222222222",
    n8n.NODE_SPLIT: "b3333333-3333-4333-8333-333333333333",
    n8n.NODE_DECIDE: "b4444444-4444-4444-8444-444444444444",
    n8n.NODE_WRITE: "b5555555-5555-4555-8555-555555555555",
    n8n.NODE_COLLECT: "b6666666-6666-4666-8666-666666666666",
    n8n.NODE_IF: "bccccccc-cccc-4ccc-8ccc-cccccccccccc",
    n8n.NODE_BACKFILL: "b7777777-7777-4777-8777-777777777777",
    n8n.NODE_REPORT_BUILD: "b8888888-8888-4888-8888-888888888888",
    n8n.NODE_REPORT_SEND: "b9999999-9999-4999-8999-999999999999",
    "if_condition": "bcccccc1-cccc-4ccc-8ccc-cccccccccccc",
}

PROJECT = {
    "updatedAt": "2026-03-24T07:46:51.801Z",
    "createdAt": "2026-03-24T06:44:50.688Z",
    "id": "SjZCov4RK9CKr2EU",
    "name": "Guangrui Sun <barongyekhna@barongyekhna.com>",
    "type": "personal",
    "icon": None,
    "description": None,
    "creatorId": "c0b4c1d1-41e4-4eaa-982f-3e1808550e7f",
}


def build() -> dict:
    """结构由 content_core 出,GEO 只传自己的常量。"""
    return n8n.build_publish_workflow(
        n8n.PublishWorkflowConfig(
            workflow_id="barongGEOpublish001",
            workflow_name="barong控制台-GEO系列-发布指南文章",
            webhook_path="barong-geo-publish",
            sticky=STICKY,
            build_bodies_js=BUILD_BODIES_JS,
            decide_js=DECIDE_JS,
            collect_js=COLLECT_JS,
            report_js=REPORT_JS,
            node_ids=NODE_IDS,
            wp_credential=WP_CREDENTIAL,
            version_id="9d1f4c22-0e3b-4a77-9f21-6b0c5f0a11ea",
            project=PROJECT,
        )
    )


def main() -> None:
    target = Path(__file__).with_name("geo_publish_workflow.json")
    target.write_text(
        json.dumps(build(), ensure_ascii=False, separators=(", ", ": ")),
        encoding="utf-8",
    )
    print(f"wrote {target}")


if __name__ == "__main__":
    main()

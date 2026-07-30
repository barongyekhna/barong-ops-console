"""生成 ``seo_publish_workflow.json``(n8n 工作流 ``barongSEOpublish001``)。

结构由 ``content_core.n8n_publish`` 出——**和 GEO 那条是同一份代码**,所以
n8n 那三个教训不会只在一边被修:
1. Code 节点必须 ``$input.all().map()``,只取第一条会把整批压成一篇;
2. 任何分支都要能走到回报节点,否则控制台永远收不到回报、任务卡在 dispatched;
3. wp/v2 的 Yoast 字段走 ``meta`` 对象,``meta_data`` 是 Woo 的形状会被静默丢弃。

SEO 与 GEO 的差别只有三处,都在这个文件里:
- 每篇文章**自带分类**(一批里可能混着 factory 文和博文),而 GEO 一簇一个分类;
- webhook 路径 / 工作流名;
- 节点 id 由 slug 派生(不能和 GEO 撞)。

跑法:``python -m backend.app.modules.seo_series.n8n.build_workflow``
装法:改 ``workflow_entity`` 的同时**必须**写 ``workflow_history`` 的
``activeVersionId`` 版本——执行读的是历史表,只改 entity 无效(死规矩)。
"""

from __future__ import annotations

import json
from pathlib import Path

from ...content_core import n8n_publish as n8n
from ..content.constants import SEO_PUBLISH_PACKAGE_VERSION

WORKFLOW_ID = "barongSEOpublish001"
WEBHOOK_PATH = "barong-seo-publish"
WP_CREDENTIAL = {"id": "kaIcXMDT4cNA0GXm", "name": "Wordpress account"}

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

STICKY = f"""## barong控制台 · SEO系列 · 发布工艺/博客文章

**干嘛的**：接控制台 SEO 的发布派单（Webhook：`POST /webhook/{WEBHOOK_PATH}`），
把选中的**已批准** SEO 文章发布到 WordPress。

1. **取发布包**：按派单里的 `package_url` 拉一份 `{SEO_PUBLISH_PACKAGE_VERSION}`。
2. **建/更新文章**：首次建**草稿**（等人工发布），重推则原地更新，且**不动 status**。
3. **回填内链**：全部 post 建完后收齐 URL，二次 PUT 把占位替换成真实链接。
4. **回报控制台**：把 item_id → post_id/URL 回传，控制台记台账。

**三条不能改的**
- Code 节点必须 `$input.all().map()`——只取第一条会把整批压成一篇。
- IF 的两个分支都要汇到「整理回报」，否则没有内链的批次走死路。
- Yoast 走 `meta` 对象，不是 Woo 的 `meta_data`。

**分类**：每篇自带 `wp_category_id`（factory 文和博文分类不同）。
拿不到分类 id 的整单失败——**绝不发成无类目**。

- 派单来源：控制台 env `N8N_SEO_PUBLISH_WEBHOOK`
- 契约：backend/app/modules/seo_series/content/assemble.py
"""

BUILD_BODIES_JS = f"""
const pkg = $input.first().json;
if (pkg.schema_version !== '{SEO_PUBLISH_PACKAGE_VERSION}') {{
  throw new Error('拒绝发布：需要 {SEO_PUBLISH_PACKAGE_VERSION}');
}}
const articles = pkg.articles || [];
if (!articles.length) {{
  throw new Error('发布包里没有已批准的文章');
}}
return articles.map((a) => {{
  const seo = a.seo || {{}};
  // 每篇自己的分类:一批里可能混着 factory 文和博文。
  const categoryId = Number(a.wp_category_id);
  if (!Number.isInteger(categoryId) || categoryId <= 0) {{
    throw new Error('拒绝发布：文章没有带分类 id — ' + (a.title || a.item_id));
  }}
  // wp/v2 的 Yoast 字段走 `meta` 对象;`meta_data` 是 Woo 的形状,WP 会静默丢弃。
  const meta = {{}};
  if (seo.title) meta._yoast_wpseo_title = seo.title;
  if (seo.meta_description) meta._yoast_wpseo_metadesc = seo.meta_description;
  const body = {{
    title: a.title || '',
    content: a.html || '',
    excerpt: (a.text || '').slice(0, 300),
    categories: [categoryId],
  }};
  if (Object.keys(meta).length) body.meta = meta;
  if (seo.url_slug) body.slug = seo.url_slug;
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


def build() -> dict:
    from ...geo_series.n8n.build_workflow import (
        COLLECT_JS,
        DECIDE_JS,
        REPORT_JS,
    )

    return n8n.build_publish_workflow(
        n8n.PublishWorkflowConfig(
            workflow_id=WORKFLOW_ID,
            workflow_name="barong控制台-SEO系列-发布工艺与博客文章",
            webhook_path=WEBHOOK_PATH,
            sticky=STICKY,
            build_bodies_js=BUILD_BODIES_JS,
            # 建/更新的判断、URL 收集与回填、回报——三段与 GEO 完全一样,
            # 直接复用同一份 JS,不再抄一遍。
            decide_js=DECIDE_JS,
            collect_js=COLLECT_JS,
            report_js=REPORT_JS,
            node_ids=n8n.derived_node_ids(WORKFLOW_ID),
            wp_credential=WP_CREDENTIAL,
            version_id="3a7c9e51-8d24-4b16-8e30-5c9a1f6b2d47",
            project=PROJECT,
        )
    )


def main() -> None:
    target = Path(__file__).with_name("seo_publish_workflow.json")
    target.write_text(
        json.dumps(build(), ensure_ascii=False, separators=(", ", ": ")),
        encoding="utf-8",
    )
    print(f"wrote {target}")


if __name__ == "__main__":
    main()

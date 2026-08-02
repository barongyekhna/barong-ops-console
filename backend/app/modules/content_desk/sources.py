"""声明式内容源表 —— 内容台的心脏。

GEO 和 SEO 是两台**独立演化过**的引擎,不对称是历史事实,不是设计失误:

============  ==========================  ==========================
              GEO                         SEO
============  ==========================  ==========================
体裁列名      ``item_type``               ``item_kind``
父记录        簇 ``cluster_id``           选题 ``topic_id``
正文形状      sections + answer_blocks    只有 sections
review 权限   ``geo.content.execute``     ``seo.content.manage``
review 品牌门 无(发布时才拦)              有(409)
重写          同步 30s+                   排队
手动解读      有                          **无**(本模块补上)
发布粒度      整簇                        选中的 item_ids
============  ==========================  ==========================

把这些差异**写成一张表**而不是散在各个 ``if source == "geo"`` 里,是照
``content_core/consistency.py`` 的 ``ProductionCheck`` 先例。判据:加第三个
内容源时应该只加一行,不改任何逻辑。测试会断言 ``queries.py`` 里不出现
``"geo"`` / ``"seo"`` 字面量,把这条规矩钉死。

**权限:进门看自己的键,动手看来源的键。** 内容台的写操作和引擎自己的一样重
(批准上线、花钱重写、派单发到 WordPress)。只认 ``content.desk.*`` 等于开一条
权限洗白通道 —— 只有内容台权限的人能做他在 ``/geo/*`` 上被 403 拦住的事。
所以每个动作要两把钥匙,来源那把写在这张表里。

放行(``manage_permission``)一律比 review 高一档 —— 放行是**推翻门禁**,
比批准一篇更重。GEO 因此出现「能批准但不能放行」的组合,这是刻意的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ContentSource:
    """一台内容引擎在内容台眼里的样子。

    行为差异挂成**延迟导入的可调用字段**(``*_fn``),而不是在模块顶层 import
    geo/seo —— 内容台是聚合层,顶层 import 会把两个引擎连同它们的 worker
    依赖一起拖进任何 import 了内容台的进程。
    """

    key: str
    label: str
    # 人话的体裁名。买家看不到,但运营看到 "wholesale_guide" 只会皱眉。
    kind_labels: dict[str, str]

    # -- 表结构的不对称 ------------------------------------------------------
    kind_column: str
    parent_fk: str
    parent_label_column: str
    body_keys: tuple[str, ...]

    # -- 权限的不对称 --------------------------------------------------------
    read_permission: str
    review_permission: str
    execute_permission: str
    manage_permission: str

    # -- 行为的不对称 --------------------------------------------------------
    # review 时就拦品牌门(SEO),还是发布时才拦(GEO)
    review_requires_clean: bool
    # "sync" = 点了卡住等;"queued" = 排队后轮询
    revise_mode: str
    # "parent" = 整簇发;"items" = 发选中的几篇
    publish_unit: str

    # -- 该源独有的、要透给前端的列 ------------------------------------------
    # (输出键, ORM 列名)。写在表里而不是在 dto.py 里 if source.key == "geo",
    # 否则「加一行就够」这条规矩当场破功。
    extra_columns: tuple[tuple[str, str], ...]
    # 这个源的文章挂产品吗?挂就要把裸 UUID 解析成 SKU
    # (裸 UUID 对运营毫无意义,而 GEO 老的 review 端点正是返回裸 UUID)。
    resolves_product_labels: bool

    # -- 延迟导入的模型与函数 ------------------------------------------------
    item_model_fn: Callable[[], Any]
    parent_model_fn: Callable[[], Any]

    @property
    def is_sync_revise(self) -> bool:
        return self.revise_mode == "sync"


def _geo_item_model() -> Any:
    from ..geo_series.content.models import GeoContentItem

    return GeoContentItem


def _geo_parent_model() -> Any:
    from ..geo_series.content.models import GeoContentCluster

    return GeoContentCluster


def _seo_item_model() -> Any:
    from ..seo_series.content.models import SeoContentItem

    return SeoContentItem


def _seo_parent_model() -> Any:
    from ..seo_series.content.models import SeoTopic

    return SeoTopic


SOURCES: tuple[ContentSource, ...] = (
    ContentSource(
        key="geo",
        label="买家问句指南",
        kind_labels={
            "hub": "总览",
            "how_it_works": "原理",
            "comparison": "对比",
            "scenario": "场景",
            "qa": "问答",
            "question_answer": "问答",
            "product_spotlight": "产品专文",
        },
        kind_column="item_type",
        parent_fk="cluster_id",
        parent_label_column="title",
        body_keys=("sections", "answer_blocks"),
        read_permission="geo.content.read",
        review_permission="geo.content.execute",
        execute_permission="geo.content.execute",
        manage_permission="geo.content.manage",
        review_requires_clean=False,
        revise_mode="sync",
        publish_unit="parent",
        extra_columns=(("schema_type", "schema_type"), ("reviewed_at", "reviewed_at")),
        resolves_product_labels=True,
        item_model_fn=_geo_item_model,
        parent_model_fn=_geo_parent_model,
    ),
    ContentSource(
        key="seo",
        label="工艺与品牌文",
        kind_labels={
            "craft_story": "工艺",
            "material_explainer": "材料",
            "testing": "测试",
            "buying_guide": "选购",
            "wholesale_guide": "批发",
            "brand_story": "品牌",
        },
        kind_column="item_kind",
        parent_fk="topic_id",
        parent_label_column="keyword",
        body_keys=("sections",),
        read_permission="seo.content.read",
        review_permission="seo.content.manage",
        execute_permission="seo.content.execute",
        manage_permission="seo.content.manage",
        review_requires_clean=True,
        revise_mode="queued",
        publish_unit="items",
        extra_columns=(("destination", "destination"), ("links", "links_json")),
        resolves_product_labels=False,
        item_model_fn=_seo_item_model,
        parent_model_fn=_seo_parent_model,
    ),
)

SOURCE_BY_KEY: dict[str, ContentSource] = {s.key: s for s in SOURCES}


class UnknownSource(ValueError):
    """来源 key 不认识。**只认表里有的**——这个值会被拼进查询和权限判断。"""


def source_for(key: str) -> ContentSource:
    source = SOURCE_BY_KEY.get(str(key or "").strip())
    if source is None:
        raise UnknownSource(f"未知内容来源：{key!r}")
    return source


__all__ = [
    "SOURCES",
    "SOURCE_BY_KEY",
    "ContentSource",
    "UnknownSource",
    "source_for",
]

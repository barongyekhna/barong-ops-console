"""内置的「谷歌类目 → 零售店型」映射目录。**代码是真相源,前端不显示。**

2026-07-28 用户拍板:"即使新增加类目,我可能也不知道这个类目应该对应什么店型,
这其实是我最担心的问题。所以我反倒希望自动一些,把所有的店型以及对应的产品类目
全部写下来(特殊的不用写,比如武器,情趣用品)但是不在前端显示。当 K/P 管线上架
一款产品后,立刻根据类目自动落入对应的店型中,如果是还没有过产品的店型,直接显示
这几个新店型。"

设计要点:
- **只映射到第一/第二层前缀**,不逐条写 5595 个叶子类目。前缀会往下吃干净,
  所以谷歌以后新增叶子类目也自动归位,不用回来补表。
- **一个类目可以落进多个店型**(捏捏球既进礼品店也进玩具店)——这是对的,
  同一件货本来就能卖给几种店。
- **店型只在真的有货时才被建出来**。没货的店型不存在,界面上也就不会出现
  一堆空壳。第一次有产品落进来时才 materialise,并且带上它全部的类目前缀
  (这样以后的品自动进来)。
- **黑名单只挡自动映射**,不改变 K 那边能不能建这个类目。
"""

from __future__ import annotations

from typing import TypedDict


class StoreTypeSpec(TypedDict):
    key: str
    # 控制台里给用户看的中文名。
    label: str
    # **对外英文名**:网站是给美国买家看的,label 是中文,直接印上去买家看不懂
    # (2026-07-29 生成 /wholesale/ 时踩到:页面上出现"户外装备店")。
    public_label: str
    sort_order: int
    prefixes: tuple[tuple[str, ...], ...]
    # 挖客户用的搜索词模板,必须含 {city}。en 给 US/CA,es 给 MX。
    queries_en: tuple[str, ...]
    queries_es: tuple[str, ...]


# 永不自动映射:用户点名的武器和情趣用品,加上监管重、他也不做的品类。
# 这里挡的是"自动落进店型",不影响 K 那边建类目。
BLOCKED_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("Mature",),  # 情趣用品 / 武器
    ("Business & Industrial", "Law Enforcement"),  # 警械
    ("Business & Industrial", "Dentistry"),
    ("Business & Industrial", "Medical"),
    ("Business & Industrial", "Piercing & Tattooing"),
    ("Arts & Entertainment", "Hobbies & Creative Arts", "Collectibles",
     "Collectible Weapons"),
    ("Cameras & Optics", "Optics", "Scopes", "Weapon Scopes & Sights"),
    ("Cameras & Optics", "Camera & Optic Accessories", "Optic Accessories",
     "Weapon Scope & Sight Accessories"),
    ("Food, Beverages & Tobacco",),  # 食品烟酒:监管重且不是他的产线
    ("Health & Beauty", "Health Care"),  # 医疗器械
    ("Home & Garden", "Smoking Accessories"),
    ("Media",),
    ("Software",),
    ("Arts & Entertainment", "Event Tickets"),
)


STORE_TYPE_CATALOG: tuple[StoreTypeSpec, ...] = (
    {
        "key": "gift_shop",
        "label": "礼品/新奇店",
        "public_label": "Gift & novelty stores",
        "sort_order": 10,
        "prefixes": (
            ("Toys & Games",),
            ("Home & Garden", "Decor"),
            ("Arts & Entertainment", "Party & Celebration"),
        ),
        "queries_en": ("gift shop {city}", "novelty store {city}"),
        "queries_es": ("tienda de regalos {city}",),
    },
    {
        "key": "toy_store",
        "label": "玩具店",
        "public_label": "Toy stores",
        "sort_order": 20,
        "prefixes": (("Toys & Games",), ("Baby & Toddler",)),
        "queries_en": ("toy store {city}",),
        "queries_es": ("juguetería {city}",),
    },
    {
        "key": "pet_boutique",
        "label": "宠物精品店",
        "public_label": "Pet stores",
        "sort_order": 30,
        "prefixes": (("Animals & Pet Supplies",),),
        "queries_en": ("pet boutique {city}", "pet supply store {city}"),
        "queries_es": ("tienda de mascotas {city}",),
    },
    {
        "key": "outdoor_store",
        "label": "户外装备店",
        "public_label": "Outdoor & camping stores",
        "sort_order": 40,
        "prefixes": (
            ("Sporting Goods", "Outdoor Recreation"),
            ("Home & Garden", "Emergency Preparedness"),
        ),
        "queries_en": ("outdoor gear store {city}", "camping store {city}"),
        "queries_es": ("tienda de camping {city}",),
    },
    {
        "key": "vanlife_store",
        "label": "房车/改装店",
        "public_label": "RV & van conversion shops",
        "sort_order": 50,
        "prefixes": (
            ("Sporting Goods", "Outdoor Recreation"),
            ("Vehicles & Parts",),
        ),
        "queries_en": ("van life store {city}", "RV accessories store {city}"),
        "queries_es": ("tienda de accesorios para casa rodante {city}",),
    },
    {
        "key": "hardware_store",
        "label": "五金店",
        "public_label": "Hardware stores",
        "sort_order": 60,
        "prefixes": (("Hardware",),),
        "queries_en": ("hardware store {city}",),
        "queries_es": ("ferretería {city}",),
    },
    {
        "key": "home_goods_store",
        "label": "家居用品店",
        "public_label": "Home goods stores",
        "sort_order": 70,
        "prefixes": (
            ("Home & Garden", "Decor"),
            ("Home & Garden", "Household Supplies"),
            ("Home & Garden", "Linens & Bedding"),
            ("Furniture",),
        ),
        "queries_en": ("home goods store {city}", "home decor store {city}"),
        "queries_es": ("tienda de decoración para el hogar {city}",),
    },
    {
        "key": "kitchen_store",
        "label": "厨房用品店",
        "public_label": "Kitchen & cookware stores",
        "sort_order": 80,
        "prefixes": (
            ("Home & Garden", "Kitchen & Dining"),
            ("Home & Garden", "Household Appliances"),
            ("Home & Garden", "Household Appliance Accessories"),
        ),
        "queries_en": ("kitchen supply store {city}", "cookware store {city}"),
        "queries_es": ("tienda de artículos de cocina {city}",),
    },
    {
        "key": "garden_center",
        "label": "园艺中心",
        "public_label": "Garden centers",
        "sort_order": 90,
        "prefixes": (
            ("Home & Garden", "Lawn & Garden"),
            ("Home & Garden", "Plants"),
        ),
        "queries_en": ("garden center {city}", "nursery garden store {city}"),
        "queries_es": ("vivero jardinería {city}",),
    },
    {
        "key": "pool_spa_store",
        "label": "泳池/水疗店",
        "public_label": "Pool & spa stores",
        "sort_order": 100,
        "prefixes": (("Home & Garden", "Pool & Spa"),),
        "queries_en": ("pool supply store {city}", "hot tub store {city}"),
        "queries_es": ("tienda de albercas {city}",),
    },
    {
        "key": "lighting_store",
        "label": "灯具店",
        "public_label": "Lighting stores",
        "sort_order": 110,
        "prefixes": (
            ("Home & Garden", "Lighting"),
            ("Home & Garden", "Lighting Accessories"),
        ),
        "queries_en": ("lighting store {city}",),
        "queries_es": ("tienda de iluminación {city}",),
    },
    {
        "key": "bathroom_store",
        "label": "卫浴店",
        "public_label": "Bathroom & plumbing stores",
        "sort_order": 120,
        "prefixes": (
            ("Home & Garden", "Bathroom Accessories"),
            ("Hardware", "Plumbing"),
        ),
        "queries_en": ("bathroom fixtures store {city}", "plumbing supply {city}"),
        "queries_es": ("tienda de artículos de baño {city}",),
    },
    {
        "key": "beauty_supply",
        "label": "美妆/个护店",
        "public_label": "Beauty supply stores",
        "sort_order": 130,
        "prefixes": (
            ("Health & Beauty", "Personal Care"),
            ("Health & Beauty", "Jewelry Cleaning & Care"),
        ),
        "queries_en": ("beauty supply store {city}",),
        "queries_es": ("tienda de productos de belleza {city}",),
    },
    {
        "key": "baby_store",
        "label": "母婴店",
        "public_label": "Baby stores",
        "sort_order": 140,
        "prefixes": (("Baby & Toddler",),),
        "queries_en": ("baby store {city}", "baby boutique {city}"),
        "queries_es": ("tienda para bebés {city}",),
    },
    {
        "key": "sporting_goods_store",
        "label": "运动用品店",
        "public_label": "Sporting goods stores",
        "sort_order": 150,
        "prefixes": (
            ("Sporting Goods", "Athletics"),
            ("Sporting Goods", "Exercise & Fitness"),
            ("Sporting Goods", "Indoor Games"),
        ),
        "queries_en": ("sporting goods store {city}",),
        "queries_es": ("tienda de artículos deportivos {city}",),
    },
    {
        "key": "electronics_store",
        "label": "电子配件店",
        "public_label": "Electronics accessory stores",
        "sort_order": 160,
        "prefixes": (("Electronics",), ("Cameras & Optics",)),
        "queries_en": ("electronics accessories store {city}",),
        "queries_es": ("tienda de accesorios electrónicos {city}",),
    },
    {
        "key": "office_supply_store",
        "label": "办公用品店",
        "public_label": "Office supply stores",
        "sort_order": 170,
        "prefixes": (
            ("Office Supplies",),
            ("Business & Industrial", "Signage"),
        ),
        "queries_en": ("office supply store {city}",),
        "queries_es": ("papelería tienda de oficina {city}",),
    },
    {
        "key": "apparel_boutique",
        "label": "服饰精品店",
        "public_label": "Clothing boutiques",
        "sort_order": 180,
        "prefixes": (("Apparel & Accessories",),),
        "queries_en": ("clothing boutique {city}",),
        "queries_es": ("boutique de ropa {city}",),
    },
    {
        "key": "luggage_store",
        "label": "箱包店",
        "public_label": "Luggage stores",
        "sort_order": 190,
        "prefixes": (("Luggage & Bags",),),
        "queries_en": ("luggage store {city}",),
        "queries_es": ("tienda de maletas {city}",),
    },
    {
        "key": "auto_parts_store",
        "label": "汽配店",
        "public_label": "Auto parts stores",
        "sort_order": 200,
        "prefixes": (("Vehicles & Parts",),),
        "queries_en": ("auto parts store {city}",),
        "queries_es": ("refaccionaria automotriz {city}",),
    },
    {
        "key": "craft_store",
        "label": "手工/文创店",
        "public_label": "Craft & art supply stores",
        "sort_order": 210,
        "prefixes": (
            ("Arts & Entertainment", "Hobbies & Creative Arts"),
        ),
        "queries_en": ("craft store {city}", "art supply store {city}"),
        "queries_es": ("tienda de manualidades {city}",),
    },
    {
        "key": "farm_supply",
        "label": "农资店",
        "public_label": "Farm supply stores",
        "sort_order": 220,
        "prefixes": (
            ("Business & Industrial", "Agriculture"),
            ("Hardware", "Fencing & Barriers"),
        ),
        "queries_en": ("farm supply store {city}", "feed store {city}"),
        "queries_es": ("tienda agropecuaria {city}",),
    },
    {
        "key": "safety_supply",
        "label": "劳保/安全用品店",
        "public_label": "Safety supply stores",
        "sort_order": 230,
        "prefixes": (
            ("Business & Industrial", "Work Safety Protective Gear"),
            ("Home & Garden", "Flood, Fire & Gas Safety"),
            ("Home & Garden", "Business & Home Security"),
        ),
        "queries_en": ("safety supply store {city}",),
        "queries_es": ("tienda de equipo de seguridad industrial {city}",),
    },
    {
        "key": "restaurant_supply",
        "label": "餐饮设备店",
        "public_label": "Restaurant supply stores",
        "sort_order": 240,
        "prefixes": (("Business & Industrial", "Food Service"),),
        "queries_en": ("restaurant supply store {city}",),
        "queries_es": ("tienda de equipo para restaurantes {city}",),
    },
)

_BY_KEY = {spec["key"]: spec for spec in STORE_TYPE_CATALOG}


def spec_for(key: str) -> StoreTypeSpec | None:
    return _BY_KEY.get(key)


def _starts_with(path: list[str], prefix: tuple[str, ...]) -> bool:
    return tuple(path[: len(prefix)]) == prefix


def is_blocked(category_path: list[str] | None) -> bool:
    """武器/情趣用品/监管品类:永不自动落进任何店型。"""
    path = [str(part).strip() for part in (category_path or []) if str(part).strip()]
    if not path:
        return False
    return any(_starts_with(path, prefix) for prefix in BLOCKED_PREFIXES)


def store_types_for_category(
    category_path: list[str] | None,
) -> list[StoreTypeSpec]:
    """一个产品类目该落进哪些店型。可能是多个,也可能一个都没有。"""
    path = [str(part).strip() for part in (category_path or []) if str(part).strip()]
    if not path or is_blocked(path):
        return []
    matched = [
        spec
        for spec in STORE_TYPE_CATALOG
        if any(_starts_with(path, prefix) for prefix in spec["prefixes"])
    ]
    return sorted(matched, key=lambda spec: spec["sort_order"])

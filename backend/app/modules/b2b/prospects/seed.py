"""种子数据：查询模板 + 目标城市。

城市**不是"前 N 大"**——用户 2026-07-27 拍板:大城市精品店每周收几十封开发
信,小镇店铺几乎没人找过,小城市机会反而更大。所以这里给的是覆盖面而不是
榜单,人口只用于排序。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import B2BProspectQuery, B2BTargetCity

# (store_type, label, country, language, template)
SEED_QUERIES = [
    ("pet_boutique", "宠物精品店", "US", "en", "pet boutique {city}"),
    ("pet_boutique", "宠物精品店", "US", "en", "independent pet store {city}"),
    ("pet_boutique", "宠物精品店", "CA", "en", "pet boutique {city}"),
    ("pet_boutique", "宠物精品店", "MX", "es", "tienda de mascotas {city}"),
    ("pet_boutique", "宠物精品店", "MX", "es", "boutique para mascotas {city}"),
    ("outdoor_store", "户外装备店", "US", "en", "outdoor gear store {city}"),
    ("outdoor_store", "户外装备店", "CA", "en", "outdoor gear store {city}"),
    ("outdoor_store", "户外装备店", "MX", "es", "tienda de camping {city}"),
    ("vanlife_store", "房车/改装店", "US", "en", "van life store {city}"),
    ("vanlife_store", "房车/改装店", "US", "en", "overland outfitter {city}"),
    ("vanlife_store", "房车/改装店", "CA", "en", "van life store {city}"),
    ("gift_shop", "礼品店", "US", "en", "gift shop {city}"),
    ("gift_shop", "礼品店", "CA", "en", "gift shop {city}"),
    ("gift_shop", "礼品店", "MX", "es", "tienda de regalos {city}"),
]

# (country, region, city, population)
SEED_CITIES = [
    ("US", "NY", "New York", 8300000), ("US", "CA", "Los Angeles", 3900000),
    ("US", "IL", "Chicago", 2700000), ("US", "TX", "Houston", 2300000),
    ("US", "AZ", "Phoenix", 1600000), ("US", "PA", "Philadelphia", 1600000),
    ("US", "TX", "San Antonio", 1450000), ("US", "CA", "San Diego", 1400000),
    ("US", "TX", "Dallas", 1300000), ("US", "TX", "Austin", 970000),
    ("US", "CO", "Denver", 715000), ("US", "WA", "Seattle", 750000),
    ("US", "OR", "Portland", 650000), ("US", "TN", "Nashville", 690000),
    ("US", "GA", "Atlanta", 500000), ("US", "FL", "Miami", 450000),
    ("US", "MN", "Minneapolis", 430000), ("US", "UT", "Salt Lake City", 200000),
    ("US", "MT", "Bozeman", 55000), ("US", "CO", "Boulder", 105000),
    ("US", "VT", "Burlington", 45000), ("US", "ME", "Portland", 68000),
    ("US", "NC", "Asheville", 94000), ("US", "CA", "Santa Cruz", 62000),
    ("US", "WY", "Jackson", 11000), ("US", "CO", "Durango", 19000),
    ("US", "UT", "Moab", 5300), ("US", "AZ", "Flagstaff", 76000),
    ("US", "ID", "Boise", 240000), ("US", "MT", "Missoula", 76000),
    ("CA", "ON", "Toronto", 2900000), ("CA", "QC", "Montreal", 1800000),
    ("CA", "BC", "Vancouver", 675000), ("CA", "AB", "Calgary", 1300000),
    ("CA", "AB", "Edmonton", 1000000), ("CA", "ON", "Ottawa", 1000000),
    ("CA", "BC", "Victoria", 92000), ("CA", "BC", "Kelowna", 145000),
    ("CA", "AB", "Banff", 8300), ("CA", "BC", "Whistler", 14000),
    ("MX", "CDMX", "Ciudad de México", 9200000),
    ("MX", "JAL", "Guadalajara", 1400000),
    ("MX", "NL", "Monterrey", 1140000), ("MX", "PUE", "Puebla", 1690000),
    ("MX", "QRO", "Querétaro", 1050000), ("MX", "YUC", "Mérida", 995000),
    ("MX", "BCN", "Tijuana", 1900000), ("MX", "GUA", "León", 1720000),
    ("MX", "QROO", "Cancún", 890000), ("MX", "JAL", "Puerto Vallarta", 290000),
    # 加拿大小镇。原来只有 4 个小城,4:1 混排凑不够小城,还是会往大城市倒。
    ("CA", "AB", "Canmore", 15000), ("CA", "BC", "Nelson", 11000),
    ("CA", "BC", "Squamish", 24000), ("CA", "BC", "Revelstoke", 8300),
    ("CA", "ON", "Collingwood", 25000), ("CA", "NS", "Halifax", 440000),
    ("CA", "BC", "Kamloops", 100000), ("CA", "ON", "Huntsville", 21000),
    # 墨西哥小城。原来 9 大 1 小,小城优先在墨西哥完全落不了地。
    # 挑的是旅游/侨居型城镇——有可支配收入的买家,精品店才活得下去。
    ("MX", "GUA", "San Miguel de Allende", 175000),
    ("MX", "QROO", "Playa del Carmen", 300000),
    ("MX", "QROO", "Tulum", 46000), ("MX", "OAX", "Oaxaca de Juárez", 270000),
    ("MX", "CHP", "San Cristóbal de las Casas", 185000),
    ("MX", "MEX", "Valle de Bravo", 30000),
    ("MX", "OAX", "Puerto Escondido", 30000),
    ("MX", "BCS", "La Paz", 250000), ("MX", "BCS", "Todos Santos", 6500),
    ("MX", "NAY", "Sayulita", 2600),
]


def seed_prospect_config(db: Session) -> dict[str, int]:
    """幂等:已存在的跳过,只补缺的。"""
    queries_added = 0
    for store_type, label, country, language, template in SEED_QUERIES:
        exists = db.scalar(
            select(B2BProspectQuery.id).where(
                B2BProspectQuery.store_type == store_type,
                B2BProspectQuery.country == country,
                B2BProspectQuery.query_template == template,
            )
        )
        if exists is not None:
            continue
        db.add(
            B2BProspectQuery(
                store_type=store_type,
                store_type_label=label,
                country=country,
                language=language,
                query_template=template,
            )
        )
        queries_added += 1

    cities_added = 0
    for country, region, city, population in SEED_CITIES:
        exists = db.scalar(
            select(B2BTargetCity.id).where(
                B2BTargetCity.country == country,
                B2BTargetCity.region == region,
                B2BTargetCity.city == city,
            )
        )
        if exists is not None:
            continue
        db.add(
            B2BTargetCity(
                country=country,
                region=region,
                city=city,
                population=population,
            )
        )
        cities_added += 1

    db.commit()
    return {"queries_added": queries_added, "cities_added": cities_added}

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from r_system_v2.ra.auto_profit import match_rw_products_for_query


def test_auto_profit_rw_match_does_not_fallback_to_unrelated_products() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE products_rw (
                  asin TEXT PRIMARY KEY,
                  marketplace TEXT,
                  source_query TEXT,
                  title TEXT,
                  title_zh TEXT,
                  image_url TEXT,
                  brand TEXT,
                  category TEXT,
                  category_id TEXT,
                  category_path TEXT,
                  price REAL,
                  state TEXT,
                  skill_score INTEGER,
                  features TEXT,
                  updated_at TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO products_rw (
                  asin, marketplace, source_query, title, title_zh, category,
                  category_path, price, state, skill_score, updated_at
                )
                VALUES
                  (
                    'B0TABLE001', 'US', '露营桌', 'Folding Camping Table',
                    '折叠露营桌', '户外桌椅', '户外 > 露营 > 桌子',
                    39.99, 'rule_passed', 88, '2026-07-05T01:00:00'
                  ),
                  (
                    'B0STOVE001', 'US', '露营炉', 'Portable Camping Stove',
                    '便携式露营炉', '户外炉具', '户外 > 露营 > 炉具',
                    29.99, 'rule_passed', 90, '2026-07-05T02:00:00'
                  )
                """
            )
        )

    with Session(engine) as session:
        rows = match_rw_products_for_query(session, query="桌子", limit=10)

    assert [row["asin"] for row in rows] == ["B0TABLE001"]

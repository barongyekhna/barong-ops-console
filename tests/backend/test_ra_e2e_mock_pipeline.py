from __future__ import annotations

from decimal import Decimal
import json
import sqlite3

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from r_system_v2.ra.ai_selection_mock import run_mock_ai_selection_for_run
from r_system_v2.ra.supplier_discovery import discover_1688_supplier_offers


def test_ra_e2e_mock_pipeline_from_rw_to_report(monkeypatch) -> None:
    sqlite3.register_adapter(Decimal, lambda value: float(value))
    monkeypatch.setenv("RA_SUPPLIER_SOURCE_MODE", "mock_1688_api")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for ddl in _schema():
            connection.execute(text(ddl))
        features = {
            "monthly_sales": 680,
            "fba_fee_usd": 6.2,
            "package_weight_g": 760,
            "package_length_mm": 360,
            "package_width_mm": 180,
            "package_height_mm": 120,
            "image_candidates": ["https://example.test/B0RAE2E001.jpg"],
        }
        connection.execute(
            text(
                """
                INSERT INTO products_rw (
                  asin, marketplace, source_query, title, title_zh, image_url,
                  brand, category, category_id, category_path, price, state,
                  skill_score, features, bsr, reviews, seller_count, rating,
                  fulfillment_method, lithium_battery_warning, updated_at
                )
                VALUES (
                  'B0RAE2E001', 'US', '露营椅', 'Camping Folding Chair',
                  '露营折叠椅', 'https://example.test/B0RAE2E001.jpg',
                  'Generic', 'Sports & Outdoors', '3375251',
                  'Sports & Outdoors > Outdoor Recreation > Camping Furniture',
                  39.99, 'rule_passed', 86, :features, 2400, 180, 6, 4.5,
                  'FBA', 0, CURRENT_TIMESTAMP
                )
                """
            ),
            {"features": json.dumps(features, ensure_ascii=False)},
        )
        connection.execute(
            text(
                """
                INSERT INTO ra_selection_runs (
                  run_id, org_id, channel, status, filters, counts, runtime_mode,
                  created_at, updated_at
                )
                VALUES (
                  'run-e2e', 'org-e2e', 'profit_auto', 'running',
                  '{}', '{}', 'background_profit_queue',
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
        )

    with Session(engine) as session:
        discovery = discover_1688_supplier_offers(
            session,
            org_id="org-e2e",
            run_id="run-e2e",
            asin="B0RAE2E001",
            result_limit=3,
            auto_calculate=True,
            exchange_rate_usd_cny=Decimal("7.20"),
        )
        ai_result = run_mock_ai_selection_for_run(
            session,
            org_id="org-e2e",
            run_id="run-e2e",
            channel="amazon",
        )

        assert discovery["counts"]["candidate_offers"] == 3
        assert discovery["profit_run"]["counts"]["processed"] == 3
        assert ai_result["counts"]["ai_candidates"] == 1
        assert ai_result["counts"]["final_decisions"] == 1
        assert ai_result["counts"]["reports"] == 1

        eval_rows = session.execute(
            text(
                """
                SELECT layer, skill_version, skill_hash, payload
                FROM ra_ai_evaluations
                WHERE run_id = 'run-e2e'
                ORDER BY created_at ASC
                """
            )
        ).mappings().all()
        assert [row["layer"] for row in eval_rows] == ["deepseek", "gpt", "opus"]
        assert {row["skill_version"] for row in eval_rows} == {"v1"}
        assert all(len(str(row["skill_hash"])) == 64 for row in eval_rows)
        assert all(json.loads(row["payload"])["skill"]["file_keys"] == ["skill", "amazon", "shared"] for row in eval_rows)

        final_row = session.execute(
            text("SELECT verdict, final_score, payload FROM ra_final_decisions LIMIT 1")
        ).mappings().one()
        assert final_row["verdict"] in {"pass", "review"}
        assert int(final_row["final_score"]) >= 58
        assert json.loads(final_row["payload"])["mock"] is True

        report_count = session.execute(
            text("SELECT COUNT(*) AS count FROM ra_reports WHERE status = 'mock_ready'")
        ).mappings().one()
        assert int(report_count["count"]) == 1


def _schema() -> list[str]:
    return [
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
          price NUMERIC,
          state TEXT,
          skill_score INTEGER,
          features TEXT,
          bsr INTEGER,
          reviews INTEGER,
          seller_count INTEGER,
          rating NUMERIC,
          fulfillment_method TEXT,
          lithium_battery_warning BOOLEAN,
          updated_at TEXT
        )
        """,
        """
        CREATE TABLE ra_selection_runs (
          run_id TEXT PRIMARY KEY,
          org_id TEXT NOT NULL,
          channel TEXT NOT NULL,
          status TEXT NOT NULL,
          triggered_by TEXT,
          filters TEXT NOT NULL DEFAULT '{}',
          counts TEXT NOT NULL DEFAULT '{}',
          runtime_mode TEXT NOT NULL DEFAULT 'framework_only',
          started_at TEXT,
          finished_at TEXT,
          created_at TEXT,
          updated_at TEXT
        )
        """,
        """
        CREATE TABLE ra_candidates (
          id TEXT PRIMARY KEY,
          org_id TEXT NOT NULL,
          run_id TEXT,
          source_asin TEXT NOT NULL,
          marketplace TEXT,
          source_state TEXT,
          title TEXT,
          title_zh TEXT,
          channel_hint TEXT,
          candidate_status TEXT,
          snapshot TEXT NOT NULL DEFAULT '{}',
          imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE ra_supplier_searches (
          id TEXT PRIMARY KEY,
          org_id TEXT NOT NULL,
          run_id TEXT,
          candidate_id TEXT,
          asin TEXT,
          query TEXT,
          provider TEXT,
          status TEXT,
          result_count INTEGER,
          payload TEXT NOT NULL DEFAULT '{}',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE ra_supplier_offers (
          id TEXT PRIMARY KEY,
          org_id TEXT NOT NULL,
          search_id TEXT,
          candidate_id TEXT,
          asin TEXT,
          supplier_name TEXT,
          supplier_url TEXT,
          unit_price_cny NUMERIC,
          moq INTEGER,
          rating NUMERIC,
          match_score INTEGER,
          offer_status TEXT,
          payload TEXT NOT NULL DEFAULT '{}',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE ra_profit_snapshots (
          id TEXT PRIMARY KEY,
          org_id TEXT NOT NULL,
          candidate_id TEXT,
          asin TEXT,
          sell_price_usd NUMERIC,
          landed_cost_usd NUMERIC,
          amazon_fees_usd NUMERIC,
          net_profit_usd NUMERIC,
          net_margin NUMERIC,
          roi NUMERIC,
          confidence TEXT,
          payload TEXT NOT NULL DEFAULT '{}',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE ra_ai_evaluations (
          id TEXT PRIMARY KEY,
          org_id TEXT NOT NULL,
          run_id TEXT,
          candidate_id TEXT,
          asin TEXT,
          layer TEXT,
          model_role TEXT,
          model_name TEXT,
          score INTEGER,
          verdict TEXT,
          skill_version TEXT,
          skill_hash TEXT,
          payload TEXT NOT NULL DEFAULT '{}',
          in_tokens INTEGER,
          out_tokens INTEGER,
          cost_usd NUMERIC,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE ra_final_decisions (
          id TEXT PRIMARY KEY,
          org_id TEXT NOT NULL,
          run_id TEXT,
          candidate_id TEXT,
          asin TEXT,
          final_score INTEGER,
          verdict TEXT,
          channel TEXT,
          barrier_type TEXT,
          decision_reason TEXT,
          payload TEXT NOT NULL DEFAULT '{}',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE ra_reports (
          report_id TEXT PRIMARY KEY,
          org_id TEXT NOT NULL,
          run_id TEXT,
          candidate_id TEXT,
          asin TEXT,
          status TEXT,
          title TEXT,
          summary TEXT,
          payload TEXT NOT NULL DEFAULT '{}',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE ra_alerts (
          id TEXT PRIMARY KEY,
          org_id TEXT NOT NULL,
          severity TEXT,
          alert_type TEXT,
          message TEXT,
          payload TEXT NOT NULL DEFAULT '{}',
          acknowledged_at TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]

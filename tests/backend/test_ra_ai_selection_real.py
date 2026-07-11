from __future__ import annotations

from decimal import Decimal
import json
import sqlite3
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import R_ANALYSIS_MODULE_ID, SecretManager
from r_system_v2.ra.ai_selection import run_ai_selection_for_candidate, run_ai_selection_for_run


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def test_real_ra_ai_chain_writes_competition_and_three_layers(monkeypatch) -> None:
    # Opus per-candidate is cost-gated off by default; enable it so the full
    # prescreen → GPT → Opus chain is exercised.
    monkeypatch.setenv("RA_OPUS_PER_CANDIDATE", "1")
    sqlite3.register_adapter(Decimal, lambda value: float(value))
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for ddl in _schema():
            connection.execute(text(ddl))
        connection.execute(
            text(
                """
                INSERT INTO ra_prescreen (
                  id, org_id, asin, score, verdict, channel_guess, reason,
                  evidence, model, mode, created_at
                )
                VALUES (
                  'prescreen-real-ai', 'org-real-ai', 'B0REALAI001', 78, 'keep',
                  'amazon', 'DeepSeek 初筛：竞争可攻，需求稳定。', '{}',
                  'deepseek-v4-pro', 'enforce', CURRENT_TIMESTAMP
                )
                """
            )
        )
        product_features = {
            "monthly_sales": 720,
            "fba_fee_usd": 6.2,
            "image_candidates": ["https://example.test/B0REALAI001.jpg"],
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
                  'B0REALAI001', 'US', '露营椅', 'Camping Folding Chair',
                  '露营折叠椅', 'https://example.test/B0REALAI001.jpg',
                  'Generic', 'Sports & Outdoors', '3375251',
                  'Sports & Outdoors > Outdoor Recreation > Camping Furniture',
                  39.99, 'rule_passed', 86, :features, 2400, 180, 6, 4.5,
                  'FBA', 0, CURRENT_TIMESTAMP
                )
                """
            ),
            {"features": json.dumps(product_features, ensure_ascii=False)},
        )
        connection.execute(
            text(
                """
                INSERT INTO ra_selection_runs (
                  run_id, org_id, channel, status, filters, counts, runtime_mode,
                  created_at, updated_at
                )
                VALUES (
                  'run-real-ai', 'org-real-ai', 'profit_auto', 'running',
                  '{}', '{}', 'background_profit_queue',
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO ra_candidates (
                  id, org_id, run_id, source_asin, marketplace, title, title_zh,
                  candidate_status, snapshot
                )
                VALUES (
                  'candidate-real-ai', 'org-real-ai', 'run-real-ai', 'B0REALAI001',
                  'US', 'Camping Folding Chair', '露营折叠椅',
                  'profit_passed', '{}'
                )
                """
            )
        )
        profit_payload = {
            "verdict": "pass",
            "gross_profit_usd": 12.34,
            "gross_margin": 0.31,
            "supplier": {
                "supplier_name": "露营椅源头工厂",
                "supplier_url": "https://detail.1688.com/offer/123.html",
                "unit_price_cny": 42.0,
                "moq": 1,
                "match_score": 91,
                "one_piece_hint": True,
            },
        }
        connection.execute(
            text(
                """
                INSERT INTO ra_profit_snapshots (
                  id, org_id, candidate_id, asin, sell_price_usd,
                  net_profit_usd, net_margin, roi, confidence, payload
                )
                VALUES (
                  'profit-real-ai', 'org-real-ai', 'candidate-real-ai',
                  'B0REALAI001', 39.99, 12.34, 0.31, 0.72, 'high', :payload
                )
                """
            ),
            {"payload": json.dumps(profit_payload, ensure_ascii=False)},
        )

    def fake_resolver(_db, *, org_id: str, module_id: str, key_alias: str):
        assert org_id == "org-real-ai"
        values = {
            (R_ANALYSIS_MODULE_ID, "deepseek"): ("deepseek-secret", "https://deepseek.test"),
            (R_ANALYSIS_MODULE_ID, "4sapi"): ("foursapi-secret", "https://foursapi.test/v1"),
            (R_ANALYSIS_MODULE_ID, "rainforest"): ("rainforest-secret", "https://rainforest.test"),
        }
        value = values.get((module_id, key_alias))
        if value is None:
            raise RuntimeError("missing")
        return SimpleNamespace(
            module_id=module_id,
            key_alias=key_alias,
            key_id=f"{key_alias}-id",
            url=value[1],
            header_value=f"Bearer {value[0]}",
            query_param_value=None,
        )

    monkeypatch.setattr(
        "r_system_v2.core.secret_manager._backend_resolver",
        lambda: (fake_resolver, RuntimeError, RuntimeError),
    )
    SecretManager.invalidate_cache()

    def fake_rainforest_urlopen(_request, timeout: int = 40):
        return _FakeResponse(
            {
                "request_info": {"credits_used": 2, "credits_remaining": 998},
                "search_results": [
                    {
                        "position": 1,
                        "asin": "B0TOP001",
                        "title": "BrandA Camping Folding Chair",
                        "rating": 4.6,
                        "ratings_total": 500,
                    },
                    {
                        "position": 2,
                        "asin": "B0TOP002",
                        "title": "BrandB Portable Chair",
                        "rating": 4.4,
                        "ratings_total": 45,
                    },
                    {
                        "position": 3,
                        "asin": "B0TOP003",
                        "title": "Generic Outdoor Chair",
                        "rating": 4.3,
                        "ratings_total": 80,
                    },
                ],
            }
        )

    def fake_ai_urlopen(request, timeout: int = 75):
        payload = json.loads(request.data.decode("utf-8"))
        user_payload = json.loads(payload["messages"][-1]["content"])
        layer = user_payload["layer"]
        content = json.dumps(
            {
                "score": 82,
                "verdict": "pass",
                "reason": f"{layer} 认为该产品需求、竞争和利润结构可继续推进。",
                "advantages": ["月销量和利润率达标", "页一评论墙可攻"],
                "risks": ["需要人工复核供应商稳定性"],
                "barrier_type": "none",
                "channel_guess": "amazon",
            },
            ensure_ascii=False,
        )
        if "/v1/messages" in request.full_url:
            return _FakeResponse(
                {
                    "content": [{"type": "text", "text": content}],
                    "usage": {"input_tokens": 120, "output_tokens": 60},
                }
            )
        return _FakeResponse(
            {
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 60},
            }
        )

    monkeypatch.setattr("r_system_v2.ra.competition.urlopen", fake_rainforest_urlopen)
    monkeypatch.setattr("r_system_v2.ra.ai_selection.urlopen", fake_ai_urlopen)

    with Session(engine) as session:
        result = run_ai_selection_for_run(
            session,
            org_id="org-real-ai",
            run_id="run-real-ai",
            channel="amazon",
        )

        assert result["mock"] is False
        assert result["counts"]["ai_candidates"] == 1
        assert result["counts"]["ai_evaluations"] == 3
        assert result["counts"]["ai_pass"] == 1
        assert result["counts"]["rainforest_snapshots"] == 1
        assert result["counts"]["rainforest_credits_used"] == 2

        competition = session.execute(
            text("SELECT review_wall_max, credits_used, page_one_sample FROM ra_competition_snapshots")
        ).mappings().one()
        assert int(competition["review_wall_max"]) == 500
        assert int(competition["credits_used"]) == 2

        eval_rows = session.execute(
            text(
                """
                SELECT layer, model_name, payload
                FROM ra_ai_evaluations
                WHERE run_id = 'run-real-ai'
                ORDER BY created_at ASC
                """
            )
        ).mappings().all()
        assert [row["layer"] for row in eval_rows] == ["prescreen", "gpt", "opus"]
        assert all(not str(row["model_name"]).startswith("mock-") for row in eval_rows)
        # The stored prescreen surfaces as a context layer without competition
        # data; the judge layers must embed the Rainforest snapshot.
        assert all(
            json.loads(row["payload"])["competition"]["review_wall_max"] == 500
            for row in eval_rows
            if row["layer"] in {"gpt", "opus"}
        )

        final = session.execute(
            text("SELECT verdict, final_score, payload FROM ra_final_decisions LIMIT 1")
        ).mappings().one()
        assert final["verdict"] == "pass"
        assert int(final["final_score"]) == 82
        assert json.loads(final["payload"])["competition"]["review_wall_max"] == 500


def test_real_ra_ai_chain_can_run_one_candidate_without_touching_siblings(monkeypatch) -> None:
    sqlite3.register_adapter(Decimal, lambda value: float(value))
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for ddl in _schema():
            connection.execute(text(ddl))
        for index, asin in enumerate(("B0REALAI101", "B0REALAI102"), start=1):
            features = {
                "monthly_sales": 500 + index,
                "fba_fee_usd": 5.0,
                "image_candidates": [f"https://example.test/{asin}.jpg"],
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
                      :asin, 'US', '收纳架', :title, :title_zh, :image_url,
                      'Generic', 'Home & Kitchen', '1000',
                      'Home & Kitchen > Storage', 35.99, 'rule_passed',
                      84, :features, 1800, 120, 5, 4.4,
                      'FBA', 0, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "asin": asin,
                    "title": f"Storage Rack {index}",
                    "title_zh": f"收纳架 {index}",
                    "image_url": f"https://example.test/{asin}.jpg",
                    "features": json.dumps(features, ensure_ascii=False),
                },
            )
        connection.execute(
            text(
                """
                INSERT INTO ra_selection_runs (
                  run_id, org_id, channel, status, filters, counts, runtime_mode,
                  created_at, updated_at
                )
                VALUES (
                  'run-real-ai-one', 'org-real-ai', 'profit_auto', 'running',
                  '{}', '{}', 'background_profit_queue',
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
        )
        for index, asin in enumerate(("B0REALAI101", "B0REALAI102"), start=1):
            candidate_id = f"candidate-real-ai-{index}"
            connection.execute(
                text(
                    """
                    INSERT INTO ra_candidates (
                      id, org_id, run_id, source_asin, marketplace, title, title_zh,
                      candidate_status, snapshot
                    )
                    VALUES (
                      :candidate_id, 'org-real-ai', 'run-real-ai-one', :asin,
                      'US', :title, :title_zh, 'profit_passed', '{}'
                    )
                    """
                ),
                {
                    "candidate_id": candidate_id,
                    "asin": asin,
                    "title": f"Storage Rack {index}",
                    "title_zh": f"收纳架 {index}",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO ra_profit_snapshots (
                      id, org_id, candidate_id, asin, sell_price_usd,
                      net_profit_usd, net_margin, roi, confidence, payload
                    )
                    VALUES (
                      :snapshot_id, 'org-real-ai', :candidate_id, :asin,
                      35.99, 9.50, 0.27, 0.60, 'high', :payload
                    )
                    """
                ),
                {
                    "snapshot_id": f"profit-real-ai-{index}",
                    "candidate_id": candidate_id,
                    "asin": asin,
                    "payload": json.dumps(
                        {
                            "verdict": "pass",
                            "gross_profit_usd": 9.5,
                            "gross_margin": 0.27,
                            "supplier": {
                                "supplier_name": "源头工厂",
                                "supplier_url": "https://detail.1688.com/offer/123.html",
                                "unit_price_cny": 38.0,
                                "moq": 1,
                                "match_score": 90,
                                "one_piece_hint": True,
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            )

    def fake_resolver(_db, *, org_id: str, module_id: str, key_alias: str):
        assert org_id == "org-real-ai"
        values = {
            (R_ANALYSIS_MODULE_ID, "deepseek"): ("deepseek-secret", "https://deepseek.test"),
            (R_ANALYSIS_MODULE_ID, "4sapi"): ("foursapi-secret", "https://foursapi.test/v1"),
            (R_ANALYSIS_MODULE_ID, "rainforest"): ("rainforest-secret", "https://rainforest.test"),
        }
        value = values.get((module_id, key_alias))
        if value is None:
            raise RuntimeError("missing")
        return SimpleNamespace(
            module_id=module_id,
            key_alias=key_alias,
            key_id=f"{key_alias}-id",
            url=value[1],
            header_value=f"Bearer {value[0]}",
            query_param_value=None,
        )

    monkeypatch.setattr(
        "r_system_v2.core.secret_manager._backend_resolver",
        lambda: (fake_resolver, RuntimeError, RuntimeError),
    )
    SecretManager.invalidate_cache()

    def fake_rainforest_urlopen(_request, timeout: int = 40):
        return _FakeResponse(
            {
                "request_info": {"credits_used": 1, "credits_remaining": 999},
                "search_results": [{"position": 1, "asin": "B0TOP101", "ratings_total": 300}],
            }
        )

    def fake_ai_urlopen(request, timeout: int = 75):
        payload = json.loads(request.data.decode("utf-8"))
        user_payload = json.loads(payload["messages"][-1]["content"])
        content = json.dumps(
            {
                "score": 86,
                "verdict": "pass",
                "reason": f"{user_payload['layer']} 单候选实时审核通过。",
                "advantages": ["利润和需求达标"],
                "risks": [],
                "barrier_type": "none",
                "channel_guess": "amazon",
            },
            ensure_ascii=False,
        )
        if "/v1/messages" in request.full_url:
            return _FakeResponse(
                {
                    "content": [{"type": "text", "text": content}],
                    "usage": {"input_tokens": 80, "output_tokens": 40},
                }
            )
        return _FakeResponse(
            {
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 80, "completion_tokens": 40},
            }
        )

    monkeypatch.setattr("r_system_v2.ra.competition.urlopen", fake_rainforest_urlopen)
    monkeypatch.setattr("r_system_v2.ra.ai_selection.urlopen", fake_ai_urlopen)

    with Session(engine) as session:
        result = run_ai_selection_for_candidate(
            session,
            org_id="org-real-ai",
            run_id="run-real-ai-one",
            candidate_id="candidate-real-ai-1",
            channel="amazon",
        )

        assert result["counts"]["ai_candidates"] == 1
        assert result["counts"]["ai_pass"] == 1
        decision_rows = session.execute(
            text(
                """
                SELECT candidate_id, verdict
                FROM ra_final_decisions
                WHERE run_id = 'run-real-ai-one'
                """
            )
        ).mappings().all()
        assert [row["candidate_id"] for row in decision_rows] == ["candidate-real-ai-1"]
        status_rows = session.execute(
            text(
                """
                SELECT id, candidate_status
                FROM ra_candidates
                ORDER BY id ASC
                """
            )
        ).mappings().all()
        assert status_rows[0]["candidate_status"] == "ai_passed"
        assert status_rows[1]["candidate_status"] == "profit_passed"


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
        CREATE TABLE ra_prescreen (
          id TEXT PRIMARY KEY,
          org_id TEXT NOT NULL,
          asin TEXT NOT NULL,
          score INTEGER,
          verdict TEXT,
          channel_guess TEXT,
          reason TEXT,
          evidence TEXT NOT NULL DEFAULT '{}',
          model TEXT,
          mode TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]

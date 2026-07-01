-- R System v2 Warehouse (R-W) PostgreSQL schema.
-- Scope: products_rw, enrich_queue, rule_results.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  CREATE TYPE rw_product_state AS ENUM (
    'discovered',
    'enriched',
    'rule_passed',
    'rejected'
  );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS products_rw (
  asin TEXT PRIMARY KEY,
  marketplace TEXT NOT NULL DEFAULT 'US',
  source_query TEXT,
  title TEXT,
  brand TEXT,
  category TEXT,
  price NUMERIC(10,2),
  bsr INTEGER,
  reviews INTEGER,
  seller_count INTEGER,
  landed_cost NUMERIC(10,2),
  est_net_margin NUMERIC(8,4),
  brand_share NUMERIC(8,4),
  price_trend TEXT,
  rating NUMERIC(3,1),
  state rw_product_state NOT NULL DEFAULT 'discovered',
  rule_reject_reason TEXT,
  features JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_keepa_pull TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS enrich_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  asin TEXT NOT NULL UNIQUE,
  marketplace TEXT NOT NULL DEFAULT 'US',
  source_query TEXT,
  picked BOOLEAN NOT NULL DEFAULT FALSE,
  retry_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  picked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS rule_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  asin TEXT NOT NULL REFERENCES products_rw(asin) ON DELETE CASCADE,
  decision TEXT NOT NULL CHECK (decision IN ('rule_passed', 'rule_rejected')),
  reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
  checks JSONB NOT NULL DEFAULT '{}'::jsonb,
  evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_products_rw_state ON products_rw(state);
CREATE INDEX IF NOT EXISTS idx_products_rw_category ON products_rw(category);
CREATE INDEX IF NOT EXISTS idx_enrich_queue_picked ON enrich_queue(picked, enqueued_at);
CREATE INDEX IF NOT EXISTS idx_rule_results_asin ON rule_results(asin);


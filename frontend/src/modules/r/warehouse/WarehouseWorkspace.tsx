"use client";

import { AlertCircle, CheckCircle2, Database, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  getRwProductsWithFilters,
  getRwRules,
  getRwStatus,
} from "@/modules/r/warehouse/api";
import type {
  RwProduct,
  RwProductsResponse,
  RwRulesResponse,
  RwStatus,
} from "@/modules/r/warehouse/types";

import styles from "./WarehouseWorkspace.module.css";

type WarehouseView = "dashboard" | "products" | "rules";

type WarehouseState = {
  products: RwProductsResponse | null;
  rules: RwRulesResponse | null;
  status: RwStatus | null;
};

type ProductFilters = {
  q: string;
  category_id: string;
  sort_by: "updated_at" | "skill_score";
  sort_order: "asc" | "desc";
};

const tabs: Array<{ href: string; label: string; view: WarehouseView }> = [
  { href: "/r-w/dashboard", label: "Dashboard", view: "dashboard" },
  { href: "/r-w/products", label: "Products", view: "products" },
  { href: "/r-w/rules", label: "Rules", view: "rules" },
];

function currency(value: number) {
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: 2,
    style: "currency",
  }).format(value);
}

function percent(value: number) {
  return `${Math.round(value * 1000) / 10}%`;
}

function productMetrics(products: readonly RwProduct[]) {
  const passed = products.filter((product) =>
    ["rule_passed", "ai1_passed"].includes(product.state),
  ).length;
  const productsWithMargin = products.filter(
    (product): product is RwProduct & { margin: number } =>
      typeof product.margin === "number",
  );
  const averageMargin =
    productsWithMargin.length === 0
      ? 0
      : productsWithMargin.reduce((total, product) => total + product.margin, 0) /
        productsWithMargin.length;
  return {
    averageMargin,
    passed,
    total: products.length,
  };
}

function ViewTabs({ activeView }: { activeView: WarehouseView }) {
  return (
    <div className={styles.tabs}>
      {tabs.map((tab) => (
        <Link
          className={`${styles.tab} ${
            activeView === tab.view ? styles.tabActive : ""
          }`}
          href={tab.href}
          key={tab.view}
        >
          <Database aria-hidden="true" size={16} />
          <span>{tab.label}</span>
        </Link>
      ))}
    </div>
  );
}

function ProductsTable({ products }: { products: readonly RwProduct[] }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Product</th>
            <th>Price</th>
            <th>BSR</th>
            <th>Reviews</th>
            <th>Sellers</th>
            <th>Margin</th>
            <th>Skill</th>
            <th>State</th>
          </tr>
        </thead>
        <tbody>
          {products.map((product) => (
            <tr key={product.asin}>
              <td>
                <div className={styles.productCell}>
                  <strong>{product.title}</strong>
                  <span>{product.asin} · {product.category}</span>
                </div>
              </td>
              <td>{product.price === null ? "N/A" : currency(product.price)}</td>
              <td>{product.bsr.toLocaleString("en-US")}</td>
              <td>{product.reviews.toLocaleString("en-US")}</td>
              <td>{product.seller_count}</td>
              <td>{product.margin === null ? "N/A" : percent(product.margin)}</td>
              <td>{product.skill_score ?? "N/A"}</td>
              <td>
                <span className={styles.badge}>{product.rule_result}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RulesList({ rules }: { rules: RwRulesResponse }) {
  return (
    <div className={styles.ruleList}>
      {rules.items.map((rule) => (
        <div className={styles.ruleRow} key={rule.id}>
          <strong>{rule.label}</strong>
          <span className={styles.muted}>{rule.threshold}</span>
          <span className={styles.badge}>{rule.result}</span>
        </div>
      ))}
    </div>
  );
}

export function WarehouseWorkspace({ view }: { view: WarehouseView }) {
  const [state, setState] = useState<WarehouseState>({
    products: null,
    rules: null,
    status: null,
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [batchPopupOpen, setBatchPopupOpen] = useState(true);
  const [filters, setFilters] = useState<ProductFilters>({
    q: "",
    category_id: "",
    sort_by: "updated_at",
    sort_order: "desc",
  });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [status, products, rules] = await Promise.all([
          getRwStatus(),
          getRwProductsWithFilters({
            q: filters.q || undefined,
            category_id: filters.category_id || undefined,
            sort_by: filters.sort_by,
            sort_order: filters.sort_order,
          }),
          getRwRules(),
        ]);
        if (!cancelled) {
          setState({ products, rules, status });
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error && loadError.message.includes("无权")
              ? "暂无权限，请联系管理员开通权限"
              : "R-W data is temporarily unavailable.",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [filters]);

  const products = state.products?.items ?? [];
  const metrics = useMemo(() => productMetrics(products), [products]);

  if (loading) {
    return (
      <div className={styles.message} role="status">
        <RefreshCw aria-hidden="true" className="spin" size={18} />
        <span>Loading R-W data.</span>
      </div>
    );
  }

  if (error || !state.status || !state.products || !state.rules) {
    return (
      <div className={styles.message} role="alert">
        <AlertCircle aria-hidden="true" size={18} />
        <span>{error ?? "R-W data did not load."}</span>
      </div>
    );
  }

  return (
    <div className={styles.workspace}>
      <div className={styles.toolbar}>
        <ViewTabs activeView={view} />
        <div className={styles.headerStatusGroup}>
          <span className={styles.skillHint}>{state.status.skill.label}</span>
          <span className={styles.statusPill}>
            <CheckCircle2 aria-hidden="true" size={16} />
            {state.status.mode}
          </span>
        </div>
      </div>

      {batchPopupOpen ? (
        <div className={styles.popupBackdrop} role="dialog" aria-modal="true">
          <div className={styles.popup}>
            <strong>DeepSeek batch status</strong>
            <dl className={styles.popupStats}>
              <div>
                <dt>Run time range</dt>
                <dd>{state.status.deepseek_batch.run_time_range}</dd>
              </div>
              <div>
                <dt>Total processed</dt>
                <dd>{state.status.deepseek_batch.total_processed}</dd>
              </div>
              <div>
                <dt>Pass count</dt>
                <dd>{state.status.deepseek_batch.pass_count}</dd>
              </div>
              <div>
                <dt>Fail count</dt>
                <dd>{state.status.deepseek_batch.fail_count}</dd>
              </div>
              <div>
                <dt>Deleted count</dt>
                <dd>{state.status.deepseek_batch.deleted_count}</dd>
              </div>
            </dl>
            <button
              className={styles.popupButton}
              onClick={() => setBatchPopupOpen(false)}
              type="button"
            >
              关闭
            </button>
          </div>
        </div>
      ) : null}

      <section className={styles.metrics} aria-label="R-W status metrics">
        <div className={styles.metric}>
          <span>Products</span>
          <strong>{metrics.total}</strong>
        </div>
        <div className={styles.metric}>
          <span>Rule Passed</span>
          <strong>{metrics.passed}</strong>
        </div>
        <div className={styles.metric}>
          <span>Average Margin</span>
          <strong>{percent(metrics.averageMargin)}</strong>
        </div>
        <div className={styles.metric}>
          <span>Keepa Mode</span>
          <strong>{state.status.keepa_mode.continuous_ingestion ? "24/7" : "paused"}</strong>
        </div>
        <div className={styles.metric}>
          <span>DeepSeek Passed</span>
          <strong>{state.status.deepseek_batch.pass_count}</strong>
        </div>
      </section>

      {view === "dashboard" ? (
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h2>Warehouse Pipeline</h2>
              <p>{state.status.organization}</p>
            </div>
            <span className={`${styles.badge} ${styles.warningBadge}`}>
              {state.status.waiting_for_keys ? "waiting for keys" : "production"}
            </span>
          </div>
          <ProductsTable products={products} />
        </section>
      ) : null}

      {view === "products" ? (
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h2>Product Warehouse</h2>
              <p>ASIN records from the Keepa enrichment flow.</p>
            </div>
          </div>
          <div className={styles.filters}>
            <input
              onChange={(event) =>
                setFilters((current) => ({ ...current, q: event.target.value }))
              }
              placeholder="Search title / ASIN / category"
              value={filters.q}
            />
            <select
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  category_id: event.target.value,
                }))
              }
              value={filters.category_id}
            >
              <option value="">All categories</option>
              {state.status.category_tree.selected_categories.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
            <select
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  sort_by: event.target.value as ProductFilters["sort_by"],
                }))
              }
              value={filters.sort_by}
            >
              <option value="updated_at">Updated</option>
              <option value="skill_score">Skill score</option>
            </select>
            <button
              className={styles.filterButton}
              onClick={() =>
                setFilters((current) => ({
                  ...current,
                  sort_order: current.sort_order === "asc" ? "desc" : "asc",
                }))
              }
              type="button"
            >
              {filters.sort_order === "asc" ? "ASC" : "DESC"}
            </button>
          </div>
          <ProductsTable products={products} />
        </section>
      ) : null}

      {view === "rules" ? (
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h2>Rule Engine</h2>
              <p>Mandatory filters currently enforced for R-W production mode.</p>
            </div>
            <span className={styles.badge}>enabled</span>
          </div>
          <RulesList rules={state.rules} />
        </section>
      ) : null}
    </div>
  );
}

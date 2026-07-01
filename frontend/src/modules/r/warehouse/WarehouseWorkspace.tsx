"use client";

import { AlertCircle, CheckCircle2, Database, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  getRwProducts,
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
  const passed = products.filter((product) => product.state === "rule_passed").length;
  const averageMargin =
    products.length === 0
      ? 0
      : products.reduce((total, product) => total + product.margin, 0) /
        products.length;
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
              <td>{currency(product.price)}</td>
              <td>{product.bsr.toLocaleString("en-US")}</td>
              <td>{product.reviews.toLocaleString("en-US")}</td>
              <td>{product.seller_count}</td>
              <td>{percent(product.margin)}</td>
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

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [status, products, rules] = await Promise.all([
          getRwStatus(),
          getRwProducts(),
          getRwRules(),
        ]);
        if (!cancelled) {
          setState({ products, rules, status });
        }
      } catch {
        if (!cancelled) {
          setError("R-W mock data is temporarily unavailable.");
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
  }, []);

  const products = state.products?.items ?? [];
  const metrics = useMemo(() => productMetrics(products), [products]);

  if (loading) {
    return (
      <div className={styles.message} role="status">
        <RefreshCw aria-hidden="true" className="spin" size={18} />
        <span>Loading R-W mock data.</span>
      </div>
    );
  }

  if (error || !state.status || !state.products || !state.rules) {
    return (
      <div className={styles.message} role="alert">
        <AlertCircle aria-hidden="true" size={18} />
        <span>{error ?? "R-W mock data did not load."}</span>
      </div>
    );
  }

  return (
    <div className={styles.workspace}>
      <div className={styles.toolbar}>
        <ViewTabs activeView={view} />
        <span className={styles.statusPill}>
          <CheckCircle2 aria-hidden="true" size={16} />
          {state.status.mode}
        </span>
      </div>

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
          <strong>Mock</strong>
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
              waiting for keys
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
              <p>ASIN records from the mock Keepa enrichment flow.</p>
            </div>
          </div>
          <ProductsTable products={products} />
        </section>
      ) : null}

      {view === "rules" ? (
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h2>Rule Engine</h2>
              <p>Mandatory filters currently enforced for R-W mock mode.</p>
            </div>
            <span className={styles.badge}>enabled</span>
          </div>
          <RulesList rules={state.rules} />
        </section>
      ) : null}
    </div>
  );
}


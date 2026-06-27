"use client";

import { Globe2, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { getProducts } from "@/modules/k/product-knowledge/api";
import type { ProductKnowledgeListItem } from "@/modules/k/product-knowledge/types";
import { isOwnerRole, isSuperAdminRole } from "@/lib/roles";
import { runSERPSearch } from "./api";
import styles from "./SERPTriggerPanel.module.css";
import type { SERPResult, SERPTriggerState } from "./types";

const statusFlow: SERPTriggerState[] = [
  "idle",
  "loading",
  "completed",
  "failed",
];

const marketOptions = ["amazon", "shopify", "tiktok_shop", "general"];

export function SERPTriggerPanel() {
  const { isOwner, user } = useAuth();
  const { byModuleKey } = useFrontendCapabilityState();
  const [products, setProducts] = useState<ProductKnowledgeListItem[]>([]);
  const [productLoadError, setProductLoadError] = useState("");
  const [productId, setProductId] = useState("");
  const [market, setMarket] = useState(marketOptions[0]);
  const [query, setQuery] = useState("kids stainless steel water bottle");
  const [state, setState] = useState<SERPTriggerState>("idle");
  const [serpResult, setSerpResult] = useState<SERPResult | null>(null);
  const [error, setError] = useState("");
  const kProductCapability = byModuleKey.get("k.product_knowledge") ?? null;
  const canRunSerp =
    isOwner ||
    isOwnerRole(user?.role) ||
    isSuperAdminRole(user?.role) ||
    kProductCapability?.can_enter === true;
  const productOptions = useMemo(
    () =>
      products.map((product) => ({
        label:
          product.product_name_en ||
          product.sku ||
          product.product_key ||
          product.id,
        market: product.target_market || marketOptions[0],
        query:
          product.product_name_en ||
          product.product_key ||
          product.sku ||
          query,
        value: product.id,
      })),
    [products, query],
  );
  const selectedProduct = productOptions.find(
    (product) => product.value === productId,
  );
  const effectiveMarketOptions = selectedProduct?.market
    ? Array.from(new Set([selectedProduct.market, ...marketOptions]))
    : marketOptions;

  useEffect(() => {
    let active = true;
    getProducts()
      .then((response) => {
        if (!active) {
          return;
        }
        setProducts(response.items);
        setProductLoadError("");
      })
      .catch((caught) => {
        if (!active) {
          return;
        }
        setProductLoadError(
          caught instanceof Error ? caught.message : "产品列表无法加载。",
        );
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (productId || productOptions.length === 0) {
      return;
    }
    const firstProduct = productOptions[0];
    setProductId(firstProduct.value);
    setMarket(firstProduct.market);
    setQuery((current) => current.trim() || firstProduct.query);
  }, [productId, productOptions]);

  async function handleRunSearch() {
    const normalizedProductId = productId.trim();
    const normalizedQuery = query.trim();

    if (!normalizedProductId || !normalizedQuery) {
      setState("failed");
      setError("运行 SERP 搜索前需要选择产品并填写查询词。");
      return;
    }

    setState("loading");
    setSerpResult(null);
    setError("");

    try {
      const result = await runSERPSearch({
        product_id: normalizedProductId,
        market,
        query: normalizedQuery,
      });
      setSerpResult(result);
      setState("completed");
    } catch (caught) {
      setState("failed");
      setError(
        caught instanceof Error ? caught.message : "SERP 搜索无法运行。",
      );
    }
  }

  return (
    <section className={styles.panel} aria-labelledby="serp-trigger">
      <div className={styles.heading}>
        <div>
          <span className="section-index">SERP</span>
          <h3 id="serp-trigger">SERP 搜索触发</h3>
          <p>
            选择产品和市场后，运行面向 SERP 结果链路的市场搜索请求。
          </p>
        </div>
      </div>

      <div className={styles.form}>
        <label className={styles.field}>
          <span>产品</span>
          <select
            disabled={productOptions.length === 0}
            onChange={(event) => {
              const nextProductId = event.target.value;
              const nextProduct = productOptions.find(
                (product) => product.value === nextProductId,
              );
              setProductId(nextProductId);
              if (nextProduct) {
                setMarket(nextProduct.market);
                setQuery((current) => current.trim() || nextProduct.query);
              }
            }}
            value={productId}
          >
            {productOptions.length === 0 ? (
              <option value="">暂无产品</option>
            ) : (
              productOptions.map((product) => (
                <option key={product.value} value={product.value}>
                  {product.label}
                </option>
              ))
            )}
          </select>
        </label>

        <label className={styles.field}>
          <span>市场</span>
          <select
            onChange={(event) => setMarket(event.target.value)}
            value={market}
          >
            {effectiveMarketOptions.map((marketOption) => (
              <option key={marketOption} value={marketOption}>
                {marketLabel(marketOption)}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>查询词</span>
          <input
            onChange={(event) => setQuery(event.target.value)}
            placeholder="市场查询词"
            type="text"
            value={query}
          />
        </label>

        <button
          className="primary-button"
          disabled={
            state === "loading" ||
            !canRunSerp ||
            productOptions.length === 0
          }
          onClick={() => void handleRunSearch()}
          type="button"
        >
          {state === "loading" ? (
            <Loader2 aria-hidden="true" className="spin" size={16} />
          ) : (
            <Globe2 aria-hidden="true" size={16} />
          )}
          运行 SERP 搜索
        </button>
      </div>

      <ol className={styles.statusRail} aria-label="SERP 触发状态流">
        {statusFlow.map((status) => (
          <li className={getStatusClass(status, state)} key={status}>
            {serpStatusLabel(status)}
          </li>
        ))}
      </ol>

      {serpResult ? <SERPResultSummary serpResult={serpResult} /> : null}

      <p className={`${styles.message} ${error ? styles.error : ""}`}>
        {error ||
          productLoadError ||
          (!canRunSerp
            ? "当前账号未分配 SERP 搜索权限。"
            : statusMessageFor(state))}
      </p>
    </section>
  );
}

function SERPResultSummary({ serpResult }: { serpResult: SERPResult }) {
  return (
    <div className={styles.result}>
      <dl className={styles.resultGrid}>
        <div>
          <dt>结果ID</dt>
          <dd>{serpResult.id}</dd>
        </div>
        <div>
          <dt>市场</dt>
          <dd>{marketLabel(serpResult.market)}</dd>
        </div>
        <div>
          <dt>更新时间</dt>
          <dd>{formatTimestamp(serpResult.updated_at)}</dd>
        </div>
      </dl>

      <TagGroup label="关键词" values={serpResult.keywords} />
      <TagGroup label="竞品链接" values={serpResult.competitor_links} />
    </div>
  );
}

function TagGroup({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) {
    return null;
  }

  return (
    <div className={styles.tagGroup}>
      <span>{label}</span>
      <div>
        {values.map((value) => (
          <strong key={value}>{value}</strong>
        ))}
      </div>
    </div>
  );
}

function getStatusClass(
  status: SERPTriggerState,
  currentStatus: SERPTriggerState,
) {
  if (status === currentStatus) {
    return `${styles.statusStep} ${
      status === "failed" ? styles.statusStepFailed : styles.statusStepActive
    }`;
  }

  const statusIndex = statusFlow.indexOf(status);
  const currentIndex = statusFlow.indexOf(currentStatus);

  if (currentStatus !== "failed" && statusIndex < currentIndex) {
    return `${styles.statusStep} ${styles.statusStepComplete}`;
  }

  return styles.statusStep;
}

function statusMessageFor(status: SERPTriggerState) {
  if (status === "loading") {
    return "SERP 搜索请求运行中。";
  }

  if (status === "completed") {
    return "已收到 SERP 结果。";
  }

  if (status === "failed") {
    return "SERP 搜索失败。";
  }

  return "空闲。尚未运行 SERP 搜索。";
}

function serpStatusLabel(status: string) {
  const labels: Record<string, string> = {
    completed: "已完成",
    failed: "失败",
    idle: "空闲",
    loading: "运行中",
  };

  return labels[status] ?? "待处理";
}

function marketLabel(market: string) {
  const labels: Record<string, string> = {
    amazon: "Amazon",
    general: "通用",
    shopify: "Shopify",
    tiktok_shop: "TikTok Shop",
  };

  return labels[market] ?? market;
}

function formatTimestamp(value: string) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

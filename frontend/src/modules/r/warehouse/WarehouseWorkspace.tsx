"use client";

import { Activity, AlertCircle, CheckCircle2, Database, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import {
  getRwCategoryTree,
  getRwPipeline,
  getRwProductsWithFilters,
  getRwRules,
  getRwSettings,
  getRwStatus,
  selectRwCategory,
  updateRwSettings,
} from "@/modules/r/warehouse/api";
import type {
  RwCategoryNode,
  RwCategoryTreeResponse,
  RwPipelineResponse,
  RwProduct,
  RwProductsResponse,
  RwRulesResponse,
  RwRuntimeSettings,
  RwSettingsResponse,
  RwStatus,
} from "@/modules/r/warehouse/types";

import styles from "./WarehouseWorkspace.module.css";

type WarehouseView = "dashboard" | "products" | "rules" | "pipeline" | "batch";

type WarehouseState = {
  products: RwProductsResponse | null;
  rules: RwRulesResponse | null;
  status: RwStatus | null;
  pipeline: RwPipelineResponse | null;
  settings: RwSettingsResponse | null;
  categoryTree: RwCategoryTreeResponse | null;
};

type CompleteWarehouseState = {
  products: RwProductsResponse;
  rules: RwRulesResponse;
  status: RwStatus;
  pipeline: RwPipelineResponse;
  settings: RwSettingsResponse | null;
  categoryTree: RwCategoryTreeResponse | null;
};

type ProductFilters = {
  q: string;
  category_id: string;
  sort_by: "updated_at" | "skill_score";
  sort_order: "asc" | "desc";
};

type RwEndpointKey = keyof WarehouseState;

const tabs: Array<{ href: string; label: string; view: WarehouseView }> = [
  { href: "/r-w/dashboard", label: "总览", view: "dashboard" },
  { href: "/r-w/products", label: "产品库", view: "products" },
  { href: "/r-w/pipeline", label: "抓取流水线", view: "pipeline" },
  { href: "/r-w/batch-status", label: "批次状态", view: "batch" },
  { href: "/r-w/rules", label: "规则", view: "rules" },
];

const DEEPSEEK_DAILY_REPORT_KEY_PREFIX = "rw-deepseek-daily-report-date";

function currency(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    currency: "USD",
    maximumFractionDigits: 2,
    style: "currency",
  }).format(value);
}

function percent(value: number) {
  return `${Math.round(value * 1000) / 10}%`;
}

function stateLabel(value: string) {
  const labels: Record<string, string> = {
    ai1_passed: "初筛通过",
    ai1_rejected: "初筛剔除",
    discovered: "已发现",
    enriched: "已富化",
    rejected: "规则剔除",
    rule_prefilter: "规则预筛",
    rule_passed: "待初筛",
    discovery: "类目发现",
    deadline: "到时停止",
    backoff: "限流等待",
    blocked: "阻塞",
  };
  return labels[value] ?? value;
}

function decisionLabel(value: string) {
  const labels: Record<string, string> = {
    pass: "通过",
    pending_review: "待复核",
    reject: "剔除",
  };
  return labels[value] ?? value;
}

function modeLabel(value: string) {
  const labels: Record<string, string> = {
    production: "生产运行",
    production_blocked: "等待密钥",
  };
  return labels[value] ?? value;
}

function eventLabel(value: string) {
  const labels: Record<string, string> = {
    deepseek_prefilter: "DeepSeek 初筛",
    keepa_cycle: "Keepa 循环",
    keepa_discovery: "Keepa 类目发现",
    keepa_fetch: "Keepa 抓取",
  };
  return labels[value] ?? value;
}

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    active: "运行中",
    backoff: "限流等待",
    blocked: "阻塞",
    failed: "失败",
    idle: "空闲",
    processed: "已处理",
    queued: "已入队",
    stored: "已入库",
    stopped: "已停止",
  };
  return labels[value] ?? value;
}

function priceTrendLabel(value: string | null) {
  if (!value) {
    return "未知";
  }
  const labels: Record<string, string> = {
    declining: "下行",
    price_war: "价格战",
    rising: "上行",
    stable: "平稳",
  };
  return labels[value] ?? value;
}

function productMetrics(products: readonly RwProduct[]) {
  const passed = products.filter((product) => product.pipeline_decision === "pass").length;
  const rejected = products.filter((product) => product.pipeline_decision === "reject").length;
  const pending = products.filter(
    (product) => product.pipeline_decision === "pending_review",
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
    pending,
    rejected,
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
  if (products.length === 0) {
    return <div className={styles.empty}>后端产品库暂无记录。</div>;
  }

  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>产品</th>
            <th>价格</th>
            <th>BSR</th>
            <th>评论</th>
            <th>卖家</th>
            <th>利润率</th>
            <th>分数</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {products.map((product) => (
            <tr key={product.asin}>
              <td>
                <div className={styles.productCell}>
                  <div className={styles.productPreview}>
                    {product.image_url ? (
                      <img alt={product.title} src={product.image_url} />
                    ) : (
                      <span>无图</span>
                    )}
                  </div>
                  <div>
                    <strong>{product.title}</strong>
                    <span>
                      {product.asin} · {product.brand ?? "未知品牌"} · {product.category}
                    </span>
                    <span>
                      评分 {product.rating ?? "无"} · 趋势 {priceTrendLabel(product.price_trend)}
                    </span>
                  </div>
                </div>
              </td>
              <td>{product.price === null ? "无" : currency(product.price)}</td>
              <td>{product.bsr.toLocaleString("zh-CN")}</td>
              <td>{product.reviews.toLocaleString("zh-CN")}</td>
              <td>{product.seller_count}</td>
              <td>{product.margin === null ? "无" : percent(product.margin)}</td>
              <td>{product.skill_score ?? "待跑"}</td>
              <td>
                <span className={styles.badge}>
                  {decisionLabel(product.pipeline_decision)}
                </span>
                <span className={styles.stateText}>{stateLabel(product.state)}</span>
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

function CategorySelectionList({
  depth = 0,
  node,
  onSelectCategory,
  savingCategory,
}: {
  depth?: number;
  node: RwCategoryNode;
  onSelectCategory: (categoryId: string, selected: boolean) => Promise<void>;
  savingCategory: string | null;
}) {
  return (
    <div className={styles.categoryNode}>
      <label style={{ paddingLeft: depth * 16 }}>
        <input
          checked={node.selected}
          disabled={savingCategory !== null}
          onChange={(event) => {
            void onSelectCategory(node.id, event.target.checked);
          }}
          type="checkbox"
        />
        <span>{node.name}</span>
      </label>
      {node.children.map((child) => (
        <CategorySelectionList
          depth={depth + 1}
          key={child.id}
          node={child}
          onSelectCategory={onSelectCategory}
          savingCategory={savingCategory}
        />
      ))}
    </div>
  );
}

function PipelineView({ pipeline }: { pipeline: RwPipelineResponse }) {
  const workers = pipeline.runtime.workers;
  const events = pipeline.runtime.events;
  return (
    <section className={styles.panel}>
      <div className={styles.panelHeader}>
        <div>
          <h2>抓取流水线</h2>
          <p>Keepa → 规则预筛 → DeepSeek 初筛 → 入库 → 页面刷新</p>
        </div>
        <span className={styles.badge}>5 秒刷新</span>
      </div>
      <div className={styles.workerGrid}>
        {workers.length === 0 ? (
          <div className={styles.empty}>尚未收到 worker 心跳。</div>
        ) : (
          workers.map((worker) => (
            <div className={styles.workerRow} key={worker.worker_name}>
              <strong>{worker.worker_name}</strong>
              <span>{statusLabel(worker.status)}</span>
              <span>Keepa {worker.loop_interval_seconds} 秒/轮</span>
              <span>DeepSeek {worker.deepseek_interval_seconds} 秒/轮</span>
              <span>队列 {worker.queue_pending}</span>
              <span>{worker.last_heartbeat_at ?? "暂无心跳"}</span>
            </div>
          ))
        )}
      </div>
      <div className={styles.eventList}>
        {events.length === 0 ? (
          <div className={styles.empty}>暂无流水线事件。</div>
        ) : (
          events.map((event, index) => (
            <div className={styles.eventRow} key={`${event.created_at}-${index}`}>
              <div>
                <strong>{eventLabel(event.event_type)}</strong>
                <span>{event.asin ?? event.category_id ?? "系统事件"}</span>
              </div>
              <span>{stateLabel(event.stage)}</span>
              <span>
                {event.score_action ? decisionLabel(event.score_action) : statusLabel(event.status)}
              </span>
              <span>{event.created_at}</span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function BatchStatusView({
  categoryTree,
  onSelectCategory,
  onSaveSettings,
  savingCategory,
  savingSettings,
  settings,
  status,
}: {
  categoryTree: RwCategoryTreeResponse | null;
  onSelectCategory: (categoryId: string, selected: boolean) => Promise<void>;
  onSaveSettings: (settings: Partial<RwRuntimeSettings>) => Promise<void>;
  savingCategory: string | null;
  savingSettings: boolean;
  settings: RwSettingsResponse | null;
  status: RwStatus;
}) {
  const queue = status.runtime.queue;
  const runtimeSettings = settings?.settings;
  const [draft, setDraft] = useState<RwRuntimeSettings>({
    deepseek_batch_size: runtimeSettings?.deepseek_batch_size ?? 100,
    deepseek_interval_seconds:
      runtimeSettings?.deepseek_interval_seconds ??
      status.runtime.workers[0]?.deepseek_interval_seconds ??
      300,
    deepseek_max_runtime_seconds:
      runtimeSettings?.deepseek_max_runtime_seconds ?? 240,
    discovery_categories_per_cycle:
      runtimeSettings?.discovery_categories_per_cycle ?? 1,
    keepa_429_backoff_seconds:
      runtimeSettings?.keepa_429_backoff_seconds ?? 300,
    keepa_batch_size: runtimeSettings?.keepa_batch_size ?? 20,
    selected_categories: runtimeSettings?.selected_categories ?? null,
  });

  useEffect(() => {
    if (!runtimeSettings) {
      return;
    }
    setDraft(runtimeSettings);
  }, [runtimeSettings]);

  return (
    <section className={styles.panel}>
      <div className={styles.panelHeader}>
        <div>
          <h2>批次状态</h2>
          <p>DeepSeek 自动初筛和 Keepa 队列处理统计。</p>
        </div>
        <span className={styles.badge}>自动批处理</span>
      </div>
      <dl className={styles.statusGrid}>
        <div>
          <dt>DeepSeek 运行范围</dt>
          <dd>{status.deepseek_batch.run_time_range}</dd>
        </div>
        <div>
          <dt>DeepSeek 已处理</dt>
          <dd>{status.deepseek_batch.total_processed}</dd>
        </div>
        <div>
          <dt>DeepSeek 通过</dt>
          <dd>{status.deepseek_batch.pass_count}</dd>
        </div>
        <div>
          <dt>DeepSeek 剔除</dt>
          <dd>{status.deepseek_batch.fail_count}</dd>
        </div>
        <div>
          <dt>队列待处理</dt>
          <dd>{queue.pending ?? 0}</dd>
        </div>
        <div>
          <dt>队列处理中</dt>
          <dd>{queue.picked ?? 0}</dd>
        </div>
      </dl>
      <form
        className={styles.settingsGrid}
        onSubmit={(event) => {
          event.preventDefault();
          const { selected_categories: _selectedCategories, ...runtimeDraft } = draft;
          void onSaveSettings(runtimeDraft);
        }}
      >
        <label>
          <span>DeepSeek 间隔秒数</span>
          <input
            min={60}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                deepseek_interval_seconds: Number(event.target.value),
              }))
            }
            step={60}
            type="number"
            value={draft.deepseek_interval_seconds}
          />
        </label>
        <label>
          <span>DeepSeek 每批数量</span>
          <input
            min={1}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                deepseek_batch_size: Number(event.target.value),
              }))
            }
            type="number"
            value={draft.deepseek_batch_size}
          />
        </label>
        <label>
          <span>单次最长运行秒数</span>
          <input
            min={10}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                deepseek_max_runtime_seconds: Number(event.target.value),
              }))
            }
            step={10}
            type="number"
            value={draft.deepseek_max_runtime_seconds}
          />
        </label>
        <label>
          <span>Keepa 每轮产品数</span>
          <input
            max={20}
            min={1}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                keepa_batch_size: Number(event.target.value),
              }))
            }
            type="number"
            value={draft.keepa_batch_size}
          />
        </label>
        <label>
          <span>429 暂停秒数</span>
          <input
            min={60}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                keepa_429_backoff_seconds: Number(event.target.value),
              }))
            }
            step={60}
            type="number"
            value={draft.keepa_429_backoff_seconds}
          />
        </label>
        <button className={styles.filterButton} disabled={savingSettings} type="submit">
          {savingSettings ? "保存中" : "保存设置"}
        </button>
      </form>
      <div className={styles.categorySelector}>
        <div className={styles.selectorHeader}>
          <strong>Keepa 抓取类目</strong>
          <span>{status.category_tree.selected_count} 个已选</span>
        </div>
        {categoryTree ? (
          <div className={styles.categoryTree}>
            <CategorySelectionList
              node={categoryTree.root}
              onSelectCategory={onSelectCategory}
              savingCategory={savingCategory}
            />
          </div>
        ) : (
          <div className={styles.empty}>类目树暂不可用。</div>
        )}
      </div>
    </section>
  );
}

export function WarehouseWorkspace({ view }: { view: WarehouseView }) {
  const { user } = useAuth();
  const [state, setState] = useState<WarehouseState>({
    categoryTree: null,
    pipeline: null,
    products: null,
    rules: null,
    settings: null,
    status: null,
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [savingCategory, setSavingCategory] = useState<string | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [showDeepseekReport, setShowDeepseekReport] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [filters, setFilters] = useState<ProductFilters>({
    category_id: "",
    q: "",
    sort_by: "updated_at",
    sort_order: "desc",
  });
  const stateRef = useRef(state);
  const deepseekDailyReportKey = `${DEEPSEEK_DAILY_REPORT_KEY_PREFIX}:${
    user?.id ?? "anonymous"
  }`;

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    if (!state.status || typeof window === "undefined") {
      return;
    }
    const today = new Date().toISOString().slice(0, 10);
    if (window.localStorage.getItem(deepseekDailyReportKey) !== today) {
      setShowDeepseekReport(true);
    }
  }, [deepseekDailyReportKey, state.status]);

  useEffect(() => {
    let cancelled = false;
    let firstLoad = true;

    async function load() {
      if (firstLoad) {
        setLoading(true);
      } else {
        setRefreshing(true);
      }
      try {
        const requests: Array<[
          RwEndpointKey,
          Promise<WarehouseState[RwEndpointKey]>,
        ]> = [
          ["status", getRwStatus()],
          [
            "products",
            getRwProductsWithFilters({
              category_id: filters.category_id || undefined,
              q: filters.q || undefined,
              sort_by: filters.sort_by,
              sort_order: filters.sort_order,
            }),
          ],
          ["rules", getRwRules()],
          ["pipeline", getRwPipeline()],
          ["settings", getRwSettings()],
          ["categoryTree", getRwCategoryTree()],
        ];
        const results = await Promise.allSettled(
          requests.map(([, request]) => request),
        );
        if (!cancelled) {
          const failed = results.filter((result) => result.status === "rejected");
          let nextState = stateRef.current;
          setState((current) => {
            const updated = { ...current };
            results.forEach((result, index) => {
              if (result.status === "fulfilled") {
                applyWarehouseStateValue(
                  updated,
                  requests[index][0],
                  result.value,
                );
              }
            });
            nextState = updated;
            stateRef.current = updated;
            return updated;
          });
          setLastRefresh(new Date().toLocaleTimeString("zh-CN"));
          if (failed.length === 0) {
            setError(null);
          } else if (hasCompleteWarehouseState(nextState)) {
            setError("部分后端数据刷新失败，已保留上一轮可读数据。");
          } else {
            const loadError = failed[0].reason;
            setError(
              loadError instanceof Error && loadError.message.includes("无权")
                ? "暂无权限，请联系管理员开通权限。"
                : "R-W 后端数据暂时不可用。",
            );
          }
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error && loadError.message.includes("无权")
              ? "暂无权限，请联系管理员开通权限。"
              : "R-W 后端数据暂时不可用。",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setRefreshing(false);
          firstLoad = false;
        }
      }
    }

    void load();
    const timer = window.setInterval(() => {
      void load();
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [filters]);

  const products = state.products?.items ?? [];
  const metrics = useMemo(() => productMetrics(products), [products]);
  const readyState = hasCompleteWarehouseState(state) ? state : null;
  const categoryLabels = useMemo(
    () => collectCategoryLabels(readyState?.categoryTree?.root ?? null),
    [readyState?.categoryTree?.root],
  );

  async function saveSettings(settings: Partial<RwRuntimeSettings>) {
    setSavingSettings(true);
    try {
      const response = await updateRwSettings(settings);
      setState((current) => {
        const updated = { ...current, settings: response };
        stateRef.current = updated;
        return updated;
      });
      setError(null);
    } catch {
      setError("DeepSeek 定时设置保存失败，现有页面数据已保留。");
    } finally {
      setSavingSettings(false);
    }
  }

  async function selectCategory(categoryId: string, selected: boolean) {
    setSavingCategory(categoryId);
    try {
      const response = await selectRwCategory(categoryId, selected);
      setState((current) => {
        const updated: WarehouseState = {
          ...current,
          categoryTree: response,
          settings: current.settings
            ? {
                ...current.settings,
                settings: {
                  ...current.settings.settings,
                  selected_categories: response.selected_categories,
                },
              }
            : current.settings,
          status: current.status
            ? {
                ...current.status,
                category_tree: {
                  ...current.status.category_tree,
                  selected_categories: response.selected_categories,
                  selected_count: response.selected_categories.length,
                },
              }
            : current.status,
        };
        stateRef.current = updated;
        return updated;
      });
      setError(null);
    } catch {
      setError("Keepa 抓取类目保存失败，现有页面数据已保留。");
    } finally {
      setSavingCategory(null);
    }
  }

  if (loading) {
    return (
      <div className={styles.message} role="status">
        <RefreshCw aria-hidden="true" className="spin" size={18} />
        <span>正在加载 R-W 实时数据。</span>
      </div>
    );
  }

  if (!readyState) {
    return (
      <div className={styles.message} role="alert">
        <AlertCircle aria-hidden="true" size={18} />
        <span>{error ?? "R-W 数据未加载。"}</span>
      </div>
    );
  }

  return (
    <div className={styles.workspace}>
      {showDeepseekReport ? (
        <div className={styles.popupBackdrop} role="presentation">
          <section
            aria-modal="true"
            className={styles.popup}
            role="dialog"
          >
            <strong>DeepSeek 今日初筛报告</strong>
            <dl className={styles.popupStats}>
              <div>
                <dt>运行间隔</dt>
                <dd>{readyState.status.deepseek_batch.run_time_range}</dd>
              </div>
              <div>
                <dt>已处理</dt>
                <dd>{readyState.status.deepseek_batch.total_processed}</dd>
              </div>
              <div>
                <dt>通过</dt>
                <dd>{readyState.status.deepseek_batch.pass_count}</dd>
              </div>
              <div>
                <dt>剔除</dt>
                <dd>{readyState.status.deepseek_batch.fail_count}</dd>
              </div>
            </dl>
            <button
              className={styles.popupButton}
              onClick={() => {
                window.localStorage.setItem(
                  deepseekDailyReportKey,
                  new Date().toISOString().slice(0, 10),
                );
                setShowDeepseekReport(false);
              }}
              type="button"
            >
              知道了
            </button>
          </section>
        </div>
      ) : null}
      {error ? (
        <div className={styles.warningMessage} role="status">
          <AlertCircle aria-hidden="true" size={16} />
          <span>{error}</span>
        </div>
      ) : null}
      <div className={styles.toolbar}>
        <ViewTabs activeView={view} />
        <div className={styles.headerStatusGroup}>
          <span className={styles.skillHint}>{readyState.status.skill.label}</span>
          <span className={styles.statusPill}>
            <CheckCircle2 aria-hidden="true" size={16} />
            {modeLabel(readyState.status.mode)}
          </span>
          <span className={styles.livePill}>
            <Activity aria-hidden="true" size={16} />
            {refreshing ? "刷新中" : `已刷新 ${lastRefresh ?? ""}`}
          </span>
        </div>
      </div>

      <section className={styles.metrics} aria-label="R-W 实时指标">
        <div className={styles.metric}>
          <span>产品数</span>
          <strong>{metrics.total}</strong>
        </div>
        <div className={styles.metric}>
          <span>通过</span>
          <strong>{metrics.passed}</strong>
        </div>
        <div className={styles.metric}>
          <span>待复核</span>
          <strong>{metrics.pending}</strong>
        </div>
        <div className={styles.metric}>
          <span>剔除</span>
          <strong>{metrics.rejected}</strong>
        </div>
        <div className={styles.metric}>
          <span>平均利润率</span>
          <strong>{percent(metrics.averageMargin)}</strong>
        </div>
      </section>

      {view === "dashboard" ? (
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h2>实时仓库总览</h2>
              <p>{readyState.status.organization}</p>
            </div>
            <span className={`${styles.badge} ${readyState.status.waiting_for_keys ? styles.warningBadge : ""}`}>
              {readyState.status.waiting_for_keys ? "等待 Keepa 密钥" : "自动运行"}
            </span>
          </div>
          <ProductsTable products={products} />
        </section>
      ) : null}

      {view === "products" ? (
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h2>产品数据仓库</h2>
              <p>来自 Keepa 抓取和自动评分流水线的 ASIN 记录。</p>
            </div>
          </div>
          <div className={styles.filters}>
            <input
              onChange={(event) =>
                setFilters((current) => ({ ...current, q: event.target.value }))
              }
              placeholder="搜索标题 / ASIN / 类目"
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
              <option value="">全部类目</option>
              {readyState.status.category_tree.selected_categories.map((category) => (
                <option key={category} value={category}>
                  {categoryLabels.get(category) ?? category}
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
              <option value="updated_at">更新时间</option>
              <option value="skill_score">初筛分数</option>
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
              {filters.sort_order === "asc" ? "升序" : "降序"}
            </button>
          </div>
          <ProductsTable products={products} />
        </section>
      ) : null}

      {view === "pipeline" ? <PipelineView pipeline={readyState.pipeline} /> : null}

      {view === "batch" ? (
        <BatchStatusView
          categoryTree={readyState.categoryTree}
          onSelectCategory={selectCategory}
          onSaveSettings={saveSettings}
          savingCategory={savingCategory}
          savingSettings={savingSettings}
          settings={readyState.settings}
          status={readyState.status}
        />
      ) : null}

      {view === "rules" ? (
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h2>规则引擎</h2>
              <p>R-W 生产流水线当前强制执行的硬性过滤规则。</p>
            </div>
            <span className={styles.badge}>已启用</span>
          </div>
          <RulesList rules={readyState.rules} />
        </section>
      ) : null}
    </div>
  );
}

function hasCompleteWarehouseState(value: WarehouseState): value is CompleteWarehouseState {
  return Boolean(value.status && value.products && value.rules && value.pipeline);
}

function applyWarehouseStateValue(
  target: WarehouseState,
  key: RwEndpointKey,
  value: WarehouseState[RwEndpointKey],
) {
  if (key === "status") {
    target.status = value as RwStatus;
  } else if (key === "products") {
    target.products = value as RwProductsResponse;
  } else if (key === "rules") {
    target.rules = value as RwRulesResponse;
  } else if (key === "pipeline") {
    target.pipeline = value as RwPipelineResponse;
  } else if (key === "categoryTree") {
    target.categoryTree = value as RwCategoryTreeResponse;
  } else {
    target.settings = value as RwSettingsResponse;
  }
}

function collectCategoryLabels(root: RwCategoryNode | null) {
  const labels = new Map<string, string>();
  function visit(node: RwCategoryNode) {
    labels.set(node.id, node.name);
    node.children.forEach(visit);
  }
  if (root) {
    visit(root);
  }
  return labels;
}

"use client";

import {
  AlertTriangle,
  BarChart3,
  Calculator,
  CheckCircle2,
  ClipboardCheck,
  Database,
  FileCheck2,
  KeyRound,
  Layers3,
  PackageSearch,
  RefreshCw,
  Save,
  Search,
  Truck,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import {
  calculateManualRaProfit,
  getRaFrameworkStatus,
  getRaProfitSnapshots,
  runRaProfitForExistingOffers,
  searchRaSuppliers,
} from "@/modules/r/analysis/api";
import type {
  RaFrameworkStatus,
  RaProfitSnapshot,
  RaStage,
  RaSupplierSearchResult,
} from "@/modules/r/analysis/types";

import styles from "./AnalysisWorkspace.module.css";

const ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司";

const STAGE_ICONS = {
  candidate_pool: PackageSearch,
  skill_loader: Layers3,
  deepseek: ClipboardCheck,
  gpt: Search,
  opus: FileCheck2,
  supplier_cost: Truck,
  profit_engine: BarChart3,
  final_report: CheckCircle2,
} as const;

const STATUS_LABELS: Record<string, string> = {
  framework_ready: "框架已就绪",
  pending_integration: "待接入",
};

export function AnalysisWorkspace({ view }: { view: "dashboard" | "analysis" }) {
  const [status, setStatus] = useState<RaFrameworkStatus | null>(null);
  const [profitSnapshots, setProfitSnapshots] = useState<RaProfitSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [profitError, setProfitError] = useState<string | null>(null);
  const [supplierResult, setSupplierResult] =
    useState<RaSupplierSearchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [profitLoading, setProfitLoading] = useState(false);
  const [profitForm, setProfitForm] = useState({
    asin: "",
    domesticShippingCny: "",
    exchangeRate: "",
    moq: "",
    supplierName: "",
    supplierUrl: "",
    unitPriceCny: "",
  });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([getRaFrameworkStatus(), getRaProfitSnapshots()])
      .then(([payload, snapshots]) => {
        if (cancelled) {
          return;
        }
        setStatus(payload);
        setProfitSnapshots(snapshots.items);
        setError(null);
      })
      .catch((requestError: unknown) => {
        if (cancelled) {
          return;
        }
        setError(
          requestError instanceof Error
            ? requestError.message
            : "R-A 后端框架状态暂时不可读取。",
        );
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const tableSummary = useMemo(() => {
    const tables = status?.tables ?? [];
    return {
      created: tables.filter((table) => table.exists).length,
      total: tables.length,
    };
  }, [status]);

  const candidateSource = status?.candidate_source;
  const stages = status?.stages ?? fallbackStages();
  const providers = status?.providers.roles ?? [];
  const formula = status?.profit_formula;

  async function handleManualProfit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProfitLoading(true);
    setProfitError(null);
    try {
      const snapshot = await calculateManualRaProfit({
        asin: profitForm.asin.trim().toUpperCase(),
        domestic_shipping_cny: optionalNumber(profitForm.domesticShippingCny),
        exchange_rate_usd_cny: optionalNumber(profitForm.exchangeRate),
        moq: optionalInteger(profitForm.moq),
        supplier_name: profitForm.supplierName.trim() || null,
        supplier_url: profitForm.supplierUrl.trim() || null,
        unit_price_cny: requiredNumber(profitForm.unitPriceCny),
      });
      setProfitSnapshots((current) => [snapshot, ...current].slice(0, 50));
      setProfitForm((current) => ({
        ...current,
        domesticShippingCny: "",
        moq: "",
        supplierName: "",
        supplierUrl: "",
        unitPriceCny: "",
      }));
    } catch (requestError) {
      setProfitError(
        requestError instanceof Error ? requestError.message : "利润测算失败。",
      );
    } finally {
      setProfitLoading(false);
    }
  }

  async function handleRunExistingOffers() {
    setProfitLoading(true);
    setProfitError(null);
    try {
      const result = await runRaProfitForExistingOffers(50);
      if (result.items.length > 0) {
        setProfitSnapshots((current) =>
          [...result.items, ...current].slice(0, 50),
        );
      } else {
        const snapshots = await getRaProfitSnapshots();
        setProfitSnapshots(snapshots.items);
      }
    } catch (requestError) {
      setProfitError(
        requestError instanceof Error ? requestError.message : "批量利润测算失败。",
      );
    } finally {
      setProfitLoading(false);
    }
  }

  async function handleSupplierSearch() {
    const asin = profitForm.asin.trim().toUpperCase();
    if (!asin) {
      setProfitError("请先输入要搜索供应商的 ASIN。");
      return;
    }
    setProfitLoading(true);
    setProfitError(null);
    try {
      const result = await searchRaSuppliers({
        asin,
        auto_calculate: true,
        exchange_rate_usd_cny: optionalNumber(profitForm.exchangeRate),
        min_gross_margin: null,
        result_limit: 5,
      });
      setSupplierResult(result);
      if (result.profit_run?.items.length) {
        setProfitSnapshots((current) =>
          [...result.profit_run!.items, ...current].slice(0, 50),
        );
      } else {
        const snapshots = await getRaProfitSnapshots();
        setProfitSnapshots(snapshots.items);
      }
    } catch (requestError) {
      setProfitError(
        requestError instanceof Error
          ? requestError.message
          : "1688 供应商搜索失败。",
      );
    } finally {
      setProfitLoading(false);
    }
  }

  return (
    <div className={styles.workspace}>
      <section className={styles.heroBand}>
        <div className={styles.heroText}>
          <span className={styles.kicker}>R-A 框架</span>
          <h2>{view === "dashboard" ? "产品分析总览" : "产品深度分析"}</h2>
          <p>
            {ORGANIZATION_NAME} 的 R-A 已接入真实利润测算入口；当前公式按美国站执行，佣金固定为售价
            15%，头程按体积重和实际重取大值后以 8 元/kg 计算，供应商成本由
            Serper + 1688 页面抓取或人工录入提供。
          </p>
        </div>
        <div className={styles.statusPill} data-state={error ? "error" : "ready"}>
          {error ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
          <span>{error ? "后端状态待恢复" : loading ? "读取框架状态" : "框架已就绪"}</span>
        </div>
      </section>

      {error ? (
        <section className={styles.noticeBand}>
          <AlertTriangle size={18} />
          <div>
            <strong>后端状态接口暂时不可读</strong>
            <span>{error}</span>
          </div>
        </section>
      ) : null}

      <section className={styles.metricGrid} aria-label="R-A 框架指标">
        <MetricCard
          icon={Database}
          label="R-W 产品总数"
          value={formatNumber(candidateSource?.total_products)}
          detail="只读来源 products_rw"
        />
        <MetricCard
          icon={PackageSearch}
          label="可进入 R-A"
          value={formatNumber(candidateSource?.ra_eligible)}
          detail="DeepSeek 通过或规则通过"
        />
        <MetricCard
          icon={ClipboardCheck}
          label="R-A 表结构"
          value={`${tableSummary.created}/${tableSummary.total || 9}`}
          detail="仅建结构，未执行任务"
        />
        <MetricCard
          icon={KeyRound}
          label="外部调用"
          value={status?.external_calls_enabled ? "可手动调用" : "未启用"}
          detail="只在点击搜索时调用"
        />
      </section>

      <section className={styles.sectionBand}>
        <div className={styles.sectionHeader}>
          <div>
            <span className={styles.kicker}>分析流水线</span>
            <h3>R-A 三层选品框架</h3>
          </div>
          <span className={styles.mutedBadge}>手动触发</span>
        </div>
        <div className={styles.stageGrid}>
          {stages.map((stage) => (
            <StageCard key={stage.id} stage={stage} />
          ))}
        </div>
      </section>

      <section className={styles.sectionBand}>
        <div className={styles.sectionHeader}>
          <div>
            <span className={styles.kicker}>利润测算</span>
            <h3>美国站毛利润公式</h3>
          </div>
          <span className={styles.readyTag}>已接入</span>
        </div>
        <div className={styles.formulaGrid}>
          <FormulaItem label="亚马逊佣金" value="售价 × 15%" />
          <FormulaItem label="头程运费" value="计费重 × 8 元/kg" />
          <FormulaItem label="体积重" value="长 × 宽 × 高 / 6000" />
          <FormulaItem
            label="毛利润"
            value={formula?.gross_profit_formula ?? "读取中"}
          />
        </div>
        <form className={styles.profitForm} onSubmit={handleManualProfit}>
          <label>
            <span>ASIN</span>
            <input
              required
              maxLength={20}
              value={profitForm.asin}
              onChange={(event) =>
                setProfitForm((current) => ({
                  ...current,
                  asin: event.target.value,
                }))
              }
            />
          </label>
          <label>
            <span>1688 产品成本（元）</span>
            <input
              required
              min="0.01"
              step="0.01"
              type="number"
              value={profitForm.unitPriceCny}
              onChange={(event) =>
                setProfitForm((current) => ({
                  ...current,
                  unitPriceCny: event.target.value,
                }))
              }
            />
          </label>
          <label>
            <span>1688 国内运费（元）</span>
            <input
              min="0"
              step="0.01"
              type="number"
              value={profitForm.domesticShippingCny}
              onChange={(event) =>
                setProfitForm((current) => ({
                  ...current,
                  domesticShippingCny: event.target.value,
                }))
              }
            />
          </label>
          <label>
            <span>汇率</span>
            <input
              min="0.01"
              step="0.01"
              type="number"
              value={profitForm.exchangeRate}
              placeholder={String(formula?.default_exchange_rate_usd_cny ?? 7.2)}
              onChange={(event) =>
                setProfitForm((current) => ({
                  ...current,
                  exchangeRate: event.target.value,
                }))
              }
            />
          </label>
          <label>
            <span>供应商</span>
            <input
              value={profitForm.supplierName}
              onChange={(event) =>
                setProfitForm((current) => ({
                  ...current,
                  supplierName: event.target.value,
                }))
              }
            />
          </label>
          <label>
            <span>MOQ</span>
            <input
              min="1"
              step="1"
              type="number"
              value={profitForm.moq}
              onChange={(event) =>
                setProfitForm((current) => ({
                  ...current,
                  moq: event.target.value,
                }))
              }
            />
          </label>
          <label className={styles.wideField}>
            <span>供应商链接</span>
            <input
              value={profitForm.supplierUrl}
              onChange={(event) =>
                setProfitForm((current) => ({
                  ...current,
                  supplierUrl: event.target.value,
                }))
              }
            />
          </label>
          <div className={styles.profitActions}>
            <button disabled={profitLoading} type="submit">
              <Calculator size={16} />
              计算并保存
            </button>
            <button
              disabled={profitLoading}
              type="button"
              onClick={handleRunExistingOffers}
            >
              <RefreshCw size={16} />
              批量计算已有报价
            </button>
            <button
              disabled={profitLoading}
              type="button"
              onClick={handleSupplierSearch}
            >
              <Search size={16} />
              搜索 1688 并计算
            </button>
          </div>
        </form>
        {profitError ? (
          <div className={styles.inlineError}>
            <AlertTriangle size={16} />
            <span>{profitError}</span>
          </div>
        ) : null}
        {supplierResult ? <SupplierSearchPanel result={supplierResult} /> : null}
        <ProfitSnapshotTable snapshots={profitSnapshots} />
      </section>

      <section className={styles.splitBand}>
        <div className={styles.sectionBand}>
          <div className={styles.sectionHeader}>
            <div>
              <span className={styles.kicker}>Provider</span>
              <h3>模型与工具角色</h3>
            </div>
          </div>
          <div className={styles.providerList}>
            {providers.length > 0 ? (
              providers.map((provider) => (
                <div className={styles.providerRow} key={provider.role}>
                  <div>
                    <strong>{provider.label}</strong>
                    <span>
                      {provider.service === "4sapi"
                        ? "通过 4sapi 代理调用"
                        : `服务：${provider.service}`}
                    </span>
                  </div>
                  <span
                    className={provider.configured ? styles.readyTag : styles.pendingTag}
                  >
                    {provider.configured ? "已配置" : "待配置"}
                  </span>
                </div>
              ))
            ) : (
              <div className={styles.emptyLine}>等待后端返回 provider 状态。</div>
            )}
          </div>
        </div>

        <div className={styles.sectionBand}>
          <div className={styles.sectionHeader}>
            <div>
              <span className={styles.kicker}>Skill</span>
              <h3>选品手册加载</h3>
            </div>
            <span className={status?.skill.loaded ? styles.readyTag : styles.pendingTag}>
              {status?.skill.loaded ? "已加载" : "待加载"}
            </span>
          </div>
          <div className={styles.skillFiles}>
            {(status?.skill.files ?? []).map((file) => (
              <div className={styles.fileRow} key={file.key}>
                <span>{file.label}</span>
                <strong>{file.exists ? file.filename : "缺失"}</strong>
              </div>
            ))}
            {!status?.skill.files.length ? (
              <div className={styles.emptyLine}>等待读取 R 系列 skill 文档。</div>
            ) : null}
          </div>
        </div>
      </section>

      <section className={styles.sectionBand}>
        <div className={styles.sectionHeader}>
          <div>
            <span className={styles.kicker}>后续接入</span>
            <h3>R-A 操作入口</h3>
          </div>
          <span className={styles.pendingTag}>分阶段接入</span>
        </div>
        <div className={styles.actionGrid}>
          <button disabled type="button">导入 R-W 候选品</button>
          <button disabled type="button">启动 DeepSeek 分析</button>
          <button disabled type="button">启动 GPT / Opus 分析</button>
          <button type="button" onClick={handleSupplierSearch}>
            <Search size={15} />
            搜索 1688 供应商
          </button>
          <button type="button" onClick={handleRunExistingOffers}>
            <Save size={15} />
            生成利润测算
          </button>
          <button disabled type="button">输出最终报告</button>
        </div>
      </section>
    </div>
  );
}

function FormulaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.formulaItem}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SupplierSearchPanel({ result }: { result: RaSupplierSearchResult }) {
  return (
    <div className={styles.supplierPanel}>
      <div className={styles.supplierHeader}>
        <div>
          <span className={styles.kicker}>1688 供应商发现</span>
          <strong>{result.asin}</strong>
        </div>
        <div className={styles.supplierStats}>
          <span>搜索 {result.counts.searches}</span>
          <span>候选 {result.counts.candidate_offers}</span>
          <span>有价格 {result.counts.priced_offers}</span>
        </div>
      </div>
      {result.warnings.length > 0 ? (
        <div className={styles.inlineWarning}>
          <AlertTriangle size={15} />
          <span>{result.warnings[0]}</span>
        </div>
      ) : null}
      <div className={styles.offerGrid}>
        {result.offers.length > 0 ? (
          result.offers.map((offer) => (
            <article className={styles.offerCard} key={offer.offer_id}>
              <div>
                <strong>{offer.supplier_name || "1688 供应商"}</strong>
                <span>{crawlerLabel(offer.crawler_status)}</span>
              </div>
              <div className={styles.offerNumbers}>
                <span>成本 {formatCny(offer.unit_price_cny)}</span>
                <span>运费 {formatCny(offer.domestic_shipping_cny)}</span>
                <span>MOQ {offer.moq ?? "未获取"}</span>
              </div>
              {offer.warning ? <small>{offer.warning}</small> : null}
              {offer.supplier_url ? (
                <a href={offer.supplier_url} rel="noreferrer" target="_blank">
                  打开 1688 页面
                </a>
              ) : null}
            </article>
          ))
        ) : (
          <div className={styles.emptyLine}>本次没有找到可用 1688 候选。</div>
        )}
      </div>
    </div>
  );
}

function ProfitSnapshotTable({ snapshots }: { snapshots: RaProfitSnapshot[] }) {
  if (snapshots.length === 0) {
    return <div className={styles.emptyLine}>暂无利润快照。</div>;
  }
  return (
    <div className={styles.profitTableWrap}>
      <table className={styles.profitTable}>
        <thead>
          <tr>
            <th>产品</th>
            <th>1688成本</th>
            <th>售价</th>
            <th>毛利润</th>
            <th>毛利率</th>
            <th>ROI</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {snapshots.slice(0, 20).map((snapshot) => (
            <tr key={snapshot.snapshot_id}>
              <td>
                <strong>{snapshot.asin}</strong>
                <span>{snapshot.title_zh || snapshot.title || "未命名产品"}</span>
              </td>
              <td>
                <strong>{formatCny(snapshot.supplier.unit_price_cny)}</strong>
                <span>运费 {formatCny(snapshot.supplier.domestic_shipping_cny)}</span>
              </td>
              <td>{formatUsd(snapshot.sell_price_usd)}</td>
              <td>{formatUsd(snapshot.gross_profit_usd)}</td>
              <td>{formatPercent(snapshot.gross_margin)}</td>
              <td>{formatPercent(snapshot.roi)}</td>
              <td>
                <span className={styles.verdictTag} data-verdict={snapshot.verdict}>
                  {verdictLabel(snapshot.verdict)}
                </span>
                {snapshot.warnings.length > 0 ? (
                  <small>{snapshot.warnings[0]}</small>
                ) : null}
                {snapshot.blocked_reasons.length > 0 ? (
                  <small>{snapshot.blocked_reasons[0]}</small>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MetricCard({
  detail,
  icon: Icon,
  label,
  value,
}: {
  detail: string;
  icon: typeof Database;
  label: string;
  value: string;
}) {
  return (
    <div className={styles.metricCard}>
      <Icon size={18} />
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function StageCard({ stage }: { stage: RaStage }) {
  const Icon = STAGE_ICONS[stage.id as keyof typeof STAGE_ICONS] ?? Layers3;
  return (
    <article className={styles.stageCard}>
      <div className={styles.stageIcon}>
        <Icon size={18} />
      </div>
      <div>
        <strong>{stage.label}</strong>
        <span>{stage.description}</span>
      </div>
      <em data-state={stage.status}>
        {STATUS_LABELS[stage.status] ?? stage.status}
      </em>
    </article>
  );
}

function formatNumber(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "读取中";
  }
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatUsd(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "未计算";
  }
  return `$${value.toFixed(2)}`;
}

function formatCny(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "未获取";
  }
  return `￥${value.toFixed(2)}`;
}

function formatPercent(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "未计算";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function verdictLabel(value: string | null | undefined) {
  if (value === "pass") {
    return "利润通过";
  }
  if (value === "reject") {
    return "利润不足";
  }
  if (value === "blocked") {
    return "缺少字段";
  }
  return "待计算";
}

function crawlerLabel(value: string | null | undefined) {
  if (value === "playwright") {
    return "Playwright 抓取";
  }
  if (value === "playwright_unavailable") {
    return "HTML 兜底抓取";
  }
  if (value === "playwright_failed") {
    return "Playwright 失败后兜底";
  }
  return value || "等待抓取";
}

function requiredNumber(value: string) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error("请输入有效成本。");
  }
  return parsed;
}

function optionalNumber(value: string) {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function optionalInteger(value: string) {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function fallbackStages(): RaStage[] {
  return [
    {
      id: "candidate_pool",
      label: "候选池",
      owner: "R-A",
      status: "framework_ready",
      description: "从 R-W 读取通过产品。",
    },
    {
      id: "skill_loader",
      label: "Skill Loader",
      owner: "R-A",
      status: "framework_ready",
      description: "加载 R 系列选品手册。",
    },
    {
      id: "deepseek",
      label: "DeepSeek 第一层",
      owner: "R-A",
      status: "pending_integration",
      description: "后续接入真实模型调用。",
    },
  ];
}

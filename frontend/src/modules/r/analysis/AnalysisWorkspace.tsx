"use client";

import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  ClipboardCheck,
  Database,
  FileCheck2,
  KeyRound,
  Layers3,
  PackageSearch,
  Search,
  Truck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getRaFrameworkStatus } from "@/modules/r/analysis/api";
import type { RaFrameworkStatus, RaStage } from "@/modules/r/analysis/types";

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
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getRaFrameworkStatus()
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setStatus(payload);
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

  return (
    <div className={styles.workspace}>
      <section className={styles.heroBand}>
        <div className={styles.heroText}>
          <span className={styles.kicker}>R-A 框架</span>
          <h2>{view === "dashboard" ? "产品分析总览" : "产品深度分析"}</h2>
          <p>
            {ORGANIZATION_NAME} 的 R-A 已按 R 系列文档搭好分析框架；当前只读展示结构状态，真实模型、
            Serper、1688 和利润计算将在后续阶段逐项接入。
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
          value={status?.external_calls_enabled ? "已启用" : "未启用"}
          detail="框架阶段不会消耗 token"
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
            <h3>当前不可执行的功能入口</h3>
          </div>
          <span className={styles.pendingTag}>功能未接入</span>
        </div>
        <div className={styles.actionGrid}>
          <button disabled type="button">导入 R-W 候选品</button>
          <button disabled type="button">启动 DeepSeek 分析</button>
          <button disabled type="button">启动 GPT / Opus 分析</button>
          <button disabled type="button">搜索 1688 供应商</button>
          <button disabled type="button">生成利润测算</button>
          <button disabled type="button">输出最终报告</button>
        </div>
      </section>
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

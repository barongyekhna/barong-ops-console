"use client";

import {
  ExternalLink,
  HelpCircle,
  LoaderCircle,
  Play,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  getRCommerceSkills,
  reviewRCommerceProduct,
  runRCommerceTask,
} from "./api";
import styles from "./RCommerceWorkspace.module.css";
import type {
  RChannelRecommendation,
  RCommerceRunRequest,
  RCommerceRunResponse,
  RCommerceSkillResponse,
  RProductCandidate,
  RSupplier,
} from "./types";

type ReviewState = {
  pending?: boolean;
  status?: "saved" | "removed";
  message?: string;
};

type SkillCopy = {
  role: string;
  input: string;
  output: string;
  deepseek: string;
};

const SKILL_COPY: Record<string, SkillCopy> = {
  "1688_supplier_skill": {
    deepseek: "不调用 DeepSeek；当前走 mock 1688 provider。",
    input: "main_keyword、category、purchase_price_range",
    output: "supplier_list、supply_chain_incomplete",
    role: "生成 2-5 条供应商候选，并标准化 MOQ、价格、发货地和代发能力。",
  },
  amazon_selection_skill: {
    deepseek: "不调用 DeepSeek；使用本地 R 文档规则。",
    input: "关键词、类目、价格、市场、风险等级",
    output: "amazon_scorecard",
    role: "评估 Amazon 需求、利润、竞争、FBA 适配和风险。",
  },
  decision_engine_skill: {
    deepseek: "不调用 DeepSeek；使用本地评分模型。",
    input: "Amazon 评分、独立站评分、风险结论",
    output: "final_decision、channel_recommendation",
    role: "汇总打分并给出 GO / TEST / WATCH / REJECT 和渠道建议。",
  },
  deepseek_reasoning_skill: {
    deepseek: "调用 mock DeepSeek V4 Pro provider；当前不需要 API KEY。",
    input: "候选产品、供应链、价格、渠道建议、决策结果",
    output: "reason.text、reason.source",
    role: "生成人话中文选品理由，解释为什么这个产品值得进入候选。",
  },
  independent_site_selection_skill: {
    deepseek: "不调用 DeepSeek；使用本地 R 文档规则。",
    input: "关键词、类目、价格、市场、风险等级",
    output: "site_scorecard",
    role: "评估独立站 SEO、内容潜力、广告和 B2B 机会。",
  },
  risk_filter_skill: {
    deepseek: "不调用 DeepSeek；使用本地硬规则。",
    input: "候选产品、评分卡、风险词",
    output: "risk_decision",
    role: "过滤 IP、合规、物流、广告政策和不可控退货风险。",
  },
  source_validation_skill: {
    deepseek: "不调用 DeepSeek；校验输入和本地资料完整性。",
    input: "任务输入和 R 系统资料",
    output: "validated_dataset",
    role: "确认输入完整度、资料加载状态和本地数据权重。",
  },
};

const DEFAULT_FORM: RCommerceRunRequest = {
  category: "home improvement",
  main_keyword: "portable door draft stopper",
  market: "Both",
  price_range: "19-39",
  risk_level: "medium",
  target_count: 3,
  task_budget_usd: 0.01,
};

function channelLabel(channel: RChannelRecommendation) {
  if (channel === "amazon") {
    return "amazon";
  }
  if (channel === "site") {
    return "site";
  }
  return "dual";
}

function boolLabel(value: boolean) {
  return value ? "支持" : "不支持";
}

function valueText(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  return String(value);
}

function formatSizeWeight(product: RProductCandidate) {
  const size = product.size_weight;
  return `${size.length_cm} x ${size.width_cm} x ${size.height_cm} cm / ${size.weight_kg} kg`;
}

function supplierLine(supplier: RSupplier) {
  return `${supplier.price_range} | MOQ ${supplier.MOQ} | ${supplier.shipping_origin}`;
}

function skillCopy(
  name: string,
  skills: RCommerceSkillResponse["skills"] | null,
): SkillCopy {
  const fallback = SKILL_COPY[name] ?? {
    deepseek: "不调用 DeepSeek。",
    input: "R V3 task context",
    output: name,
    role: "R V3 本地 skill。",
  };
  const live = skills?.[name];
  return {
    deepseek: live?.deepseek_call || fallback.deepseek,
    input: live?.input || fallback.input,
    output: live?.output || fallback.output,
    role: live?.functions?.join("；") || fallback.role,
  };
}

function SkillItem({
  name,
  skills,
}: {
  name: string;
  skills: RCommerceSkillResponse["skills"] | null;
}) {
  const copy = skillCopy(name, skills);
  return (
    <div className={styles.skillItem}>
      <strong>{name}</strong>
      <button
        aria-label={`${name} info`}
        className={styles.iconInfoButton}
        type="button"
      >
        <HelpCircle aria-hidden="true" size={16} />
      </button>
      <div className={styles.tooltip} role="tooltip">
        <span>skill作用：{copy.role}</span>
        <span>输入：{copy.input}</span>
        <span>输出：{copy.output}</span>
        <span>DeepSeek调用说明：{copy.deepseek}</span>
      </div>
    </div>
  );
}

function SupplierCard({ supplier }: { supplier: RSupplier }) {
  return (
    <article className={styles.supplierCard}>
      <img alt={supplier.supplier_name} src={supplier.preview_image} />
      <div className={styles.supplierBody}>
        <strong>{supplier.supplier_name}</strong>
        <span>{supplierLine(supplier)}</span>
        <span>一件代发：{boolLabel(supplier.dropshipping_support)}</span>
        <span>一件起批：{boolLabel(supplier.moq_1_allowed)}</span>
        <span>样品：{boolLabel(supplier.sample_availability)}</span>
        <span>评分：{supplier.rating ?? "-"}</span>
        <a href={supplier.product_link} rel="noreferrer" target="_blank">
          mock 1688 链接 <ExternalLink aria-hidden="true" size={12} />
        </a>
      </div>
    </article>
  );
}

function ProductCard({
  onReview,
  product,
  review,
}: {
  product: RProductCandidate;
  review: ReviewState | undefined;
  onReview: (action: "Save" | "Remove", product: RProductCandidate) => void;
}) {
  const locked = review?.pending || review?.status === "saved" || review?.status === "removed";
  return (
    <article className={styles.productCard}>
      <div className={styles.productHeader}>
        <div>
          <span className="eyebrow">Selected Product</span>
          <h3>{product.main_keyword}</h3>
        </div>
        <div className={styles.productMeta}>
          <span className={styles.statusBadge}>{product.market}</span>
          <span className={styles.statusBadge}>
            {channelLabel(product.channel_recommendation)}
          </span>
          <span className={styles.sourceBadge} title="由 DeepSeek V4 Pro 生成">
            {product.reason.source}
          </span>
        </div>
      </div>

      <div className={styles.metricGrid}>
        <div className={styles.metric}>
          <span>拿货价区间</span>
          <strong>{product.purchase_price_range}</strong>
        </div>
        <div className={styles.metric}>
          <span>销售价</span>
          <strong>{product.selling_price}</strong>
        </div>
        <div className={styles.metric}>
          <span>尺寸重量</span>
          <strong>{formatSizeWeight(product)}</strong>
        </div>
        <div className={styles.metric}>
          <span>供应链</span>
          <strong>
            {product.supplier_list.length} 条
            {product.supply_chain_incomplete ? " / incomplete" : ""}
          </strong>
        </div>
      </div>

      <div className={styles.supplierGrid}>
        {product.supplier_list.map((supplier) => (
          <SupplierCard
            key={`${product.candidate_id}:${supplier.supplier_name}`}
            supplier={supplier}
          />
        ))}
      </div>

      <div className={styles.reasonBox} title="由 DeepSeek V4 Pro 生成">
        <p>{product.reason.text}</p>
        <span className={styles.reasonHint}>
          由 DeepSeek V4 Pro 生成选品分析总结
        </span>
      </div>

      <div className={styles.reviewActions}>
        {review?.message ? (
          <span className={styles.reviewStatus}>{review.message}</span>
        ) : null}
        <button
          className={styles.secondaryButton}
          disabled={locked}
          onClick={() => onReview("Save", product)}
          type="button"
        >
          {review?.pending ? (
            <LoaderCircle aria-hidden="true" className="spin" size={16} />
          ) : (
            <Save aria-hidden="true" size={16} />
          )}
          Save
        </button>
        <button
          className={styles.dangerButton}
          disabled={locked}
          onClick={() => onReview("Remove", product)}
          type="button"
        >
          <Trash2 aria-hidden="true" size={16} />
          Remove
        </button>
      </div>
    </article>
  );
}

export function RCommerceWorkspace() {
  const [form, setForm] = useState<RCommerceRunRequest>(DEFAULT_FORM);
  const [result, setResult] = useState<RCommerceRunResponse | null>(null);
  const [skills, setSkills] = useState<RCommerceSkillResponse | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewStates, setReviewStates] = useState<Record<string, ReviewState>>({});

  useEffect(() => {
    let mounted = true;
    getRCommerceSkills()
      .then((payload) => {
        if (mounted) {
          setSkills(payload);
        }
      })
      .catch(() => {
        if (mounted) {
          setSkills(null);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  const skillNames = useMemo(
    () =>
      skills?.required_skills?.length
        ? skills.required_skills
        : Object.keys(SKILL_COPY),
    [skills?.required_skills],
  );

  async function handleRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsRunning(true);
    setError(null);
    setReviewStates({});
    try {
      const payload = await runRCommerceTask(form);
      setResult(payload);
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "R 任务执行失败。");
    } finally {
      setIsRunning(false);
    }
  }

  async function handleReview(action: "Save" | "Remove", product: RProductCandidate) {
    setReviewStates((current) => ({
      ...current,
      [product.candidate_id]: { pending: true },
    }));
    try {
      const response = await reviewRCommerceProduct(action, product);
      setReviewStates((current) => ({
        ...current,
        [product.candidate_id]: {
          message:
            response.status === "saved"
              ? `已保存到 ${response.database_path}`
              : "已移除候选",
          status: response.status,
        },
      }));
    } catch (reviewError) {
      setReviewStates((current) => ({
        ...current,
        [product.candidate_id]: {
          message:
            reviewError instanceof Error ? reviewError.message : "审核动作失败。",
        },
      }));
    }
  }

  const budgetUsage = result?.budget_usage ?? {};

  return (
    <div className={styles.workspace}>
      <section className={styles.controlPanel}>
        <div className={styles.panelHeader}>
          <div>
            <h2>R V3 选品任务</h2>
            <p>Mock provider production mode；无需 Amazon、1688、OpenAI 或 Claude API KEY。</p>
          </div>
          <span className={styles.modeBadge}>
            <Sparkles aria-hidden="true" size={14} />
            mock provider
          </span>
        </div>

        <form className={styles.workspace} onSubmit={handleRun}>
          <div className={styles.formGrid}>
            <label className={styles.field}>
              <span>主关键词</span>
              <input
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    main_keyword: event.target.value,
                  }))
                }
                required
                value={form.main_keyword}
              />
            </label>
            <label className={styles.field}>
              <span>类目</span>
              <input
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    category: event.target.value,
                  }))
                }
                value={form.category}
              />
            </label>
            <label className={styles.field}>
              <span>市场</span>
              <select
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    market: event.target.value as RCommerceRunRequest["market"],
                  }))
                }
                value={form.market}
              >
                <option value="Both">Both</option>
                <option value="Amazon">Amazon</option>
                <option value="独立站">独立站</option>
              </select>
            </label>
            <label className={styles.field}>
              <span>售价区间</span>
              <input
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    price_range: event.target.value,
                  }))
                }
                value={form.price_range}
              />
            </label>
            <label className={styles.field}>
              <span>目标数量</span>
              <input
                min={1}
                max={20}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    target_count: Number(event.target.value),
                  }))
                }
                type="number"
                value={form.target_count}
              />
            </label>
            <label className={styles.field}>
              <span>task_budget_usd</span>
              <input
                min={0.001}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    task_budget_usd: Number(event.target.value),
                  }))
                }
                required
                step={0.001}
                type="number"
                value={form.task_budget_usd}
              />
            </label>
            <label className={styles.field}>
              <span>风险等级</span>
              <select
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    risk_level: event.target.value as RCommerceRunRequest["risk_level"],
                  }))
                }
                value={form.risk_level}
              >
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </label>
          </div>

          <div className={styles.formActions}>
            <span className={styles.budgetLine}>1 USD = 1000 crawls</span>
            <button className={styles.primaryButton} disabled={isRunning} type="submit">
              {isRunning ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <Play aria-hidden="true" size={16} />
              )}
              启动任务
            </button>
          </div>
          <p className={styles.message} role="alert">
            {error}
          </p>
        </form>
      </section>

      <section className={styles.skillPanel}>
        <div className={styles.panelHeader}>
          <h3>R V3 Skills</h3>
          <span className={styles.modeBadge}>{skills?.provider_mode ?? "mock"}</span>
        </div>
        <div className={styles.skillGrid}>
          {skillNames.map((name) => (
            <SkillItem key={name} name={name} skills={skills?.skills ?? null} />
          ))}
        </div>
      </section>

      <section className={styles.resultPanel}>
        <div className={styles.panelHeader}>
          <div>
            <h3>选品结果</h3>
            <p>{result ? result.report_name : "等待任务输出"}</p>
          </div>
          <span className={styles.modeBadge}>
            crawl_count {result?.crawl_count ?? 0}
          </span>
        </div>

        {result ? (
          <div className={styles.summaryStrip}>
            <div className={styles.summaryItem}>
              <span>selected_products</span>
              <strong>{result.selected_products.length}</strong>
            </div>
            <div className={styles.summaryItem}>
              <span>crawl_budget</span>
              <strong>{valueText(budgetUsage.crawl_budget)}</strong>
            </div>
            <div className={styles.summaryItem}>
              <span>remaining_crawls</span>
              <strong>{valueText(budgetUsage.remaining_crawls)}</strong>
            </div>
            <div className={styles.summaryItem}>
              <span>stop_reason</span>
              <strong>{valueText(budgetUsage.stop_reason)}</strong>
            </div>
          </div>
        ) : null}

        {result && result.selected_products.length > 0 ? (
          <div className={styles.productList}>
            {result.selected_products.map((product) => (
              <ProductCard
                key={product.candidate_id}
                onReview={handleReview}
                product={product}
                review={reviewStates[product.candidate_id]}
              />
            ))}
          </div>
        ) : (
          <div className={styles.emptyState}>暂无成功产品</div>
        )}
      </section>
    </div>
  );
}

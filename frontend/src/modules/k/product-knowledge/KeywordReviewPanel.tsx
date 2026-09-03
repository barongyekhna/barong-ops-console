"use client";

/**
 * 关键词调研 + 风险词审核。
 *
 * 从 ProductDetail 抽出的第三簇（2026-09-01），也是最大的一块：
 * 320 行 JSX、14 个 state、4 个 handler、3 个 useMemo。
 *
 * 抽得动的原因是它对外只有**两个布尔**：「已提交」和「改过了」。
 * 底部的 P 系列就绪度靠这两个值算，除此之外整簇都是自己的事。
 * 所以这里把它们通过回调报回上层，其余 12 个 state 全留在本地 ——
 * 上层从此不必再关心「谁在改关键词、改到哪一步」。
 *
 * 风险词那一列刻意**不给批量默认值**：每个风险词都要人工点通过或拒绝，
 * 漏一个就不让提交。这是给品牌门和合规兜底的最后一道人工闸。
 */

import {
  CheckCircle2,
  LoaderCircle,
  Play,
  Plus,
  RotateCcw,
  ShieldCheck,
  X,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { createKeyword, deleteKeyword, getKeywordsByProduct } from "@/modules/k19/keywords/api";
import type { KeywordEntry } from "@/modules/k19/keywords/types";

import styles from "./ProductKnowledge.module.css";
import type {
  KWorkflowStartPayload,
  ProductKnowledgeDetail,
  RiskDecisionValue,
} from "./types";

/** 一条待审关键词。来源决定移除时走哪条路——已保存的要真删，AI/人工的只是本地丢掉。 */
export type KeywordReviewItem = {
  detail?: string;
  id?: string;
  keyword: string;
  source: "saved" | "ai" | "manual";
};

type RiskKeyword = { term: string; reason?: string | null };

/** 原话术照搬，重构不改文案。 */
const KEYWORD_RESEARCH_NOT_STARTED_MESSAGE =
  "关键词调研尚未开始，请先启动关键词调研。";

type KeywordReviewPanelProps = {
  product: ProductKnowledgeDetail;
  /** 工作流快照。为 null 表示还没跑过调研。 */
  workflow: KeywordWorkflowLike | null;
  workflowError: string;
  isWorkflowBusy: boolean;
  keywordProgress: number;
  riskKeywords: RiskKeyword[];
  /** Claude 终筛出来的非风险词。 */
  generatedKeywords: string[];
  keywordSteps: readonly { key: string; label: string }[];
  stepStatus: (step: string) => string;
  isRetryableStepStatus: (status: string) => boolean;
  statusLabel: (status: string) => string;
  runtimeStatusLabel: (status: string | null | undefined) => string;
  productPlaceholder: string;
  onRefreshWorkflow?: () => void;
  onStartWorkflow?: (payload: KWorkflowStartPayload) => void;
  onRetryWorkflowStep?: (step: string, payload: KWorkflowStartPayload) => void;
  onSubmitRiskReview?: (
    decisions: { decision: RiskDecisionValue; reason: string | null; term: string }[],
    noRiskKeywords: boolean,
  ) => Promise<unknown> | unknown;
  /** 「已提交」「改过了」是这一簇唯一的对外信号——P 系列就绪度靠它们算。 */
  onSubmittedChange: (submitted: boolean) => void;
  onTouchedChange: (touched: boolean) => void;
  complete: boolean;
  dirty: boolean;
  normalizeKeywordKey: (keyword: string) => string;
};

type KeywordWorkflowLike = { id?: string; status?: string | null } | null;

export function KeywordReviewPanel({
  product,
  workflow,
  workflowError,
  isWorkflowBusy,
  keywordProgress,
  riskKeywords,
  generatedKeywords,
  keywordSteps,
  stepStatus,
  isRetryableStepStatus,
  statusLabel,
  runtimeStatusLabel,
  productPlaceholder,
  onRefreshWorkflow,
  onStartWorkflow,
  onRetryWorkflowStep,
  onSubmitRiskReview,
  onSubmittedChange,
  onTouchedChange,
  complete,
  dirty,
  normalizeKeywordKey,
}: KeywordReviewPanelProps) {
  const [targetMarket, setTargetMarket] = useState(product.target_market ?? "US");
  const [serpQuery, setSerpQuery] = useState("");
  const [entries, setEntries] = useState<KeywordEntry[]>([]);
  const [manualKeywords, setManualKeywords] = useState<string[]>([]);
  const [manualInput, setManualInput] = useState("");
  const [removedGenerated, setRemovedGenerated] = useState<string[]>([]);
  const [optimisticRemoved, setOptimisticRemoved] = useState<string[]>([]);
  const [pendingRemoval, setPendingRemoval] = useState<string[]>([]);
  const [reviewError, setReviewError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [riskDecisions, setRiskDecisions] = useState<
    Record<string, RiskDecisionValue>
  >({});

  const productId = product.id;

  const loadEntries = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await getKeywordsByProduct(productId);
      setEntries(response.keyword_entries);
    } catch (error) {
      setReviewError(
        error instanceof Error ? error.message : "关键词列表加载失败。",
      );
    } finally {
      setIsLoading(false);
    }
  }, [productId]);

  useEffect(() => {
    void loadEntries();
  }, [loadEntries]);

  // 换了工作流就重来一遍风险决策——上一轮的通过/拒绝对新一轮不作数。
  useEffect(() => {
    setRiskDecisions({});
    setReviewError("");
  }, [workflow?.id]);

  const riskKeys = useMemo(
    () => new Set(riskKeywords.map((item) => normalizeKeywordKey(item.term))),
    [normalizeKeywordKey, riskKeywords],
  );

  const activeEntries = useMemo(
    () => entries.filter((entry) => entry.status !== "archived"),
    [entries],
  );

  const nonRiskKeywords = useMemo<KeywordReviewItem[]>(() => {
    const savedKeys = new Set<string>();
    const removedKeys = new Set([...removedGenerated, ...optimisticRemoved]);
    const savedItems = activeEntries
      .filter((entry) => !riskKeys.has(normalizeKeywordKey(entry.keyword)))
      .map((entry) => {
        savedKeys.add(normalizeKeywordKey(entry.keyword));
        return {
          detail: entry.source === "manual" ? "人工保存" : "已保存",
          id: entry.id,
          keyword: entry.keyword,
          source: "saved" as const,
        };
      });
    const aiItems = generatedKeywords
      .filter((keyword) => {
        const key = normalizeKeywordKey(keyword);
        return !savedKeys.has(key) && !riskKeys.has(key) && !removedKeys.has(key);
      })
      .map((keyword) => ({
        detail: "Claude 终筛",
        keyword,
        source: "ai" as const,
      }));
    const manualItems = manualKeywords
      .filter((keyword) => {
        const key = normalizeKeywordKey(keyword);
        return !savedKeys.has(key) && !riskKeys.has(key) && !removedKeys.has(key);
      })
      .map((keyword) => ({
        detail: "人工新增",
        keyword,
        source: "manual" as const,
      }));
    return [...savedItems, ...aiItems, ...manualItems];
  }, [
    activeEntries,
    generatedKeywords,
    manualKeywords,
    normalizeKeywordKey,
    optimisticRemoved,
    removedGenerated,
    riskKeys,
  ]);

  function buildWorkflowPayload(): KWorkflowStartPayload {
    const mainKeyword = product.main_keyword ?? product.primary_keyword ?? "";
    return {
      main_keyword: mainKeyword,
      seed_keywords: [],
      serp_query: serpQuery.trim() || mainKeyword || null,
      target_market: targetMarket,
    };
  }

  function startWorkflow() {
    onTouchedChange(true);
    onSubmittedChange(false);
    onStartWorkflow?.(buildWorkflowPayload());
  }

  function retryStep(step: string) {
    onTouchedChange(true);
    onSubmittedChange(false);
    onRetryWorkflowStep?.(step, buildWorkflowPayload());
  }

  function addManualKeyword() {
    const keyword = manualInput.trim();
    if (!keyword) {
      return;
    }
    const existing = new Set(
      nonRiskKeywords.map((item) => normalizeKeywordKey(item.keyword)),
    );
    if (existing.has(normalizeKeywordKey(keyword))) {
      setReviewError("这个关键词已在非风险关键词列表中。");
      return;
    }
    setManualKeywords((current) => [...current, keyword]);
    setManualInput("");
    onTouchedChange(true);
    setReviewError("");
  }

  async function removeKeyword(item: KeywordReviewItem) {
    const key = normalizeKeywordKey(item.keyword);
    if (pendingRemoval.includes(key)) {
      return;
    }
    if (item.source !== "saved") {
      setOptimisticRemoved((current) =>
        current.includes(key) ? current : [...current, key],
      );
    }
    setPendingRemoval((current) =>
      current.includes(key) ? current : [...current, key],
    );
    setReviewError("");
    onTouchedChange(true);
    if (item.source === "saved" && item.id) {
      try {
        await deleteKeyword(item.id);
        await loadEntries();
      } catch (error) {
        setOptimisticRemoved((current) =>
          current.filter((currentKey) => currentKey !== key),
        );
        setReviewError(
          error instanceof Error ? error.message : "关键词移除失败。",
        );
      } finally {
        setPendingRemoval((current) =>
          current.filter((currentKey) => currentKey !== key),
        );
      }
      return;
    }
    if (item.source === "manual") {
      setManualKeywords((current) =>
        current.filter((keyword) => normalizeKeywordKey(keyword) !== key),
      );
      setPendingRemoval((current) =>
        current.filter((currentKey) => currentKey !== key),
      );
      return;
    }
    setRemovedGenerated((current) =>
      current.includes(key) ? current : [...current, key],
    );
    setPendingRemoval((current) =>
      current.filter((currentKey) => currentKey !== key),
    );
  }

  async function submitReview() {
    const missing = riskKeywords.filter((item) => !riskDecisions[item.term]);
    if (missing.length > 0) {
      setReviewError("每个风险词都需要人工选择通过或拒绝。");
      return;
    }
    if (nonRiskKeywords.length === 0) {
      setReviewError(
        workflow
          ? "请至少保留一个非风险关键词。"
          : KEYWORD_RESEARCH_NOT_STARTED_MESSAGE,
      );
      return;
    }

    setIsSaving(true);
    setReviewError("");
    try {
      const savedKeys = new Set(
        activeEntries.map((entry) => normalizeKeywordKey(entry.keyword)),
      );
      const newKeywords = nonRiskKeywords.filter(
        (item) => !item.id && !savedKeys.has(normalizeKeywordKey(item.keyword)),
      );
      await Promise.all(
        newKeywords.map((item) =>
          createKeyword({
            keyword: item.keyword,
            product_id: productId,
            source: item.source === "manual" ? "manual" : "K18",
            status: "active",
          }),
        ),
      );
      await onSubmitRiskReview?.(
        riskKeywords.map((item) => {
          const decision = riskDecisions[item.term] as RiskDecisionValue;
          return {
            decision,
            reason: decision === "reject" ? "Rejected in manual review" : null,
            term: item.term,
          };
        }),
        riskKeywords.length === 0,
      );

      await loadEntries();
      setManualKeywords([]);
      onTouchedChange(false);
      onSubmittedChange(true);
    } catch (error) {
      setReviewError(
        error instanceof Error ? error.message : "关键词审核保存失败。",
      );
    } finally {
      setIsSaving(false);
    }
  }

  function decideAll(decision: RiskDecisionValue) {
    onTouchedChange(true);
    setRiskDecisions(
      Object.fromEntries(riskKeywords.map((item) => [item.term, decision])),
    );
  }

  function decideOne(term: string, decision: RiskDecisionValue) {
    onTouchedChange(true);
    setRiskDecisions((current) => ({ ...current, [term]: decision }));
  }

  return (
    <section aria-labelledby="k-keywords" className={styles.workflowSection}>
      <div className={styles.sellingPointsHeading}>
        <div>
          <span className={styles.eyebrow}>关键词</span>
          <h4 id="k-keywords">关键词审核</h4>
        </div>
        <button
          className="secondary-button"
          disabled={isWorkflowBusy}
          onClick={onRefreshWorkflow}
          type="button"
        >
          <RotateCcw aria-hidden="true" size={16} />
          刷新
        </button>
      </div>

      {workflowError ? (
        <p className={styles.sellingPointsError}>{workflowError}</p>
      ) : null}

      <div className={styles.workflowMetrics}>
        <div>
          <dt>状态</dt>
          <dd>{runtimeStatusLabel(workflow?.status)}</dd>
        </div>
        <div>
          <dt>进度</dt>
          <dd>{keywordProgress}%</dd>
        </div>
      </div>

      <div
        aria-label="关键词进度"
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={keywordProgress}
        className={styles.workflowProgress}
        role="progressbar"
      >
        <span style={{ width: `${keywordProgress}%` }} />
      </div>

      <ol className={styles.workflowStages}>
        {keywordSteps.map((step) => {
          const status = stepStatus(step.key);
          const canRetry = isRetryableStepStatus(status);
          return (
            <li data-status={status} key={step.key}>
              <div>
                <span>{step.label}</span>
                <strong>{statusLabel(status)}</strong>
              </div>
              <button
                className="secondary-button"
                disabled={!canRetry || isWorkflowBusy}
                onClick={() => retryStep(step.key)}
                type="button"
              >
                {isWorkflowBusy && canRetry ? (
                  <LoaderCircle aria-hidden="true" className="spin" size={14} />
                ) : (
                  <RotateCcw aria-hidden="true" size={14} />
                )}
                重试
              </button>
            </li>
          );
        })}
      </ol>
      <p className={styles.keywordAiNotice}>
        AI 调用可能失败，请点击对应步骤重试。
      </p>

      <div className={styles.workflowStartGrid}>
        <label className={styles.field}>
          <span>目标市场</span>
          <select
            onChange={(event) => setTargetMarket(event.target.value)}
            value={targetMarket}
          >
            <option value="US">美国</option>
            <option value="UK">英国</option>
            <option value="EU">欧盟</option>
            <option value="CN">中国</option>
            <option value="JP">日本</option>
            <option value="KR">韩国</option>
            <option value="RU">俄罗斯</option>
            <option value="GCC">中东</option>
            <option value="LATAM">拉美</option>
          </select>
        </label>
        <label className={styles.field}>
          <span>关键词查询</span>
          <input
            onChange={(event) => setSerpQuery(event.target.value)}
            placeholder={productPlaceholder}
            value={serpQuery}
          />
        </label>
        <button
          className="primary-button"
          disabled={isWorkflowBusy}
          onClick={startWorkflow}
          type="button"
        >
          {isWorkflowBusy ? (
            <LoaderCircle aria-hidden="true" className="spin" size={16} />
          ) : (
            <Play aria-hidden="true" size={16} />
          )}
          启动关键词调研
        </button>
      </div>

      {reviewError ? (
        <p className={styles.sellingPointsError}>{reviewError}</p>
      ) : null}

      <div className={styles.keywordReviewGrid}>
        <div className={styles.keywordColumn}>
          <div className={styles.columnHeading}>
            <strong>非风险关键词</strong>
            <span>{nonRiskKeywords.length} 个</span>
          </div>
          <div className={styles.manualAddRow}>
            <input
              onChange={(event) => setManualInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addManualKeyword();
                }
              }}
              placeholder="人工添加非风险关键词"
              value={manualInput}
            />
            <button
              className="secondary-button"
              onClick={addManualKeyword}
              type="button"
            >
              <Plus aria-hidden="true" size={15} />
              添加
            </button>
          </div>
          {isLoading ? (
            <p className={styles.sellingPointsEmpty}>正在加载关键词。</p>
          ) : null}
          {nonRiskKeywords.length === 0 && !isLoading ? (
            <p className={styles.sellingPointsEmpty}>
              Claude 终筛后会在这里显示优质关键词。
            </p>
          ) : (
            <div className={styles.kwChipCloud}>
              {nonRiskKeywords.map((item) => {
                const keywordKey = normalizeKeywordKey(item.keyword);
                const isRemoving = pendingRemoval.includes(keywordKey);
                return (
                  <span
                    className={styles.kwChip}
                    data-removing={isRemoving}
                    key={`${item.source}-${item.id ?? item.keyword}`}
                    title={item.detail || item.keyword}
                  >
                    {item.keyword}
                    <button
                      aria-label={`移除 ${item.keyword}`}
                      disabled={isRemoving}
                      onClick={() => void removeKeyword(item)}
                      type="button"
                    >
                      {isRemoving ? (
                        <LoaderCircle
                          aria-hidden="true"
                          className="spin"
                          size={11}
                        />
                      ) : (
                        <X aria-hidden="true" size={11} />
                      )}
                    </button>
                  </span>
                );
              })}
            </div>
          )}
        </div>

        <div className={styles.keywordColumn}>
          <div className={styles.columnHeading}>
            <strong>风险词</strong>
            <span>
              已决策{" "}
              {riskKeywords.filter((item) => riskDecisions[item.term]).length}/
              {riskKeywords.length}
            </span>
          </div>
          {riskKeywords.length > 0 ? (
            <div className={styles.riskBatchBar}>
              <button
                className="secondary-button"
                onClick={() => decideAll("approve")}
                type="button"
              >
                <CheckCircle2 aria-hidden="true" size={14} />
                全部通过
              </button>
              <button
                className="secondary-button"
                onClick={() => decideAll("reject")}
                type="button"
              >
                <XCircle aria-hidden="true" size={14} />
                全部拒绝
              </button>
            </div>
          ) : null}
          {riskKeywords.length === 0 ? (
            <p className={styles.sellingPointsEmpty}>
              暂无风险词。Claude 终筛完成后仍需提交关键词审核。
            </p>
          ) : (
            <ul className={styles.riskCompactList}>
              {riskKeywords.map((item) => {
                const decision = riskDecisions[item.term];
                return (
                  <li data-decision={decision ?? "none"} key={item.term}>
                    <span
                      className={styles.riskTermText}
                      title={item.reason || item.term}
                    >
                      <strong>{item.term}</strong>
                      {item.reason ? <em>{item.reason}</em> : null}
                    </span>
                    <span className={styles.riskActions}>
                      <button
                        aria-label={`通过 ${item.term}`}
                        aria-pressed={decision === "approve"}
                        data-kind="approve"
                        onClick={() => decideOne(item.term, "approve")}
                        type="button"
                      >
                        <CheckCircle2 aria-hidden="true" size={15} />
                      </button>
                      <button
                        aria-label={`拒绝 ${item.term}`}
                        aria-pressed={decision === "reject"}
                        data-kind="reject"
                        onClick={() => decideOne(item.term, "reject")}
                        type="button"
                      >
                        <XCircle aria-hidden="true" size={15} />
                      </button>
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      {reviewError ? (
        <p className={styles.sellingPointsError} role="alert">
          {reviewError}
        </p>
      ) : null}
      <div className={styles.sectionFooter}>
        <span data-complete={complete}>
          {complete
            ? "关键词已保存"
            : dirty
              ? "关键词已修改，待重新提交"
              : "关键词待审核"}
        </span>
        <button
          className="primary-button"
          disabled={isSaving || isWorkflowBusy}
          onClick={() => void submitReview()}
          type="button"
        >
          {isSaving ? (
            <LoaderCircle aria-hidden="true" className="spin" size={16} />
          ) : (
            <ShieldCheck aria-hidden="true" size={16} />
          )}
          提交关键词
        </button>
      </div>
    </section>
  );
}

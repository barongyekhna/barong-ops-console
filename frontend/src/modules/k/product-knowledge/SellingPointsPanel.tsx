"use client";

/**
 * 卖点与文案审核。
 *
 * 从 ProductDetail 抽出的第四簇（2026-09-01），13 个 state、6 个 handler、
 * 439 行 JSX —— 整个详情页里最大的一块。
 *
 * 对外接口和关键词那簇一样，只有**两个信号**：
 * 「已批准」和「改过了」。P 系列就绪度靠它们算，其余全是这里自己的事。
 *
 * 两条不能丢的规矩写在代码里：
 * - 三步没走完不许提交。approve 会把当前内容冻结成已审版本、并清空已生成的
 *   文案与作图指令；阶段 3 没跑完就提交，商品页文案会以空值定型。
 *   **编辑不受此限**——阶段 1 一出结果就能改，那正是鼓励的用法。
 * - 后台分阶段推送会反复触发回灌 effect。运营已经在改的内容绝不能被后来的
 *   阶段冲掉，所以 touched / isEditing 是「别覆盖我」的闸门。
 */

import {
  CheckCircle2,
  ClipboardCopy,
  Copy,
  LoaderCircle,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  Wand2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type {
  BulletPoint,
  ProductSellingPoints,
} from "@/modules/k14/selling-points/types";

import type { GenerationJob } from "./api";
import { displayProductKey } from "./display";
import styles from "./ProductKnowledge.module.css";
import type { ProductKnowledgeDetail } from "./types";

/** 后台分阶段生成的进度话术。三步走完才允许提交。 */
const SELLING_POINTS_STAGE_LABEL: Record<string, string> = {
  bullets: "第 1/3 步：正在写卖点…（约 1 分钟，可以先去忙别的）",
  zh: "第 2/3 步：卖点已出，正在翻中文对照…",
  copy: "第 3/3 步：正在写商品页整段文案…",
};

function sellingPointsProgressPercent(
  sellingPoints: ProductSellingPoints | null,
  isGenerating: boolean,
  approved: boolean,
  hasManualDraft: boolean,
  stage?: string | null,
) {
  if (approved) {
    return 100;
  }
  // 生成中的进度按真实阶段推进,而不是过去那样一律停在 36%。
  if (isGenerating) {
    if (stage === "copy") {
      return 66;
    }
    if (stage === "zh") {
      return 52;
    }
    return 36;
  }
  if (sellingPoints || hasManualDraft) {
    return 72;
  }
  return 0;
}
function nextManualSellingPointId(bullets: BulletPoint[]) {
  const occupiedIds = new Set(
    bullets.map((bullet) => bullet.id).filter((id): id is string => Boolean(id)),
  );
  let ordinal = 1;
  while (occupiedIds.has(`manual_selling_point_${ordinal}`)) {
    ordinal += 1;
  }
  return `manual_selling_point_${ordinal}`;
}
function splitListText(value: string) {
  return value
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}
function joinListText(values: string[] | undefined) {
  return (values ?? []).join("\n");
}

type SellingPointsPanelProps = {
  product: ProductKnowledgeDetail;
  sellingPoints: ProductSellingPoints | null;
  sellingPointsStage: string | null;
  sellingPointsJob: GenerationJob | null;
  isGeneratingSellingPoints: boolean;
  /** 上层拿到的生成失败话术。面板不自己造这条错，它来自生成流程。 */
  sellingPointsError: string;
  onGenerateSellingPoints?: () => void;
  onApproveSellingPoints?: (
    sellingPoints: ProductSellingPoints,
  ) => void | Promise<void>;
  /** 「已批准」「改过了」是这一簇唯一的对外信号——P 系列就绪度靠它们算。 */
  onApprovedChange: (approved: boolean) => void;
  onTouchedChange: (touched: boolean) => void;
  complete: boolean;
  dirty: boolean;
};

export function SellingPointsPanel({
  product,
  sellingPoints,
  sellingPointsStage,
  sellingPointsJob,
  isGeneratingSellingPoints,
  sellingPointsError,
  onGenerateSellingPoints,
  onApproveSellingPoints,
  onApprovedChange,
  onTouchedChange,
  complete,
  dirty,
}: SellingPointsPanelProps) {
  const [sellingBullets, setSellingBullets] = useState<BulletPoint[]>([]);
  const [seoKeywordsText, setSeoKeywordsText] = useState("");
  const [marketTagsText, setMarketTagsText] = useState("");
  const [marketingCopy, setMarketingCopy] = useState("");
  const [translatedVersion, setTranslatedVersion] = useState("");
  const [chineseTranslation, setChineseTranslation] = useState("");
  const [targetLanguage, setTargetLanguage] = useState("");
  const [sellingPointReviewError, setSellingPointReviewError] = useState("");
  const [isSavingSellingPoints, setIsSavingSellingPoints] = useState(false);
  const [sellingPointsApproved, setSellingPointsApproved] = useState(false);
  const [sellingPointsTouched, setSellingPointsTouched] = useState(false);
  const [isEditingSellingPoints, setIsEditingSellingPoints] = useState(false);
  const [sellingPointsCopyStatus, setSellingPointsCopyStatus] = useState("");

  // 对外只报这两个信号，报的时机就是本地状态变的时机。
  useEffect(() => {
    onApprovedChange(sellingPointsApproved);
  }, [onApprovedChange, sellingPointsApproved]);
  useEffect(() => {
    onTouchedChange(sellingPointsTouched);
  }, [onTouchedChange, sellingPointsTouched]);

  const sellingPointsComplete = complete;
  const sellingPointsDirty = dirty;
  const hasSellingPointsDraft =
    Boolean(sellingPoints) || sellingBullets.length > 0;
  const sellingPointsJobFailed = sellingPointsJob?.status === "failed";
  const sellingPointsStageErrors = sellingPointsJob?.stage_errors ?? null;
  const sellingPointsStillRunning =
    isGeneratingSellingPoints && sellingPointsStage !== "done";

  const sellingPointsProgress = useMemo(
    () =>
      sellingPointsProgressPercent(
        sellingPoints,
        isGeneratingSellingPoints,
        sellingPointsApproved,
        sellingBullets.length > 0,
        sellingPointsStage,
      ),
    [
      isGeneratingSellingPoints,
      sellingBullets.length,
      sellingPoints,
      sellingPointsApproved,
      sellingPointsStage,
    ],
  );

  useEffect(() => {
    if (!sellingPoints) {
      setSellingBullets([]);
      setSeoKeywordsText("");
      setMarketTagsText("");
      setMarketingCopy("");
      setTranslatedVersion("");
      setChineseTranslation("");
      setTargetLanguage("");
      setSellingPointsApproved(false);
      setSellingPointsTouched(false);
      setSellingPointsCopyStatus("");
      return;
    }

    // 卖点生成改成后台分阶段推送后,这个 effect 会被反复触发(阶段 2 补中文、
    // 阶段 3 补文案各推一次)。运营已经在改的内容绝不能被后来的阶段冲掉
    // —— 阶段 1 一出结果就可以开始审,那正是我们鼓励的用法。
    if (sellingPointsTouched || isEditingSellingPoints) {
      return;
    }

    setSellingBullets(
      sellingPoints.bullets.map((bullet) => ({
        ...bullet,
        evidence: bullet.evidence ?? "",
        review_decision:
          bullet.review_decision ??
          (sellingPoints.source === "manual_review" ? "approve" : "candidate"),
        verification_status: bullet.verification_status ?? "unverified",
      })),
    );
    setSeoKeywordsText(joinListText(sellingPoints.seo_keywords));
    setMarketTagsText(joinListText(sellingPoints.market_tags));
    setMarketingCopy(sellingPoints.marketing_copy ?? "");
    setTranslatedVersion(sellingPoints.translated_version ?? "");
    setChineseTranslation(sellingPoints.chinese_translation ?? "");
    setTargetLanguage(sellingPoints.target_language ?? sellingPoints.language ?? "");
    setSellingPointsApproved(sellingPoints.source === "manual_review");
    setSellingPointsTouched(false);
    setSellingPointsCopyStatus("");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 故意不依赖
    // sellingPointsTouched / isEditingSellingPoints:它们只作为"别覆盖我"的
    // 闸门读一次。放进依赖会让运营一退出编辑就被上一轮数据回灌。
  }, [sellingPoints]);

  function updateBullet(index: number, patch: Partial<BulletPoint>) {
    setSellingPointsTouched(true);
    setSellingBullets((current) =>
      current.map((bullet, bulletIndex) =>
        bulletIndex === index ? { ...bullet, ...patch } : bullet,
      ),
    );
  }

  function addManualSellingPoint() {
    setSellingPointsTouched(true);
    setSellingPointsApproved(false);
    setSellingPointReviewError("");
    setIsEditingSellingPoints(true);
    setSellingBullets((current) => [
      ...current,
      {
        category: "benefit",
        evidence: "operator_fact",
        evidence_excerpt: "",
        id: nextManualSellingPointId(current),
        importance_score: 1,
        review_decision: "approve",
        text: "",
        verification_status: "unverified",
      },
    ]);
  }

  function removeSellingPoint(index: number) {
    setSellingPointsTouched(true);
    setSellingPointsApproved(false);
    setSellingPointReviewError("");
    setSellingBullets((current) =>
      current.filter((_, bulletIndex) => bulletIndex !== index),
    );
  }

  async function submitSellingPointsReview() {
    if (sellingBullets.length === 0) {
      setSellingPointReviewError("请至少新增一条卖点，再进行人工审核。");
      return;
    }
    const cleanedBullets = sellingBullets
      .map((bullet) => ({
        ...bullet,
        category: bullet.category.trim() || "conversion",
        importance_score: Number.isFinite(Number(bullet.importance_score))
          ? Number(bullet.importance_score)
          : 1,
        text: bullet.text.trim(),
        evidence: bullet.evidence?.trim() || null,
        evidence_excerpt:
          bullet.evidence_excerpt?.trim() ||
          (bullet.evidence?.trim() === "operator_fact" ? bullet.text.trim() : null),
        review_decision: bullet.review_decision ?? "candidate",
      }))
      .filter((bullet) => bullet.text.length > 0);
    if (cleanedBullets.length === 0) {
      setSellingPointReviewError("请至少保留一条卖点。");
      return;
    }
    const undecided = cleanedBullets.filter(
      (bullet) => (bullet.review_decision ?? "candidate") === "candidate",
    );
    if (undecided.length > 0) {
      setSellingPointReviewError("请逐条选择通过、编辑后通过或拒绝。");
      return;
    }
    const missingEvidence = cleanedBullets.filter(
      (bullet) =>
        bullet.review_decision !== "reject" && !bullet.evidence?.trim(),
    );
    if (missingEvidence.length > 0) {
      setSellingPointReviewError(
        "保留的每条卖点都必须填写 spec:<字段>、verified_feature:<ID> 或 operator_fact 证据。",
      );
      return;
    }

    setIsSavingSellingPoints(true);
    setSellingPointReviewError("");
    try {
      const baseSellingPoints: ProductSellingPoints = sellingPoints ?? {
        bullets: [],
        confidence_score: 1,
        language: targetLanguage.trim() || "en",
        market_tags: [],
        product_id: product.id,
        raw_input: "",
        seo_bullets: [],
        seo_keywords: [],
        source: "manual_input",
        title:
          product.product_name_en ??
          displayProductKey(product.product_key),
      };
      await onApproveSellingPoints?.({
        ...baseSellingPoints,
        bullets: cleanedBullets,
        confidence_score: baseSellingPoints.confidence_score ?? 1,
        chinese_translation: chineseTranslation.trim() || null,
        language: baseSellingPoints.language ?? (targetLanguage || "en"),
        market_tags: splitListText(marketTagsText),
        marketing_copy: marketingCopy.trim() || null,
        product_id: baseSellingPoints.product_id ?? product.id,
        raw_input: baseSellingPoints.raw_input ?? "",
        seo_bullets: baseSellingPoints.seo_bullets ?? [],
        seo_keywords: splitListText(seoKeywordsText),
        source: "manual_review",
        target_language:
          targetLanguage.trim() || baseSellingPoints.target_language,
        title:
          baseSellingPoints.title ??
          product.product_name_en ??
          displayProductKey(product.product_key),
        translated_version: translatedVersion.trim() || null,
      });
      setSellingPointsApproved(true);
      setSellingPointsTouched(false);
    } catch (error) {
      setSellingPointReviewError(
        error instanceof Error ? error.message : "卖点审核保存失败。",
      );
    } finally {
      setIsSavingSellingPoints(false);
    }
  }

  function buildSellingPointsCopyText() {
    const lines = [
      product.product_name_en ||
        displayProductKey(product.product_key),
      "",
      "卖点",
      ...sellingBullets.map((bullet, index) => {
        const category = bullet.category.trim() || "conversion";
        return `${index + 1}. [${category}] ${bullet.text.trim()}`;
      }),
      "",
      "SEO关键词",
      ...splitListText(seoKeywordsText).map((keyword) => `- ${keyword}`),
      "",
      "市场标签",
      ...splitListText(marketTagsText).map((tag) => `- ${tag}`),
      "",
      "转化文案",
      marketingCopy.trim(),
      "",
      "目标市场译文",
      translatedVersion.trim(),
      "",
      "中文翻译",
      chineseTranslation.trim(),
    ];

    return lines
      .filter((line, index, allLines) => {
        if (line.trim()) {
          return true;
        }
        return index > 0 && index < allLines.length - 1;
      })
      .join("\n");
  }

  async function copySellingPoints() {
    const text = buildSellingPointsCopyText();
    if (!text.trim()) {
      return;
    }

    try {
      await navigator.clipboard.writeText(text);
      setSellingPointsCopyStatus("已复制");
    } catch {
      setSellingPointsCopyStatus("复制失败");
    }
  }


  return (
      <section
        aria-labelledby="k-selling-points"
        className={styles.sellingPointsSection}
      >
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>卖点</span>
            <h4 id="k-selling-points">卖点整理</h4>
          </div>
          <div className={styles.headingActions}>
            {hasSellingPointsDraft ? (
              <button
                className="secondary-button"
                onClick={() => void copySellingPoints()}
                title="复制当前卖点"
                type="button"
              >
                <Copy aria-hidden="true" size={16} />
                {sellingPointsCopyStatus || "复制"}
              </button>
            ) : null}
            <button
              className="secondary-button"
              onClick={addManualSellingPoint}
              type="button"
            >
              <Plus aria-hidden="true" size={16} />
              新增手工卖点
            </button>
            <button
              className="secondary-button"
              disabled={isGeneratingSellingPoints}
              onClick={() => {
                // 必须清掉这两个闸门:上面那个同步 effect 靠它们判断
                // 「运营正在改,别覆盖」。点了重新生成就是要新结果,
                // 不清的话三个阶段推回来的数据一条都进不来。
                setSellingPointsTouched(false);
                setSellingPointsApproved(false);
                setIsEditingSellingPoints(false);
                onGenerateSellingPoints?.();
              }}
              type="button"
            >
              {isGeneratingSellingPoints ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <Sparkles aria-hidden="true" size={16} />
              )}
              {isGeneratingSellingPoints
                ? "后台生成中…"
                : sellingPoints
                  ? "重新生成"
                  : "生成"}
            </button>
          </div>
        </div>

        <div className={styles.workflowMetrics}>
          <div>
            <dt>进度</dt>
            <dd>{sellingPointsProgress}%</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>
              {sellingPointsComplete
                ? "已保存"
                : sellingPointsDirty
                  ? "已修改，待重新提交"
                  : "待审核"}
            </dd>
          </div>
        </div>
        <div
          aria-label="卖点进度"
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={sellingPointsProgress}
          className={styles.workflowProgress}
          role="progressbar"
        >
          <span style={{ width: `${sellingPointsProgress}%` }} />
        </div>

        {sellingPointsError ? (
          <p className={styles.sellingPointsError}>{sellingPointsError}</p>
        ) : null}
        {sellingPointReviewError ? (
          <p className={styles.sellingPointsError}>{sellingPointReviewError}</p>
        ) : null}
        {sellingPointsJobFailed ? (
          <p className={styles.sellingPointsError}>
            卖点生成失败：{sellingPointsJob?.error || "未知原因"}。可以点「重新生成」再试一次。
          </p>
        ) : null}

        {isGeneratingSellingPoints ? (
          <p className={styles.copyReviewHint}>
            {(sellingPointsStage &&
              SELLING_POINTS_STAGE_LABEL[sellingPointsStage]) ||
              "已排进后台队列，正在启动…"}
            {hasSellingPointsDraft
              ? " 下面已经出来的部分可以先看、先改。"
              : " 你可以先去忙别的，好了这里会自动显示。"}
          </p>
        ) : null}

        {/* 增强阶段失败不遮挡已到手的卖点 —— 卖点本体是阶段 1 出的，
            中文/文案没补上不影响它可用。 */}
        {sellingPointsStageErrors?.zh ? (
          <p className={styles.copyReviewHint}>
            中文对照没翻出来（{sellingPointsStageErrors.zh}）。卖点本身不受影响，
            想要中文可以点「重新生成」。
          </p>
        ) : null}
        {sellingPointsStageErrors?.copy ? (
          <p className={styles.copyReviewHint}>
            商品页整段文案没生成出来（{sellingPointsStageErrors.copy}）。
            卖点与中文对照不受影响。
          </p>
        ) : null}

        {hasSellingPointsDraft && !isEditingSellingPoints ? (
          <div className={styles.sellingPointsResult}>
            {/* ---- 阅读模式：整洁展示，点「编辑」才出输入框 ---- */}
            <div className={styles.spReadHead}>
              <div className={styles.spChips}>
                <span className={styles.spMetaChip}>语言 {targetLanguage || "—"}</span>
                {seoKeywordsText
                  .split(/[,，\n]/)
                  .map((keyword) => keyword.trim())
                  .filter(Boolean)
                  .slice(0, 12)
                  .map((keyword) => (
                    <span className={styles.spKeywordChip} key={keyword}>
                      {keyword}
                    </span>
                  ))}
                {marketTagsText
                  .split(/[,，\n]/)
                  .map((tag) => tag.trim())
                  .filter(Boolean)
                  .slice(0, 8)
                  .map((tag) => (
                    <span className={styles.spTagChip} key={tag}>
                      {tag}
                    </span>
                  ))}
              </div>
              <button
                className="secondary-button"
                onClick={() => setIsEditingSellingPoints(true)}
                type="button"
              >
                <Pencil aria-hidden="true" size={15} />
                编辑
              </button>
            </div>

            <ol className={styles.spReadList}>
              {sellingBullets.map((bullet, index) => (
                <li
                  className={styles.spReadCard}
                  key={bullet.id || `${index}-${bullet.category}`}
                >
                  <div className={styles.spReadCardTop}>
                    <span className={styles.spCategoryBadge}>
                      {bullet.category || "卖点"}
                    </span>
                    <span
                      className={styles.spScoreBadge}
                      title="重要度"
                    >
                      ★ {Number(bullet.importance_score ?? 0).toFixed(1)}
                    </span>
                  </div>
                  <div className={styles.spBilingualRow}>
                    <p>{bullet.text}</p>
                    {bullet.text_zh ? (
                      <p className={styles.spZhText}>{bullet.text_zh}</p>
                    ) : null}
                  </div>
                  <small>
                    证据：{bullet.evidence || "未提供"} · {bullet.verification_status === "verified" ? "已核验" : "待核验"}
                  </small>
                </li>
              ))}
            </ol>

            {chineseTranslation ? (
              <details className={styles.spFold} open>
                <summary>中文翻译（供你审核）</summary>
                <p>{chineseTranslation}</p>
              </details>
            ) : null}
            {marketingCopy ? (
              <details className={styles.spFold}>
                <summary>转化文案</summary>
                <p>{marketingCopy}</p>
              </details>
            ) : null}
            {translatedVersion ? (
              <details className={styles.spFold}>
                <summary>目标市场译文</summary>
                <p>{translatedVersion}</p>
              </details>
            ) : null}
          </div>
        ) : null}

        {hasSellingPointsDraft && isEditingSellingPoints ? (
          <div className={styles.sellingPointsResult}>
            <div className={styles.spEditBar}>
              <span>编辑模式 —— 改完点「完成编辑」回到清爽视图，再提交卖点。</span>
              <button
                className="secondary-button"
                onClick={() => setIsEditingSellingPoints(false)}
                type="button"
              >
                <CheckCircle2 aria-hidden="true" size={15} />
                完成编辑
              </button>
            </div>
            <div className={styles.sellingPointEditorGrid}>
              <label className={styles.field}>
                <span>目标语言</span>
                <input
                  onChange={(event) => {
                    setSellingPointsTouched(true);
                    setTargetLanguage(event.target.value);
                  }}
                  value={targetLanguage}
                />
              </label>
              <label className={styles.field}>
                <span>SEO关键词</span>
                <textarea
                  onChange={(event) => {
                    setSellingPointsTouched(true);
                    setSeoKeywordsText(event.target.value);
                  }}
                  rows={3}
                  value={seoKeywordsText}
                />
              </label>
              <label className={styles.field}>
                <span>市场标签</span>
                <textarea
                  onChange={(event) => {
                    setSellingPointsTouched(true);
                    setMarketTagsText(event.target.value);
                  }}
                  rows={3}
                  value={marketTagsText}
                />
              </label>
            </div>

            <ul className={styles.sellingPointBullets}>
              {sellingBullets.map((bullet, index) => (
                <li
                  className={styles.spEditRow}
                  key={bullet.id || `${index}-${bullet.category}`}
                >
                  <div className={styles.spRowHead}>
                    <span className={styles.spRowOrdinal}>{index + 1}</span>
                    <label className={styles.field}>
                      <span>类别</span>
                      <input
                        aria-label="卖点类别"
                        onChange={(event) =>
                          updateBullet(index, { category: event.target.value })
                        }
                        value={bullet.category}
                      />
                    </label>
                    <label className={`${styles.field} ${styles.spRowScore}`}>
                      <span>重要度</span>
                      <input
                        aria-label="重要度"
                        min={0}
                        onChange={(event) =>
                          updateBullet(index, {
                            importance_score: Number(event.target.value),
                          })
                        }
                        step={0.1}
                        type="number"
                        value={bullet.importance_score}
                      />
                    </label>
                    <label className={`${styles.field} ${styles.spRowDecision}`}>
                      <span>逐条决定</span>
                      <select
                        aria-label="卖点审核决定"
                        onChange={(event) =>
                          updateBullet(index, {
                            review_decision: event.target.value as BulletPoint["review_decision"],
                          })
                        }
                        value={bullet.review_decision ?? "candidate"}
                      >
                        <option value="candidate">待决定</option>
                        <option value="approve">通过</option>
                        <option value="edit">编辑后通过</option>
                        <option value="reject">拒绝</option>
                      </select>
                    </label>
                    <button
                      className={`secondary-button ${styles.spRowDelete}`}
                      onClick={() => removeSellingPoint(index)}
                      type="button"
                    >
                      <Trash2 aria-hidden="true" size={15} />
                      删除
                    </button>
                  </div>

                  <label className={styles.field}>
                    <span>卖点文案</span>
                    <textarea
                      aria-label="卖点文案"
                      onChange={(event) =>
                        updateBullet(index, { text: event.target.value })
                      }
                      rows={2}
                      value={bullet.text}
                    />
                  </label>

                  {bullet.text_zh ? (
                    <p className={styles.spZhLine}>
                      <span>中文对照</span>
                      {bullet.text_zh}
                    </p>
                  ) : null}

                  <label className={styles.field}>
                    <span>证据</span>
                    <input
                      aria-label="卖点证据"
                      onChange={(event) =>
                        updateBullet(index, {
                          evidence: event.target.value,
                          verification_status: "unverified",
                        })
                      }
                      placeholder="spec:material / verified_feature:ID / operator_fact"
                      value={bullet.evidence ?? ""}
                    />
                  </label>
                </li>
              ))}
            </ul>

            <label className={styles.field}>
              <span>转化文案</span>
              <textarea
                onChange={(event) => {
                  setSellingPointsTouched(true);
                  setMarketingCopy(event.target.value);
                }}
                rows={4}
                value={marketingCopy}
              />
            </label>
            <label className={styles.field}>
              <span>目标市场译文</span>
              <textarea
                onChange={(event) => {
                  setSellingPointsTouched(true);
                  setTranslatedVersion(event.target.value);
                }}
                rows={4}
                value={translatedVersion}
              />
            </label>
            <label className={styles.field}>
              <span>中文翻译</span>
              <textarea
                onChange={(event) => {
                  setSellingPointsTouched(true);
                  setChineseTranslation(event.target.value);
                }}
                rows={5}
                value={chineseTranslation}
              />
            </label>
          </div>
        ) : null}

        {!hasSellingPointsDraft ? (
          <p className={styles.sellingPointsEmpty}>
            可直接新增手工卖点，或点击生成后逐条审核 AI 候选。
          </p>
        ) : null}

        {sellingPointReviewError ? (
          <p className={styles.sellingPointsError} role="alert">
            {sellingPointReviewError}
          </p>
        ) : null}
        <div className={styles.sectionFooter}>
          <span data-complete={sellingPointsComplete}>
            {sellingPointsStillRunning
              ? "生成中，三步走完才能提交"
              : sellingPointsComplete
                ? "卖点已保存"
                : sellingPointsDirty
                  ? "卖点已修改，待重新提交"
                  : "卖点待审核"}
          </span>
          <button
            className="primary-button"
            disabled={
              sellingBullets.length === 0 ||
              isSavingSellingPoints ||
              // 生成没走完不许提交:提交会把当前内容冻结成已审版本并清空
              // 已生成的文案/作图指令,此时中文和商品页文案还没补上。
              // 编辑不受此限 —— 阶段 1 出结果就能改。
              sellingPointsStillRunning
            }
            onClick={() => void submitSellingPointsReview()}
            title={
              sellingPointsStillRunning
                ? "等三步走完再提交（现在就可以先改）"
                : undefined
            }
            type="button"
          >
            {isSavingSellingPoints ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <CheckCircle2 aria-hidden="true" size={16} />
            )}
            提交卖点
          </button>
        </div>
      </section>
  );
}

"use client";

import {
  CheckCircle2,
  ImagePlay,
  LoaderCircle,
  RotateCcw,
  Save,
  Wand2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  getRenderAssets,
  getRenderJobs,
  mediaAssetPreviewUrl,
  mediaAssetThumbnailUrl,
  renderProductImages,
  retryRenderJobs,
  reworkRenderAsset,
  saveRenderAssets,
  type RenderAsset,
  type RenderJobsResult,
} from "./api";
import styles from "./ProductKnowledge.module.css";

type RenderImagesPanelProps = {
  productId: string;
  hasBrief: boolean;
};

const POLL_MS = 5000;

function isActive(result: RenderJobsResult | null) {
  if (!result) {
    return false;
  }
  return result.summary.pending > 0 || result.summary.running > 0;
}

function placementLabel(placement: string) {
  return placement === "description" ? "描述图" : "图库图";
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function RenderImagesPanel({ productId, hasBrief }: RenderImagesPanelProps) {
  const [jobs, setJobs] = useState<RenderJobsResult | null>(null);
  const [assets, setAssets] = useState<RenderAsset[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [previewAsset, setPreviewAsset] = useState<RenderAsset | null>(null);
  const [reworkAsset, setReworkAsset] = useState<RenderAsset | null>(null);
  const [reworkPrompt, setReworkPrompt] = useState("");
  const [reworkUseCurrent, setReworkUseCurrent] = useState(true);

  const mounted = useRef(true);
  const timer = useRef<number | null>(null);

  const clearTimer = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  const poll = useCallback(async () => {
    if (!mounted.current) {
      return;
    }
    try {
      const [jobsData, assetsData] = await Promise.all([
        getRenderJobs(productId),
        getRenderAssets(productId),
      ]);
      if (!mounted.current) {
        return;
      }
      setJobs(jobsData);
      setAssets(assetsData);
      if (isActive(jobsData)) {
        clearTimer();
        timer.current = window.setTimeout(() => void poll(), POLL_MS);
      }
    } catch (pollError) {
      if (mounted.current) {
        setError(errorMessage(pollError, "查询作图进度失败。"));
      }
    }
  }, [productId, clearTimer]);

  useEffect(() => {
    mounted.current = true;
    void poll();
    return () => {
      mounted.current = false;
      clearTimer();
    };
  }, [poll, clearTimer]);

  const runAction = useCallback(
    async (action: () => Promise<unknown>, failText: string) => {
      setBusy(true);
      setError(null);
      setNotice(null);
      try {
        await action();
        await poll();
        return true;
      } catch (actionError) {
        setError(errorMessage(actionError, failText));
        return false;
      } finally {
        if (mounted.current) {
          setBusy(false);
        }
      }
    },
    [poll],
  );

  const handleRenderAll = () =>
    runAction(() => renderProductImages(productId), "提交作图任务失败，请重试。");

  const handleRetry = () => {
    if (!jobs?.batch_id) {
      return;
    }
    void runAction(
      () => retryRenderJobs(productId, jobs.batch_id as string),
      "重试失败，请稍后再试。",
    );
  };

  const handleSave = (assetIds?: string[]) =>
    runAction(async () => {
      await saveRenderAssets(productId, assetIds);
      setNotice(
        assetIds
          ? "已保存该图（同位置旧图已替换），品牌审查已自动排队。"
          : "已全部保存，品牌审查已自动排队。",
      );
      setPreviewAsset(null);
    }, "保存失败，请重试。");

  const submitRework = () => {
    if (!reworkAsset) {
      return;
    }
    const target = reworkAsset;
    void runAction(async () => {
      await reworkRenderAsset(productId, {
        asset_id: target.asset_id,
        extra_prompt: reworkPrompt,
        use_current_as_reference: reworkUseCurrent,
      });
      setNotice(
        `第 ${target.position} 张已排队重做（${
          reworkUseCurrent ? "以这版图为基础修改" : "按原始参考图重新生成"
        }）。新图完成后出现在暂存区，满意再保存。`,
      );
      setReworkAsset(null);
      setReworkPrompt("");
      setPreviewAsset(null);
    }, "重做提交失败，请重试。");
  };

  const active = isActive(jobs);
  const summary = jobs?.summary;
  const stagedAssets = assets.filter((asset) => asset.status === "staged");
  const runningPositions = new Set(
    (jobs?.jobs ?? [])
      .filter((job) => job.status === "pending" || job.status === "running")
      .map((job) => job.position),
  );
  const failedJobs = (jobs?.jobs ?? []).filter((job) => job.status === "failed");

  return (
    <section className={styles.sellingPointsSection} aria-labelledby="k-render">
      <div className={styles.sellingPointsHeading}>
        <div>
          <span className={styles.eyebrow}>成品图</span>
          <h4 id="k-render">一次性作图 · 预览满意再保存</h4>
        </div>
        <div className={styles.headingActions}>
          {stagedAssets.length > 0 && !active ? (
            <button
              className="primary-button"
              disabled={busy}
              onClick={() => void handleSave()}
              type="button"
            >
              <Save aria-hidden="true" size={16} />
              全部保存（{stagedAssets.length}）
            </button>
          ) : null}
          {failedJobs.length > 0 && !active ? (
            <button
              className="secondary-button"
              disabled={busy}
              onClick={handleRetry}
              type="button"
            >
              <RotateCcw aria-hidden="true" size={16} />
              重试失败的 {failedJobs.length} 张
            </button>
          ) : null}
          <button
            className="secondary-button"
            disabled={busy || active || !hasBrief}
            onClick={() => void handleRenderAll()}
            title={hasBrief ? "按作图指令一次性生成全部成品图" : "请先生成作图指令"}
            type="button"
          >
            {busy || active ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <ImagePlay aria-hidden="true" size={16} />
            )}
            {active ? "作图中…" : assets.length ? "重新一次性作图" : "一次性作图"}
          </button>
        </div>
      </div>

      {error ? <p className={styles.sellingPointsError}>{error}</p> : null}
      {notice ? <p className={styles.copyReviewHint}>{notice}</p> : null}

      {active && summary ? (
        <p className={styles.copyReviewHint}>
          AI 正在按指令逐张作图（
          {summary.completed + summary.failed}/{summary.total} 张完成）——
          完成的图先进暂存区，点开预览满意再保存。
        </p>
      ) : null}

      {assets.length === 0 && !active ? (
        <p className={styles.copyReviewHint}>
          有了作图指令后点「一次性作图」：生成的图先进<strong>暂存区</strong>
          （挂 24 小时），逐张预览，满意的点「保存」才正式入库 ——
          没保存的图不参与品牌审查和上架。
        </p>
      ) : null}

      {assets.length > 0 || runningPositions.size > 0 ? (
        <ul className={styles.renderGrid}>
          {assets.map((asset) => (
            <li
              className={`${styles.renderCard}${
                asset.status === "staged" ? ` ${styles.renderCardStaged}` : ""
              }`}
              key={asset.asset_id}
            >
              <button
                className={styles.renderThumbButton}
                onClick={() => setPreviewAsset(asset)}
                title="点击看大图"
                type="button"
              >
                <img
                  alt={`第 ${asset.position} 张`}
                  decoding="async"
                  loading="lazy"
                  src={mediaAssetThumbnailUrl(asset.asset_id)}
                />
              </button>
              <div className={styles.renderMeta}>
                <strong>
                  #{asset.position} {asset.role_label || placementLabel(asset.placement)}
                </strong>
                <span>
                  {placementLabel(asset.placement)}
                  {asset.asset_role === "main" ? " · 主图" : ""}
                </span>
                <span
                  className={styles.renderStateBadge}
                  data-state={asset.status}
                >
                  {asset.status === "staged" ? "暂存 · 待保存" : "已保存"}
                </span>
                {asset.status === "staged" ? (
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => void handleSave([asset.asset_id])}
                    type="button"
                  >
                    <Save aria-hidden="true" size={13} />
                    保存
                  </button>
                ) : null}
              </div>
            </li>
          ))}
          {[...runningPositions]
            .filter(
              (position) => !assets.some((asset) => asset.position === position),
            )
            .sort((a, b) => a - b)
            .map((position) => (
              <li className={styles.renderCard} key={`run-${position}`}>
                <div className={styles.renderThumb}>
                  <LoaderCircle aria-hidden="true" className="spin" size={20} />
                </div>
                <div className={styles.renderMeta}>
                  <strong>#{position}</strong>
                  <span>生成中…</span>
                </div>
              </li>
            ))}
        </ul>
      ) : null}

      {failedJobs.length > 0 ? (
        <ul className={styles.copyReviewHint} style={{ margin: 0, paddingLeft: 18 }}>
          {failedJobs.map((job) => (
            <li key={job.job_id}>
              第 {job.position} 张失败：{job.error || "未知错误"}
            </li>
          ))}
        </ul>
      ) : null}

      {/* ---- 大图预览弹层 ---- */}
      {previewAsset ? (
        <div
          className={styles.renderLightbox}
          onMouseDown={() => setPreviewAsset(null)}
          role="presentation"
        >
          <div
            className={styles.renderLightboxInner}
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
            aria-label={`第 ${previewAsset.position} 张预览`}
          >
            <div className={styles.renderLightboxHead}>
              <strong>
                #{previewAsset.position}{" "}
                {previewAsset.role_label || placementLabel(previewAsset.placement)}
                <span
                  className={styles.renderStateBadge}
                  data-state={previewAsset.status}
                  style={{ marginLeft: 10 }}
                >
                  {previewAsset.status === "staged" ? "暂存 · 待保存" : "已保存"}
                </span>
              </strong>
              <button
                aria-label="关闭预览"
                className="secondary-button"
                onClick={() => setPreviewAsset(null)}
                type="button"
              >
                <X aria-hidden="true" size={16} />
              </button>
            </div>
            <img
              alt={`第 ${previewAsset.position} 张大图`}
              className={styles.renderLightboxImg}
              src={mediaAssetPreviewUrl(previewAsset.asset_id)}
            />
            <div className={styles.renderLightboxActions}>
              {previewAsset.status === "staged" ? (
                <button
                  className="primary-button"
                  disabled={busy}
                  onClick={() => void handleSave([previewAsset.asset_id])}
                  type="button"
                >
                  <CheckCircle2 aria-hidden="true" size={15} />
                  保存这张
                </button>
              ) : null}
              <button
                className="secondary-button"
                disabled={busy}
                onClick={() => {
                  setReworkAsset(previewAsset);
                  setReworkPrompt("");
                  setReworkUseCurrent(true);
                }}
                type="button"
              >
                <Wand2 aria-hidden="true" size={15} />
                不满意，重做
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* ---- 重做弹窗 ---- */}
      {reworkAsset ? (
        <div
          className={styles.renderLightbox}
          onMouseDown={() => setReworkAsset(null)}
          role="presentation"
        >
          <div
            className={styles.renderReworkModal}
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
            aria-label="重做这张图"
          >
            <div className={styles.renderLightboxHead}>
              <strong>重做第 {reworkAsset.position} 张</strong>
              <button
                aria-label="取消重做"
                className="secondary-button"
                onClick={() => setReworkAsset(null)}
                type="button"
              >
                <X aria-hidden="true" size={16} />
              </button>
            </div>
            <label className={styles.field}>
              <span>
                这张图的临时修改要求（不改动原作图指令；与原指令冲突时以这里为准）
              </span>
              <textarea
                onChange={(event) => setReworkPrompt(event.target.value)}
                placeholder="例：再加两只小猫，一只在抢篮板"
                rows={4}
                value={reworkPrompt}
              />
            </label>
            <div className={styles.renderReworkChoices}>
              <label>
                <input
                  checked={reworkUseCurrent}
                  name="rework-ref"
                  onChange={() => setReworkUseCurrent(true)}
                  type="radio"
                />
                <span>
                  <strong>以这版图为基础修改</strong> ——
                  保留当前构图和内容，只应用上面的修改要求
                </span>
              </label>
              <label>
                <input
                  checked={!reworkUseCurrent}
                  name="rework-ref"
                  onChange={() => setReworkUseCurrent(false)}
                  type="radio"
                />
                <span>
                  <strong>不保留这版，重新生成</strong> ——
                  用原始参考图 + 原指令 + 修改要求整合重画
                </span>
              </label>
            </div>
            <div className={styles.renderLightboxActions}>
              <button
                className="primary-button"
                disabled={busy || !reworkPrompt.trim()}
                onClick={submitRework}
                type="button"
              >
                {busy ? (
                  <LoaderCircle aria-hidden="true" className="spin" size={15} />
                ) : (
                  <Wand2 aria-hidden="true" size={15} />
                )}
                提交重做
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

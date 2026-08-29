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
  addBriefImage,
  applyBriefOverlay,
  getOverlayFields,
  getProduct,
  getRenderAssets,
  getRenderJobs,
  mediaAssetPreviewUrl,
  mediaAssetThumbnailUrl,
  renderProductImages,
  retryRenderJobs,
  reworkRenderAsset,
  saveRenderAssets,
  uploadProductMediaAsset,
  type OverlayFieldOption,
  type RenderAsset,
  type RenderJobsResult,
} from "./api";
import styles from "./ProductKnowledge.module.css";

type RenderImagesPanelProps = {
  productId: string;
  hasBrief: boolean;
  /** 保存成功后通知上层重拉图片绑定等数据（详情页图片板块靠它刷新）。 */
  onSaved?: () => void;
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

export function RenderImagesPanel({ productId, hasBrief, onSaved }: RenderImagesPanelProps) {
  const [jobs, setJobs] = useState<RenderJobsResult | null>(null);
  const [assets, setAssets] = useState<RenderAsset[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [previewAsset, setPreviewAsset] = useState<RenderAsset | null>(null);
  const [reworkAsset, setReworkAsset] = useState<RenderAsset | null>(null);
  const [reworkPrompt, setReworkPrompt] = useState("");
  const [reworkUseCurrent, setReworkUseCurrent] = useState(true);
  const [reworkReferenceUrl, setReworkReferenceUrl] = useState("");
  const [reworkReferenceAssetId, setReworkReferenceAssetId] = useState<string | null>(
    null,
  );
  const [reworkReferenceName, setReworkReferenceName] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [addScene, setAddScene] = useState("");
  const [addPlacement, setAddPlacement] = useState<"gallery" | "description">(
    "gallery",
  );
  const [addReferenceUrl, setAddReferenceUrl] = useState("");
  const [addReferenceAssetId, setAddReferenceAssetId] = useState<string | null>(null);
  const [addReferenceName, setAddReferenceName] = useState("");
  const [uploadingRef, setUploadingRef] = useState(false);

  // 上传本地文件作为参考图 → 返回 reference 资产 id(参考图是产品级,任取一个变体挂载)
  const uploadReferenceFile = async (file: File): Promise<string> => {
    const detail = await getProduct(productId);
    const variantSku =
      (detail as { variants?: { variant_sku?: string | null }[] }).variants?.find(
        (v) => v.variant_sku,
      )?.variant_sku ?? null;
    if (!variantSku) {
      throw new Error("产品没有可挂载的变体,无法上传参考图。");
    }
    const asset = await uploadProductMediaAsset(productId, file, variantSku, "reference");
    return asset.id;
  };
  const [overlayAsset, setOverlayAsset] = useState<RenderAsset | null>(null);
  const [overlayFields, setOverlayFields] = useState<OverlayFieldOption[]>([]);
  const [overlayPicked, setOverlayPicked] = useState<string[]>([]);

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
      onSaved?.();
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
        reference_image_url: reworkReferenceUrl.trim() || null,
        reference_asset_id: reworkReferenceAssetId,
      });
      setNotice(
        `第 ${target.position} 张已排队重做（${
          reworkUseCurrent ? "以这版图为基础修改" : "按原始参考图重新生成"
        }）。新图完成后出现在暂存区，满意再保存。`,
      );
      setReworkAsset(null);
      setReworkPrompt("");
      setReworkReferenceUrl("");
      setReworkReferenceAssetId(null);
      setReworkReferenceName("");
      setPreviewAsset(null);
    }, "重做提交失败，请重试。");
  };

  const submitAddImage = () => {
    void runAction(async () => {
      await addBriefImage(productId, {
        scene: addScene.trim(),
        placement: addPlacement,
        reference_image_url: addReferenceUrl.trim() || null,
        reference_asset_id: addReferenceAssetId,
      });
      setNotice(
        `已把这张图追加进作图方案（${
          addPlacement === "gallery" ? "轮播图库" : "描述内嵌"
        }）并排队渲染，SEO 字段已自动生成。`,
      );
      setAddOpen(false);
      setAddScene("");
      setAddReferenceUrl("");
      setAddReferenceAssetId(null);
      setAddReferenceName("");
    }, "新增图片失败，请重试。");
  };

  const handleReferenceFilePick = async (
    file: File | undefined,
    which: "rework" | "add",
  ) => {
    if (!file) {
      return;
    }
    setUploadingRef(true);
    setError(null);
    try {
      const assetId = await uploadReferenceFile(file);
      if (which === "rework") {
        setReworkReferenceAssetId(assetId);
        setReworkReferenceName(file.name);
      } else {
        setAddReferenceAssetId(assetId);
        setAddReferenceName(file.name);
      }
    } catch (uploadError) {
      setError(errorMessage(uploadError, "参考图上传失败，请重试。"));
    } finally {
      setUploadingRef(false);
    }
  };

  const openOverlayDialog = (asset: RenderAsset) => {
    setOverlayAsset(asset);
    setOverlayPicked([]);
    setOverlayFields([]);
    void getOverlayFields(productId)
      .then((fields) => setOverlayFields(fields))
      .catch(() => setOverlayFields([]));
  };

  const toggleOverlayField = (field: string) => {
    setOverlayPicked((current) =>
      current.includes(field)
        ? current.filter((item) => item !== field)
        : current.length >= 4
          ? current
          : [...current, field],
    );
  };

  const submitOverlay = () => {
    if (!overlayAsset) {
      return;
    }
    const target = overlayAsset;
    void runAction(async () => {
      await applyBriefOverlay(productId, target.position, overlayPicked);
      setNotice(
        `第 ${target.position} 张已按所选规格重排渲染——真实数值由系统精确画上图。`,
      );
      setOverlayAsset(null);
      setPreviewAsset(null);
    }, "加标注失败，请重试。");
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
            onClick={() => {
              setAddReferenceAssetId(null);
              setAddReferenceName("");
              setAddOpen(true);
            }}
            title={
              hasBrief
                ? "在 AI 方案之外追加一张图（可贴专属参考图，手选放轮播还是描述）"
                : "请先生成作图指令"
            }
            type="button"
          >
            <ImagePlay aria-hidden="true" size={16} />
            添加图片
          </button>
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
                {asset.variant_color ? (
                  <span
                    style={{
                      display: "inline-block",
                      background: "rgba(231,161,44,0.16)",
                      color: "#b26a00",
                      borderRadius: 6,
                      padding: "1px 7px",
                      fontSize: "0.74rem",
                      fontWeight: 600,
                      width: "fit-content",
                    }}
                  >
                    🎨 {asset.variant_color} 专属主图
                  </span>
                ) : null}
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
                {asset.submitted_via === "mcp" ? (
                  <span
                    className={styles.renderStateBadge}
                    data-state="external"
                    title={`外部精修通道交回的稿(${asset.submitted_by ?? "外部代理"} 经 Codex/MCP 提交),已过同一套审查`}
                  >
                    ✦ {asset.submitted_by ? `${asset.submitted_by} · ` : ""}Codex 精修
                  </span>
                ) : null}
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
                  setReworkReferenceUrl("");
                  setReworkReferenceAssetId(null);
                  setReworkReferenceName("");
                  setReworkUseCurrent(true);
                }}
                type="button"
              >
                <Wand2 aria-hidden="true" size={15} />
                不满意，重做
              </button>
              {previewAsset.asset_role !== "main" ? (
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => openOverlayDialog(previewAsset)}
                  title="从已核实规格里挑几条，系统把真实数值精确画上图（亚马逊风信息图）"
                  type="button"
                >
                  <CheckCircle2 aria-hidden="true" size={15} />
                  加标注
                </button>
              ) : null}
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
            <label className={styles.field}>
              <span>
                专属参考图链接（可选）——贴了就以它为最高优先参考，适合“这张图想换个实物/角度”的场景
              </span>
              <input
                inputMode="url"
                onChange={(event) => setReworkReferenceUrl(event.target.value)}
                placeholder="贴图片链接（1688/Amazon 等）；或用下面「上传本地图」"
                value={reworkReferenceUrl}
              />
            </label>
            <label className={styles.field}>
              <span>或 上传本地图片作参考图（可选）</span>
              <input
                accept="image/*"
                disabled={uploadingRef}
                onChange={(event) =>
                  void handleReferenceFilePick(event.target.files?.[0], "rework")
                }
                type="file"
              />
              {uploadingRef ? (
                <small>上传中…</small>
              ) : reworkReferenceAssetId ? (
                <small>已上传参考图：{reworkReferenceName}（将优先使用）</small>
              ) : null}
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
                disabled={
                  busy ||
                  uploadingRef ||
                  (!reworkPrompt.trim() &&
                    !reworkReferenceUrl.trim() &&
                    !reworkReferenceAssetId)
                }
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

      {/* ---- 添加图片弹窗 ---- */}
      {addOpen ? (
        <div
          className={styles.renderLightbox}
          onMouseDown={() => setAddOpen(false)}
          role="presentation"
        >
          <div
            className={styles.renderReworkModal}
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
            aria-label="添加图片"
          >
            <div className={styles.renderLightboxHead}>
              <strong>在方案之外添加一张图</strong>
              <button
                aria-label="取消添加"
                className="secondary-button"
                onClick={() => setAddOpen(false)}
                type="button"
              >
                <X aria-hidden="true" size={16} />
              </button>
            </div>
            <label className={styles.field}>
              <span>想要什么画面（一句话描述，中英文都行）</span>
              <textarea
                onChange={(event) => setAddScene(event.target.value)}
                placeholder="例：办公桌上，手边放着捏捏球，屏幕前的人伸手去拿"
                rows={3}
                value={addScene}
              />
            </label>
            <label className={styles.field}>
              <span>专属参考图链接（可选）</span>
              <input
                inputMode="url"
                onChange={(event) => setAddReferenceUrl(event.target.value)}
                placeholder="贴图片链接；或用下面「上传本地图」；留空则用产品默认参考图"
                value={addReferenceUrl}
              />
            </label>
            <label className={styles.field}>
              <span>或 上传本地图片作参考图（可选）</span>
              <input
                accept="image/*"
                disabled={uploadingRef}
                onChange={(event) =>
                  void handleReferenceFilePick(event.target.files?.[0], "add")
                }
                type="file"
              />
              {uploadingRef ? (
                <small>上传中…</small>
              ) : addReferenceAssetId ? (
                <small>已上传参考图：{addReferenceName}（将优先使用）</small>
              ) : null}
            </label>
            <div className={styles.renderReworkChoices}>
              <label>
                <input
                  checked={addPlacement === "gallery"}
                  name="add-placement"
                  onChange={() => setAddPlacement("gallery")}
                  type="radio"
                />
                <span>
                  <strong>放进轮播图库</strong> —— 页面顶部的产品图轮播
                </span>
              </label>
              <label>
                <input
                  checked={addPlacement === "description"}
                  name="add-placement"
                  onChange={() => setAddPlacement("description")}
                  type="radio"
                />
                <span>
                  <strong>放进描述内嵌</strong> —— 详情页正文里的图文混排
                </span>
              </label>
            </div>
            <p className={styles.copyReviewHint}>
              新图的 SEO 四件套（标题/alt/说明/描述）自动生成,和 AI 方案图同一标准;
              渲染完成后同样进暂存区,满意再保存。
            </p>
            <div className={styles.renderLightboxActions}>
              <button
                className="primary-button"
                disabled={busy || !addScene.trim()}
                onClick={submitAddImage}
                type="button"
              >
                {busy ? (
                  <LoaderCircle aria-hidden="true" className="spin" size={15} />
                ) : (
                  <ImagePlay aria-hidden="true" size={15} />
                )}
                添加并开始渲染
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* ---- 加标注弹窗 ---- */}
      {overlayAsset ? (
        <div
          className={styles.renderLightbox}
          onMouseDown={() => setOverlayAsset(null)}
          role="presentation"
        >
          <div
            className={styles.renderReworkModal}
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
            aria-label="加标注"
          >
            <div className={styles.renderLightboxHead}>
              <strong>给第 {overlayAsset.position} 张加规格标注</strong>
              <button
                aria-label="取消加标注"
                className="secondary-button"
                onClick={() => setOverlayAsset(null)}
                type="button"
              >
                <X aria-hidden="true" size={16} />
              </button>
            </div>
            <p className={styles.copyReviewHint}>
              勾选要画上图的已核实规格（最多 4 条）——数值由系统按规格库精确绘制,
              不是 AI 画字,不会出现乱码或吹牛数据。
            </p>
            {overlayFields.length === 0 ? (
              <p className={styles.copyReviewHint}>
                该产品暂无可标注的已核实规格——先去「规格（事实）」补充材质/尺寸等真实数据。
              </p>
            ) : (
              <div className={styles.renderReworkChoices}>
                {overlayFields.map((field) => (
                  <label key={field.field}>
                    <input
                      checked={overlayPicked.includes(field.field)}
                      onChange={() => toggleOverlayField(field.field)}
                      type="checkbox"
                    />
                    <span>
                      <strong>{field.label}</strong> — {field.value_text}
                    </span>
                  </label>
                ))}
              </div>
            )}
            <div className={styles.renderLightboxActions}>
              <button
                className="primary-button"
                disabled={busy || overlayPicked.length === 0}
                onClick={submitOverlay}
                type="button"
              >
                {busy ? (
                  <LoaderCircle aria-hidden="true" className="spin" size={15} />
                ) : (
                  <CheckCircle2 aria-hidden="true" size={15} />
                )}
                应用并重画这张
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

"use client";

import {
  ChevronDown,
  Download,
  ImagePlus,
  Images,
  LoaderCircle,
  Maximize2,
  RefreshCcw,
  Save,
  Send,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Wand2,
  X,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { DashboardScene } from "@/components/dashboard-scene";
import {
  getProduct,
  importISystemImagesToProduct,
} from "@/modules/k/product-knowledge/api";
import type {
  ProductKnowledgeDetail,
  ProductKnowledgeVariant,
} from "@/modules/k/product-knowledge/types";

import {
  deleteMediaAsset,
  editImages,
  generateImages,
  getMediaLibrary,
  imageDataUrl,
  iMediaFileUrl,
  iMediaPreviewUrl,
  iMediaThumbnailUrl,
  saveToMediaLibrary,
} from "./api";
import styles from "./ImageSystemWorkspace.module.css";
import type {
  IImageCandidate,
  IMediaAsset,
  ISourceType,
} from "./types";

type CandidateBatch = {
  eventId: string;
  sourceType: ISourceType;
  promptOriginal: string;
  enhancedPrompt: string;
  aspectRatio: string;
  styleConfig: Record<string, unknown>;
  candidates: IImageCandidate[];
  removedIds: string[];
};

type ProgressMode = "generate" | "edit";

type ProgressState = {
  mode: ProgressMode;
  percent: number;
  label: string;
  status: "active" | "done" | "failed";
};

const ASPECT_RATIOS = ["1:1", "4:5", "3:4", "16:9", "9:16"];
const DEFAULT_ASPECT_RATIO = "1:1";
const DEFAULT_GENERATION_COUNT = 1;
const PROMPT_SKILL_LABEL = "i-image-prompt-skill-2026-06-27";
const PROGRESS_STEPS: Record<
  ProgressMode,
  Array<{ delayMs: number; percent: number; label: string }>
> = {
  edit: [
    { delayMs: 0, percent: 10, label: "校验参考图" },
    { delayMs: 800, percent: 28, label: "DeepSeek 正在优化英文作图指令" },
    { delayMs: 2600, percent: 52, label: "上传临时参考图并调用 gpt-image-2" },
    { delayMs: 9000, percent: 78, label: "图片模型正在编辑" },
    { delayMs: 18000, percent: 90, label: "清理临时图并解析结果" },
  ],
  generate: [
    { delayMs: 0, percent: 12, label: "DeepSeek 正在优化英文作图指令" },
    { delayMs: 1200, percent: 34, label: "记录生成任务" },
    { delayMs: 2600, percent: 58, label: "gpt-image-2 正在生成图片" },
    { delayMs: 12000, percent: 84, label: "解析图片并准备预览" },
  ],
};

type StyleConfigKey = "style" | "lighting" | "composition" | "background";

const STYLE_FIELDS: Array<{
  key: StyleConfigKey;
  label: string;
  generatePlaceholder: string;
  editPlaceholder: string;
}> = [
  {
    key: "style",
    label: "风格",
    generatePlaceholder: "例如：真实电商产品摄影、极简目录图、生活方式场景",
    editPlaceholder: "例如：真实电商修图、保留产品身份、自然商业质感",
  },
  {
    key: "lighting",
    label: "光线",
    generatePlaceholder: "例如：柔和棚拍灯、漫射自然光、高亮目录光",
    editPlaceholder: "例如：均衡棚拍光、保持原图光影、柔和补光",
  },
  {
    key: "composition",
    label: "构图",
    generatePlaceholder: "例如：居中主图、三分之二角度、俯拍平铺、留白构图",
    editPlaceholder: "例如：干净商业构图、主体居中、保留原始角度",
  },
  {
    key: "background",
    label: "背景",
    generatePlaceholder: "例如：干净电商棚拍背景、浅灰渐变、真实生活场景",
    editPlaceholder: "例如：保持产品一致性、替换为干净背景、弱化杂乱元素",
  },
];

function formatError(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function styleConfigFromInputs(values: {
  style: string;
  lighting: string;
  composition: string;
  background: string;
}) {
  return {
    background: values.background.trim(),
    composition: values.composition.trim(),
    lighting: values.lighting.trim(),
    style: values.style.trim(),
  };
}

function normalizeAspectRatio(value: string) {
  const trimmed = value.trim();
  return trimmed || DEFAULT_ASPECT_RATIO;
}

function normalizeGenerationCount(value: string) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return DEFAULT_GENERATION_COUNT;
  }
  return Math.min(8, Math.max(1, Math.floor(parsed)));
}

function variantLabel(variant: ProductKnowledgeVariant | null | undefined) {
  if (!variant) {
    return "默认变体";
  }
  const parts = [
    variant.color || null,
    variant.size
      ? /size/i.test(variant.size)
        ? variant.size
        : `${variant.size} Size`
      : null,
    variant.function || null,
    variant.quantity !== null && variant.quantity !== undefined
      ? `${variant.quantity} 件`
      : null,
  ].filter((part): part is string => Boolean(part && part.trim()));

  return parts.length > 0 ? parts.join(" | ") : "默认变体";
}

function sourceTypeLabel(sourceType: ISourceType) {
  return sourceType === "generate" ? "生成图" : "编辑图";
}

type MediaTileVariant = "big" | "wide" | "tall" | "normal";

// 图墙图块大小由图片自身比例决定：最新一张当封面大图，横图铺宽、竖图拉高。
function mediaTileVariant(asset: IMediaAsset, index: number): MediaTileVariant {
  if (index === 0) {
    return "big";
  }
  const { width, height } = asset;
  if (!width || !height) {
    return "normal";
  }
  const ratio = width / height;
  if (ratio >= 1.35) {
    return "wide";
  }
  if (ratio <= 0.74) {
    return "tall";
  }
  return "normal";
}

function activeCandidates(batch: CandidateBatch | null) {
  if (!batch) {
    return [];
  }
  const removed = new Set(batch.removedIds);
  return batch.candidates.filter((candidate) => !removed.has(candidate.candidate_id));
}

function CandidateGrid({
  batch,
  isKContext,
  isSaving,
  kSaveLabel,
  onRemove,
  onSaveI,
  onSaveK,
}: {
  batch: CandidateBatch | null;
  isKContext: boolean;
  isSaving: boolean;
  kSaveLabel: string;
  onRemove: (candidateId: string) => void;
  onSaveI: () => void;
  onSaveK: () => void;
}) {
  const [previewCandidateId, setPreviewCandidateId] = useState<string | null>(null);

  if (!batch) {
    return null;
  }

  const visibleCandidates = activeCandidates(batch);
  const previewCandidate =
    batch.candidates.find(
      (candidate) => candidate.candidate_id === previewCandidateId,
    ) ?? null;

  return (
    <div className={styles.candidateSurface}>
      <div className={styles.promptBox}>
        <span>DeepSeek 英文指令</span>
        <p>{batch.enhancedPrompt}</p>
      </div>

      <div className={styles.candidateGrid}>
        {batch.candidates.map((candidate) => {
          const removed = batch.removedIds.includes(candidate.candidate_id);
          return (
            <article
              className={styles.candidateCard}
              data-removed={removed}
              key={candidate.candidate_id}
            >
              <button
                aria-label="放大查看图片"
                className={styles.previewButton}
                disabled={removed}
                onClick={() => setPreviewCandidateId(candidate.candidate_id)}
                type="button"
              >
                <img alt="" src={imageDataUrl(candidate)} />
                <span>
                  <Maximize2 aria-hidden="true" size={15} />
                  放大
                </span>
              </button>
              <div className={styles.candidateMeta}>
                <strong>
                  {candidate.width} x {candidate.height}
                </strong>
                <span>{Math.ceil(candidate.file_size / 1024)} KB</span>
              </div>
              <button
                className="secondary-button"
                disabled={removed}
                onClick={() => onRemove(candidate.candidate_id)}
                type="button"
              >
                <X aria-hidden="true" size={15} />
                移除
              </button>
            </article>
          );
        })}
      </div>

      {previewCandidate && typeof document !== "undefined" ? createPortal(
        <div
          className={styles.lightbox}
          onClick={() => setPreviewCandidateId(null)}
          role="dialog"
          aria-modal="true"
          aria-label="图片放大预览"
        >
          <div
            className={styles.lightboxPanel}
            onClick={(event) => event.stopPropagation()}
          >
            <div className={styles.lightboxHeader}>
              <div>
                <strong>图片预览</strong>
                <span>
                  {previewCandidate.width} x {previewCandidate.height} /{" "}
                  {Math.ceil(previewCandidate.file_size / 1024)} KB
                </span>
              </div>
              <button
                className="secondary-button"
                onClick={() => setPreviewCandidateId(null)}
                type="button"
              >
                <X aria-hidden="true" size={15} />
                关闭
              </button>
            </div>
            <div className={styles.lightboxImageWrap}>
              <img alt="" src={imageDataUrl(previewCandidate)} />
            </div>
            <div className={styles.lightboxActions}>
              <button
                className="secondary-button"
                disabled={batch.removedIds.includes(previewCandidate.candidate_id)}
                onClick={() => {
                  onRemove(previewCandidate.candidate_id);
                  setPreviewCandidateId(null);
                }}
                type="button"
              >
                <X aria-hidden="true" size={15} />
                移除这张
              </button>
            </div>
          </div>
        </div>,
        document.body,
      ) : null}

      <div className={styles.saveRow}>
        <span>剩余 {visibleCandidates.length} 张可保存</span>
        {isKContext ? (
          <button
            className="primary-button"
            disabled={isSaving || visibleCandidates.length === 0}
            onClick={onSaveK}
            type="button"
          >
            {isSaving ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <Send aria-hidden="true" size={16} />
            )}
            {kSaveLabel}
          </button>
        ) : (
          <button
            className="primary-button"
            disabled={isSaving || visibleCandidates.length === 0}
            onClick={onSaveI}
            type="button"
          >
            {isSaving ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <Save aria-hidden="true" size={16} />
            )}
            保存到 I 媒体库
          </button>
        )}
      </div>
    </div>
  );
}

function ProgressBar({ progress }: { progress: ProgressState | null }) {
  if (!progress) {
    return null;
  }

  return (
    <div
      className={styles.progressPanel}
      data-status={progress.status}
      role="status"
    >
      <div className={styles.progressHeader}>
        <span>{progress.mode === "generate" ? "图片生成" : "图片编辑"}</span>
        <strong>{progress.percent}%</strong>
      </div>
      <div className={styles.progressTrack} aria-hidden="true">
        <span style={{ width: `${progress.percent}%` }} />
      </div>
      <p>{progress.label}</p>
    </div>
  );
}

function MediaLibraryPreview({
  asset,
  onClose,
  onRemove,
}: {
  asset: IMediaAsset | null;
  onClose: () => void;
  onRemove: (assetId: string) => void;
}) {
  if (!asset || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div
      className={styles.lightbox}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="媒体库图片放大预览"
    >
      <div
        className={styles.lightboxPanel}
        onClick={(event) => event.stopPropagation()}
      >
        <div className={styles.lightboxHeader}>
          <div>
            <strong>{asset.image_id}</strong>
            <span>
              {asset.width && asset.height
                ? `${asset.width} x ${asset.height}`
                : "尺寸未知"}{" "}
              / {Math.ceil(asset.file_size / 1024)} KB
            </span>
          </div>
          <button className="secondary-button" onClick={onClose} type="button">
            <X aria-hidden="true" size={15} />
            关闭
          </button>
        </div>
        <div className={styles.lightboxImageWrap}>
          <img alt="" decoding="async" src={iMediaPreviewUrl(asset.id)} />
        </div>
        <div className={styles.lightboxActions}>
          <a className="secondary-button" download href={iMediaFileUrl(asset.id)}>
            <Download aria-hidden="true" size={15} />
            下载
          </a>
          <button
            className="secondary-button"
            onClick={() => {
              onRemove(asset.id);
              onClose();
            }}
            type="button"
          >
            <Trash2 aria-hidden="true" size={15} />
            删除这张
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export function ImageSystemWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const productId = searchParams.get("product_id");
  const variantIdFromQuery = searchParams.get("variant_id");
  const [detachedKContext, setDetachedKContext] = useState(false);
  const isKContext = Boolean(productId) && !detachedKContext;
  const activeProductId = isKContext ? productId : null;

  const [product, setProduct] = useState<ProductKnowledgeDetail | null>(null);
  const [selectedVariantId, setSelectedVariantId] = useState(
    variantIdFromQuery || "",
  );
  const selectedVariant = useMemo(
    () =>
      (product?.variants ?? []).find((variant) => variant.id === selectedVariantId) ??
      null,
    [product?.variants, selectedVariantId],
  );
  const kSaveLabel = selectedVariant
    ? `保存到 ${variantLabel(selectedVariant)}`
    : "保存到产品变体";

  const [mode, setMode] = useState<"generate" | "edit">("generate");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [generatePrompt, setGeneratePrompt] = useState("");
  const [generateCount, setGenerateCount] = useState("");
  const [generateAspect, setGenerateAspect] = useState("");
  const [generateStyle, setGenerateStyle] = useState({
    background: "",
    composition: "",
    lighting: "",
    style: "",
  });
  const [generationBatch, setGenerationBatch] = useState<CandidateBatch | null>(
    null,
  );

  const [editPrompt, setEditPrompt] = useState("");
  const [editCount, setEditCount] = useState("");
  const [editAspect, setEditAspect] = useState("");
  const [editStyle, setEditStyle] = useState({
    background: "",
    composition: "",
    lighting: "",
    style: "",
  });
  const [editFiles, setEditFiles] = useState<File[]>([]);
  const [editBatch, setEditBatch] = useState<CandidateBatch | null>(null);

  const [media, setMedia] = useState<IMediaAsset[]>([]);
  const [mediaSourceFilter, setMediaSourceFilter] = useState<ISourceType | "">("");
  const [mediaProductFilter, setMediaProductFilter] = useState("");
  const [mediaVariantFilter, setMediaVariantFilter] = useState("");
  const [previewMediaAsset, setPreviewMediaAsset] = useState<IMediaAsset | null>(
    null,
  );

  const [isGenerating, setIsGenerating] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoadingMedia, setIsLoadingMedia] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [progress, setProgress] = useState<ProgressState | null>(null);
  const progressTimersRef = useRef<number[]>([]);

  const clearProgressTimers = useCallback(() => {
    for (const timerId of progressTimersRef.current) {
      window.clearTimeout(timerId);
    }
    progressTimersRef.current = [];
  }, []);

  const startProgress = useCallback(
    (mode: ProgressMode) => {
      clearProgressTimers();
      for (const step of PROGRESS_STEPS[mode]) {
        const timerId = window.setTimeout(() => {
          setProgress({
            label: step.label,
            mode,
            percent: step.percent,
            status: "active",
          });
        }, step.delayMs);
        progressTimersRef.current.push(timerId);
      }
    },
    [clearProgressTimers],
  );

  const finishProgress = useCallback(
    (mode: ProgressMode, label: string) => {
      clearProgressTimers();
      setProgress({ label, mode, percent: 100, status: "done" });
      const timerId = window.setTimeout(() => setProgress(null), 1800);
      progressTimersRef.current.push(timerId);
    },
    [clearProgressTimers],
  );

  const failProgress = useCallback(
    (mode: ProgressMode, label: string) => {
      clearProgressTimers();
      setProgress({ label, mode, percent: 100, status: "failed" });
    },
    [clearProgressTimers],
  );

  useEffect(() => {
    setDetachedKContext(false);
  }, [productId, variantIdFromQuery]);

  useEffect(() => {
    if (!isKContext || !productId) {
      setProduct(null);
      setSelectedVariantId("");
      return;
    }
    let cancelled = false;
    setError("");
    getProduct(productId)
      .then((loadedProduct) => {
        if (cancelled) {
          return;
        }
        setProduct(loadedProduct);
        const variants = loadedProduct.variants ?? [];
        const nextVariant =
          variants.find((variant) => variant.id === variantIdFromQuery) ??
          variants[0] ??
          null;
        setSelectedVariantId(nextVariant?.id ?? "");
        setGeneratePrompt((current) =>
          current.trim()
            ? current
            : loadedProduct.product_name_en ||
              loadedProduct.main_keyword ||
              loadedProduct.parent_sku ||
              "",
        );
      })
      .catch((loadError) => {
        if (!cancelled) {
          setError(formatError(loadError, "K 产品上下文加载失败。"));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isKContext, productId, variantIdFromQuery]);

  const loadMedia = useCallback(async () => {
    setIsLoadingMedia(true);
    setError("");
    try {
      const response = await getMediaLibrary({
        product_id: mediaProductFilter || undefined,
        source_type: mediaSourceFilter,
        variant_id: mediaVariantFilter || undefined,
      });
      setMedia(response.items);
    } catch (loadError) {
      setError(formatError(loadError, "I 媒体库加载失败。"));
    } finally {
      setIsLoadingMedia(false);
    }
  }, [mediaProductFilter, mediaSourceFilter, mediaVariantFilter]);

  useEffect(() => {
    if (!isKContext) {
      void loadMedia();
    }
  }, [isKContext, loadMedia]);

  useEffect(() => clearProgressTimers, [clearProgressTimers]);

  async function runGenerate() {
    setIsGenerating(true);
    setError("");
    setNotice("");
    startProgress("generate");
    const resolvedAspect = normalizeAspectRatio(generateAspect);
    const resolvedCount = normalizeGenerationCount(generateCount);
    try {
      const response = await generateImages({
        aspect_ratio: resolvedAspect,
        generation_count: resolvedCount,
        origin_context: isKContext ? "k_handoff" : "i_direct",
        product_id: activeProductId,
        prompt: generatePrompt,
        style_config: styleConfigFromInputs(generateStyle),
        variant_id: selectedVariantId || null,
      });
      setGenerationBatch({
        aspectRatio: resolvedAspect,
        candidates: response.candidates,
        enhancedPrompt: response.image_prompt_enhanced,
        eventId: response.event_id,
        promptOriginal: generatePrompt,
        removedIds: [],
        sourceType: "generate",
        styleConfig: styleConfigFromInputs(generateStyle),
      });
      setGeneratePrompt("");
      finishProgress("generate", "生成完成，正在展示预览");
    } catch (generateError) {
      setError(formatError(generateError, "图片生成失败。"));
      failProgress("generate", "图片生成失败，请查看错误信息");
    } finally {
      setIsGenerating(false);
    }
  }

  async function runEdit() {
    if (editFiles.length === 0) {
      setError("图片编辑必须先上传参考图。");
      return;
    }
    setIsEditing(true);
    setError("");
    setNotice("");
    startProgress("edit");
    const resolvedAspect = normalizeAspectRatio(editAspect);
    const resolvedCount = normalizeGenerationCount(editCount);
    try {
      const response = await editImages({
        aspect_ratio: resolvedAspect,
        files: editFiles,
        generation_count: resolvedCount,
        origin_context: isKContext ? "k_handoff" : "i_direct",
        product_id: activeProductId,
        prompt: editPrompt,
        style_config: styleConfigFromInputs(editStyle),
        variant_id: selectedVariantId || null,
      });
      setEditBatch({
        aspectRatio: resolvedAspect,
        candidates: response.candidates,
        enhancedPrompt: response.image_prompt_enhanced,
        eventId: response.event_id,
        promptOriginal: editPrompt,
        removedIds: [],
        sourceType: "edit",
        styleConfig: styleConfigFromInputs(editStyle),
      });
      setEditPrompt("");
      setEditFiles([]);
      finishProgress("edit", "编辑完成，正在展示预览");
    } catch (editError) {
      setError(formatError(editError, "图片编辑失败。"));
      failProgress("edit", "图片编辑失败，请查看错误信息");
    } finally {
      setIsEditing(false);
    }
  }

  function removeCandidate(sourceType: ISourceType, candidateId: string) {
    const setter = sourceType === "generate" ? setGenerationBatch : setEditBatch;
    setter((current) =>
      current
        ? {
            ...current,
            removedIds: current.removedIds.includes(candidateId)
              ? current.removedIds
              : [...current.removedIds, candidateId],
          }
        : current,
    );
  }

  async function saveBatchToI(batch: CandidateBatch | null) {
    if (!batch) {
      return;
    }
    const candidates = activeCandidates(batch);
    setIsSaving(true);
    setError("");
    setNotice("");
    try {
      const response = await saveToMediaLibrary({
        aspect_ratio: batch.aspectRatio,
        image_prompt_enhanced: batch.enhancedPrompt,
        images: candidates,
        prompt_original: batch.promptOriginal,
        source_type: batch.sourceType,
        style_config: batch.styleConfig,
      });
      setNotice(`已保存 ${response.count} 张图片到 I 媒体库。`);
      if (batch.sourceType === "generate") {
        setGenerationBatch(null);
      } else {
        setEditBatch(null);
      }
      await loadMedia();
    } catch (saveError) {
      setError(formatError(saveError, "保存到 I 媒体库失败。"));
    } finally {
      setIsSaving(false);
    }
  }

  async function saveBatchToK(batch: CandidateBatch | null) {
    if (!batch || !activeProductId || !selectedVariant) {
      setError("保存到 K 必须有产品 ID 和变体 ID。");
      return;
    }
    const candidates = activeCandidates(batch);
    setIsSaving(true);
    setError("");
    setNotice("");
    try {
      const response = await importISystemImagesToProduct(activeProductId, {
        aspect_ratio: batch.aspectRatio,
        event_id: batch.eventId,
        image_prompt_enhanced: batch.enhancedPrompt,
        images: candidates.map((candidate) => ({
          candidate_id: candidate.candidate_id,
          content_sha256: candidate.content_sha256,
          height: candidate.height,
          image_base64: candidate.image_base64,
          metadata: candidate.metadata,
          mime_type: candidate.mime_type,
          width: candidate.width,
        })),
        prompt_original: batch.promptOriginal,
        source_type: batch.sourceType,
        style_config: batch.styleConfig,
        variant_id: selectedVariant.id,
      });
      setNotice(
        response.submitted
          ? `已保存 ${response.asset_ids.length} 张图片到 K，并已提交图片。`
          : `已保存 ${response.asset_ids.length} 张图片到 K。${response.message ?? ""}`,
      );
      if (batch.sourceType === "generate") {
        setGenerationBatch(null);
      } else {
        setEditBatch(null);
      }
    } catch (saveError) {
      setError(formatError(saveError, "保存到 K 产品失败。"));
    } finally {
      setIsSaving(false);
    }
  }

  async function removeMedia(assetId: string) {
    setError("");
    setNotice("");
    const previousMedia = media;
    setMedia((current) => current.filter((asset) => asset.id !== assetId));
    setPreviewMediaAsset((current) => (current?.id === assetId ? null : current));
    try {
      await deleteMediaAsset(assetId);
      setNotice("图片已删除。");
    } catch (deleteError) {
      setMedia(previousMedia);
      setError(formatError(deleteError, "删除失败。"));
    }
  }

  function updateEditFiles(files: File[]) {
    const imageFiles = files.filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length !== files.length) {
      setError("图片编辑只允许上传图片文件。");
      return;
    }
    if (imageFiles.length > 10) {
      setError("图片编辑一次最多上传 10 张参考图。");
      return;
    }
    setEditFiles(imageFiles);
    setError("");
  }

  function clearKContext() {
    setDetachedKContext(true);
    setProduct(null);
    setSelectedVariantId("");
    setNotice("已切换为 I 独立作图。");
    router.replace("/image-system", { scroll: false });
  }

  return (
    <section
      aria-label="I 系列 AI 作图系统"
      className={`${styles.workspace} mm-page i-page`}
    >
      <DashboardScene />
      <div className={styles.contextBar}>
        <div>
          <span className={styles.eyebrow}>I 系列</span>
          <h2>AI 作图系统</h2>
          <p>
            生成与编辑分栏独立处理；直接进入保存到 I 媒体库，从 K 进入则保存回对应产品变体。
          </p>
        </div>
        {isKContext ? (
          <div className={styles.kContext}>
            <div className={styles.kContextDetails}>
              <strong>{product?.product_name_en || "K 产品上下文"}</strong>
              <select
                onChange={(event) => setSelectedVariantId(event.target.value)}
                value={selectedVariantId}
              >
                {(product?.variants ?? []).map((variant) => (
                  <option key={variant.id} value={variant.id}>
                    {variantLabel(variant)}
                  </option>
                ))}
              </select>
            </div>
            <button
              aria-label="退出 K 产品绑定"
              className={styles.clearKContextButton}
              onClick={clearKContext}
              title="退出 K 产品绑定"
              type="button"
            >
              <X aria-hidden="true" size={16} />
            </button>
          </div>
        ) : (
          <button
            className="secondary-button"
            disabled={isLoadingMedia}
            onClick={() => void loadMedia()}
            type="button"
          >
            <RefreshCcw aria-hidden="true" size={16} />
            刷新媒体库
          </button>
        )}
      </div>

      {error ? <p className={styles.error}>{error}</p> : null}
      {notice ? <p className={styles.notice}>{notice}</p> : null}
      <ProgressBar progress={progress} />

      <div className={styles.composer}>
        <div className={styles.modeSwitch} role="tablist" aria-label="作图模式">
          <button
            aria-selected={mode === "generate"}
            data-on={mode === "generate"}
            onClick={() => setMode("generate")}
            role="tab"
            type="button"
          >
            <Sparkles aria-hidden="true" size={17} />
            图片生成
          </button>
          <button
            aria-selected={mode === "edit"}
            data-on={mode === "edit"}
            onClick={() => setMode("edit")}
            role="tab"
            type="button"
          >
            <Images aria-hidden="true" size={17} />
            图片编辑
          </button>
        </div>

        {mode === "generate" ? (
          <section className={styles.toolPanel} aria-label="图片生成">
            <label className={styles.field}>
              <span>生成提示词</span>
              <textarea
                onChange={(event) => setGeneratePrompt(event.target.value)}
                placeholder="输入你要生成的图片内容、产品特征、场景或风格要求。"
                value={generatePrompt}
              />
              <p className={styles.helpText}>
                已安装 {PROMPT_SKILL_LABEL}，启动后会调用 DeepSeek V4 Pro 转换成英文作图指令。
              </p>
            </label>
            <div className={styles.formGrid}>
              <label className={styles.field}>
                <span>比例</span>
                <input
                  list="i-generate-aspect-ratios"
                  onChange={(event) => setGenerateAspect(event.target.value)}
                  placeholder="默认比例：1:1"
                  value={generateAspect}
                />
                <datalist id="i-generate-aspect-ratios">
                  {ASPECT_RATIOS.map((ratio) => (
                    <option key={ratio} value={ratio}>
                      {ratio}
                    </option>
                  ))}
                </datalist>
              </label>
              <label className={styles.field}>
                <span>数量</span>
                <input
                  max={8}
                  min={1}
                  onChange={(event) => setGenerateCount(event.target.value)}
                  placeholder="默认图片数量：1张"
                  type="number"
                  value={generateCount}
                />
              </label>
            </div>
            <button
              aria-expanded={showAdvanced}
              className={styles.advancedToggle}
              onClick={() => setShowAdvanced((value) => !value)}
              type="button"
            >
              <SlidersHorizontal aria-hidden="true" size={15} />
              高级参数
              <span className={styles.advancedHint}>风格 / 光线 / 构图 / 背景</span>
              <ChevronDown
                aria-hidden="true"
                className={showAdvanced ? styles.chevOpen : styles.chev}
                size={15}
              />
            </button>
            {showAdvanced ? (
              <div className={styles.formGrid}>
                {STYLE_FIELDS.map((field) => (
                  <label className={styles.field} key={field.key}>
                    <span>{field.label}</span>
                    <input
                      onChange={(event) =>
                        setGenerateStyle((current) => ({
                          ...current,
                          [field.key]: event.target.value,
                        }))
                      }
                      placeholder={field.generatePlaceholder}
                      value={generateStyle[field.key]}
                    />
                  </label>
                ))}
              </div>
            ) : null}
            <button
              className="primary-button"
              disabled={isGenerating || !generatePrompt.trim()}
              onClick={() => void runGenerate()}
              type="button"
            >
              {isGenerating ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <Wand2 aria-hidden="true" size={16} />
              )}
              生成图片
            </button>
            <CandidateGrid
              batch={generationBatch}
              isKContext={isKContext}
              isSaving={isSaving}
              kSaveLabel={kSaveLabel}
              onRemove={(candidateId) => removeCandidate("generate", candidateId)}
              onSaveI={() => void saveBatchToI(generationBatch)}
              onSaveK={() => void saveBatchToK(generationBatch)}
            />
          </section>
        ) : (
          <section className={styles.toolPanel} aria-label="图片编辑">
            <label className={styles.field}>
              <span>参考图</span>
              <input
                accept="image/*"
                multiple
                onChange={(event) =>
                  updateEditFiles(Array.from(event.target.files ?? []))
                }
                type="file"
              />
            </label>
            <div className={styles.fileChips}>
              {editFiles.map((file) => (
                <span key={`${file.name}-${file.size}`}>{file.name}</span>
              ))}
            </div>
            <label className={styles.field}>
              <span>编辑提示词</span>
              <textarea
                onChange={(event) => setEditPrompt(event.target.value)}
                placeholder="输入要对参考图执行的修改，例如换背景、调整光线、增加场景或保留产品身份。"
                value={editPrompt}
              />
              <p className={styles.helpText}>
                已安装 {PROMPT_SKILL_LABEL}，启动后会调用 DeepSeek V4 Pro 转换成英文作图指令。
              </p>
            </label>
            <div className={styles.formGrid}>
              <label className={styles.field}>
                <span>比例</span>
                <input
                  list="i-edit-aspect-ratios"
                  onChange={(event) => setEditAspect(event.target.value)}
                  placeholder="默认比例：1:1"
                  value={editAspect}
                />
                <datalist id="i-edit-aspect-ratios">
                  {ASPECT_RATIOS.map((ratio) => (
                    <option key={ratio} value={ratio}>
                      {ratio}
                    </option>
                  ))}
                </datalist>
              </label>
              <label className={styles.field}>
                <span>数量</span>
                <input
                  max={8}
                  min={1}
                  onChange={(event) => setEditCount(event.target.value)}
                  placeholder="默认图片数量：1张"
                  type="number"
                  value={editCount}
                />
              </label>
            </div>
            <button
              aria-expanded={showAdvanced}
              className={styles.advancedToggle}
              onClick={() => setShowAdvanced((value) => !value)}
              type="button"
            >
              <SlidersHorizontal aria-hidden="true" size={15} />
              高级参数
              <span className={styles.advancedHint}>风格 / 光线 / 构图 / 背景</span>
              <ChevronDown
                aria-hidden="true"
                className={showAdvanced ? styles.chevOpen : styles.chev}
                size={15}
              />
            </button>
            {showAdvanced ? (
              <div className={styles.formGrid}>
                {STYLE_FIELDS.map((field) => (
                  <label className={styles.field} key={field.key}>
                    <span>{field.label}</span>
                    <input
                      onChange={(event) =>
                        setEditStyle((current) => ({
                          ...current,
                          [field.key]: event.target.value,
                        }))
                      }
                      placeholder={field.editPlaceholder}
                      value={editStyle[field.key]}
                    />
                  </label>
                ))}
              </div>
            ) : null}
            <button
              className="primary-button"
              disabled={isEditing || !editPrompt.trim() || editFiles.length === 0}
              onClick={() => void runEdit()}
              type="button"
            >
              {isEditing ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <ImagePlus aria-hidden="true" size={16} />
              )}
              启动图片编辑
            </button>
            <CandidateGrid
              batch={editBatch}
              isKContext={isKContext}
              isSaving={isSaving}
              kSaveLabel={kSaveLabel}
              onRemove={(candidateId) => removeCandidate("edit", candidateId)}
              onSaveI={() => void saveBatchToI(editBatch)}
              onSaveK={() => void saveBatchToK(editBatch)}
            />
          </section>
        )}
      </div>

      {!isKContext ? (
        <section className={styles.libraryPanel} aria-labelledby="i-media-library">
          <div className={styles.libraryHeader}>
            <div>
              <span className={styles.eyebrow}>I 媒体库</span>
              <h3 id="i-media-library">媒体库</h3>
            </div>
            <div className={styles.libraryFilters}>
              <select
                onChange={(event) =>
                  setMediaSourceFilter(event.target.value as ISourceType | "")
                }
                value={mediaSourceFilter}
              >
                <option value="">全部来源</option>
                <option value="generate">生成图</option>
                <option value="edit">编辑图</option>
              </select>
              <input
                onChange={(event) => setMediaProductFilter(event.target.value)}
                placeholder="产品 ID"
                value={mediaProductFilter}
              />
              <input
                onChange={(event) => setMediaVariantFilter(event.target.value)}
                placeholder="变体 ID"
                value={mediaVariantFilter}
              />
              <button
                className="secondary-button"
                disabled={isLoadingMedia}
                onClick={() => void loadMedia()}
                type="button"
              >
                <RefreshCcw aria-hidden="true" size={16} />
                筛选
              </button>
            </div>
          </div>
          <div className={styles.mediaGrid}>
            {media.map((asset, index) => {
              const variant = mediaTileVariant(asset, index);
              return (
              <article
                className={`${styles.mediaCard} ${styles[`tile_${variant}`]}`}
                key={asset.id}
              >
                <div className={styles.mediaThumb}>
                  <img
                    alt=""
                    decoding="async"
                    loading="lazy"
                    src={iMediaThumbnailUrl(asset.id)}
                  />
                  <span className={styles.mediaTag}>
                    {sourceTypeLabel(asset.source_type)}
                  </span>
                  <div className={styles.mediaOverlay}>
                    <button
                      aria-label="放大查看"
                      className={styles.mediaIcon}
                      onClick={() => setPreviewMediaAsset(asset)}
                      title="放大"
                      type="button"
                    >
                      <Maximize2 aria-hidden="true" size={16} />
                    </button>
                    <a
                      aria-label="下载"
                      className={styles.mediaIcon}
                      download
                      href={iMediaFileUrl(asset.id)}
                      title="下载"
                    >
                      <Download aria-hidden="true" size={16} />
                    </a>
                    <button
                      aria-label="删除"
                      className={styles.mediaIcon}
                      onClick={() => void removeMedia(asset.id)}
                      title="删除"
                      type="button"
                    >
                      <Trash2 aria-hidden="true" size={16} />
                    </button>
                  </div>
                </div>
              </article>
              );
            })}
          </div>
          {media.length === 0 ? (
            <p className={styles.empty}>暂无 I 媒体库图片。</p>
          ) : null}
          <MediaLibraryPreview
            asset={previewMediaAsset}
            onClose={() => setPreviewMediaAsset(null)}
            onRemove={(assetId) => void removeMedia(assetId)}
          />
        </section>
      ) : null}
    </section>
  );
}

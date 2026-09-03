"use client";

/**
 * 产品图片：上传、绑定变体、送 I 系列、提交。
 *
 * 从 ProductDetail 抽出的第五簇（2026-09-01）。11 个 state 里 9 个是本地的，
 * 只有「已提交」和「改过了」两个信号报给上层算 P 系列就绪度 ——
 * 和关键词、卖点两簇是同一套接口，五块都长一个样，读代码的人只需要学一次。
 *
 * 家规钉在这里：
 * - 少于 5 张不许提交。图片是独立站转化的主要抓手，凑不齐宁可卡住。
 * - 变体产品只有 1 个变体时给警告：多半是变体没拆开，图片会全绑到同一个 SKU 上。
 */

import {
  CheckCircle2,
  Download,
  ExternalLink,
  ImagePlus,
  Images,
  LoaderCircle,
  Send,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useMemo, useRef, useState, type DragEvent } from "react";

import {
  mediaAssetFileUrl,
  mediaAssetThumbnailUrl,
  setImageUploadBound,
  uploadProductMediaAsset,
} from "./api";
import {
  formatVariantDisplayName,
  formatVariantOptionLabel,
  mediaVariantDisplayName,
  variantAttributesFromJson,
} from "./display";
import styles from "./ProductKnowledge.module.css";
import type {
  KMediaAsset,
  ProductKnowledgeDetail,
  ProductKnowledgeListItem,
  ProductKnowledgeVariant,
} from "./types";

function displayMediaSource(source: string | null) {
  const labels: Record<string, string> = {
    i_system_asset: "I系统图片",
    manual_upload_image: "手动图片",
  };

  return labels[source ?? ""] ?? "手动图片";
}

function displayMediaStatus(status: string) {
  const labels: Record<string, string> = {
    active: "可用",
    available: "可用",
    bound: "已绑定",
    created: "已创建",
    pending: "待处理",
    rejected: "已拒绝",
    uploaded: "已上传",
  };

  return labels[status] ?? "待处理";
}

/** 上传中的占位条目。上传是逐张异步的，没有它界面就只能干等。 */
type PendingMediaUpload = {
  id: string;
  fileName: string;
  variantSku: string;
};

function buildISystemHref(
  product: ProductKnowledgeListItem,
  variant: ProductKnowledgeVariant | null,
) {
  const params = new URLSearchParams({
    product_id: product.id,
    source: "k",
  });
  if (variant?.id) {
    params.set("variant_id", variant.id);
  }
  return `/image-system?${params.toString()}`;
}

type ProductMediaPanelProps = {
  product: ProductKnowledgeDetail;
  mediaAssets: KMediaAsset[];
  isWorkflowBusy: boolean;
  complete: boolean;
  dirty: boolean;
  onBindImage?: (assetId: string, variantSku: string) => void;
  onCreateMedia?: (
    file: File,
    variantSku: string,
  ) => Promise<KMediaAsset | void> | KMediaAsset | void;
  onDeleteMedia?: (assetId: string) => Promise<void> | void;
  onSubmitImages?: () => Promise<void> | void;
  /** 上传/删除之后请上层重拉详情——这个面板不持有产品数据的真相。 */
  refreshProductDetail: (productId: string) => Promise<unknown>;
  /** 这一簇唯一的对外信号。 */
  onSubmittedChange: (submitted: boolean) => void;
  onTouchedChange: (touched: boolean) => void;
};

export function ProductMediaPanel({
  product,
  mediaAssets,
  isWorkflowBusy,
  complete,
  dirty,
  onBindImage,
  onCreateMedia,
  onDeleteMedia,
  onSubmitImages,
  refreshProductDetail,
  onSubmittedChange,
  onTouchedChange,
}: ProductMediaPanelProps) {
  const mediaInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedMediaFiles, setSelectedMediaFiles] = useState<File[]>([]);
  const [isDraggingMedia, setIsDraggingMedia] = useState(false);
  const [mediaError, setMediaError] = useState("");
  const [isUploadingMedia, setIsUploadingMedia] = useState(false);
  const [boundOverrides, setBoundOverrides] = useState<Record<string, boolean>>({});
  const [bindingBoundIds, setBindingBoundIds] = useState<string[]>([]);
  const [pendingMediaUploads, setPendingMediaUploads] = useState<
    PendingMediaUpload[]
  >([]);
  const [deletingMediaIds, setDeletingMediaIds] = useState<string[]>([]);
  const [selectedVariantSku, setSelectedVariantSku] = useState(
    product.variants?.[0]?.variant_sku ?? "",
  );

  const setImageSectionTouched = onTouchedChange;
  const setImageSectionSubmitted = onSubmittedChange;

  const activeMediaAssets = useMemo(
    () => mediaAssets.filter((asset) => asset.status !== "removed"),
    [mediaAssets],
  );
  const activeVariantCount = product.variants?.length ?? 0;
  const selectedVariant = useMemo(
    () =>
      (product.variants ?? []).find(
        (variant) => variant.variant_sku === selectedVariantSku,
      ) ?? null,
    [product.variants, selectedVariantSku],
  );
  const selectedMediaLabel =
    selectedMediaFiles.length === 0
      ? "拖拽或选择本地图片"
      : selectedMediaFiles.length === 1
        ? selectedMediaFiles[0].name
        : `已选择 ${selectedMediaFiles.length} 张图片`;
  const variantSplitWarning = Boolean(
    product.product_type === "variable_product" && activeVariantCount <= 1,
  );
  const imagesComplete = complete;
  const imagesDirty = dirty;
  const iSystemHref = buildISystemHref(product, selectedVariant);

  function setUploadFiles(files: File[]) {
    if (files.length === 0) {
      return;
    }
    const invalidFile = files.find(
      (file) => file.type && !file.type.startsWith("image/"),
    );
    if (invalidFile) {
      setMediaError("只能上传图片文件。");
      return;
    }
    setMediaError("");
    setSelectedMediaFiles(files);
  }

  function handleMediaDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDraggingMedia(false);
    setUploadFiles(Array.from(event.dataTransfer.files));
  }

  const isUploadBound = (asset: KMediaAsset): boolean => {
    if (asset.id in boundOverrides) {
      return boundOverrides[asset.id];
    }
    const meta = asset.metadata as { upload_bound?: unknown } | null;
    return meta?.upload_bound === true;
  };

  async function toggleUploadBound(asset: KMediaAsset) {
    const next = !isUploadBound(asset);
    setBindingBoundIds((ids) => [...ids, asset.id]);
    setMediaError("");
    try {
      await setImageUploadBound(product.id, asset.id, next);
      setBoundOverrides((current) => ({ ...current, [asset.id]: next }));
    } catch (error) {
      setMediaError(
        error instanceof Error ? error.message : "绑定取图失败，请重试。",
      );
    } finally {
      setBindingBoundIds((ids) => ids.filter((id) => id !== asset.id));
    }
  }

  async function uploadAsReference() {
    if (!product) {
      return;
    }
    if (selectedMediaFiles.length === 0) {
      setMediaError("请先选择本地图片文件。");
      return;
    }
    if (!selectedVariantSku) {
      setMediaError("请选择图片绑定变体。");
      return;
    }
    setIsUploadingMedia(true);
    setMediaError("");
    try {
      for (const file of selectedMediaFiles) {
        await uploadProductMediaAsset(
          product.id,
          file,
          selectedVariantSku,
          "reference",
        );
      }
      setSelectedMediaFiles([]);
      if (mediaInputRef.current) {
        mediaInputRef.current.value = "";
      }
      setImageSectionTouched(true);
      await refreshProductDetail(product.id);
    } catch (error) {
      setMediaError(
        error instanceof Error ? error.message : "参考图上传失败，请重试。",
      );
    } finally {
      setIsUploadingMedia(false);
    }
  }

  async function createMedia() {
    if (selectedMediaFiles.length === 0) {
      setMediaError("请选择本地图片文件。");
      return;
    }
    if (!selectedVariantSku) {
      setMediaError("请选择图片绑定变体。");
      return;
    }
    const uploadBatch = selectedMediaFiles.map((file, index) => ({
      file,
      id: `${Date.now()}-${index}-${file.name}`,
    }));
    setPendingMediaUploads((current) => [
      ...uploadBatch.map((item) => ({
        fileName: item.file.name,
        id: item.id,
        variantSku: selectedVariantSku,
      })),
      ...current,
    ]);
    setIsUploadingMedia(true);
    setMediaError("");
    try {
      for (const item of uploadBatch) {
        await onCreateMedia?.(item.file, selectedVariantSku);
        setPendingMediaUploads((current) =>
          current.filter((pending) => pending.id !== item.id),
        );
      }
      setSelectedMediaFiles([]);
      if (mediaInputRef.current) {
        mediaInputRef.current.value = "";
      }
      setImageSectionTouched(true);
      setImageSectionSubmitted(false);
    } catch (error) {
      setMediaError(error instanceof Error ? error.message : "图片上传失败。");
    } finally {
      setPendingMediaUploads((current) =>
        current.filter((pending) =>
          uploadBatch.every((item) => item.id !== pending.id),
        ),
      );
      setIsUploadingMedia(false);
    }
  }

  async function deleteMedia(assetId: string) {
    setDeletingMediaIds((current) =>
      current.includes(assetId) ? current : [...current, assetId],
    );
    setMediaError("");
    try {
      await onDeleteMedia?.(assetId);
      setImageSectionTouched(true);
      setImageSectionSubmitted(false);
    } catch (error) {
      setMediaError(error instanceof Error ? error.message : "图片删除失败。");
    } finally {
      setDeletingMediaIds((current) =>
        current.filter((currentId) => currentId !== assetId),
      );
    }
  }

  function bindUploadedImage(assetId: string, variantSku: string) {
    setImageSectionTouched(true);
    setImageSectionSubmitted(false);
    onBindImage?.(assetId, variantSku);
  }

  async function submitImageSection() {
    if (activeMediaAssets.length < 5) {
      setMediaError("请至少上传 5 张图片后再提交图片。");
      return;
    }

    setMediaError("");
    try {
      await onSubmitImages?.();
      setImageSectionTouched(false);
      setImageSectionSubmitted(true);
    } catch (error) {
      setMediaError(error instanceof Error ? error.message : "图片提交失败。");
    }
  }


  return (
      <section className={styles.workflowSection} aria-labelledby="k-image-system">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>图片</span>
            <h4 id="k-image-system">图片管理</h4>
          </div>
          <a className="secondary-button" href={iSystemHref}>
            <ExternalLink aria-hidden="true" size={16} />
            I系列
          </a>
        </div>

        <div className={styles.workflowMetrics}>
          <div>
            <dt>图片数</dt>
            <dd>{activeMediaAssets.length} / 5</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>
              {imagesComplete
                ? "已保存"
                : imagesDirty
                  ? "已修改，待重新提交"
                  : "待保存"}
            </dd>
          </div>
        </div>

        <label className={styles.field}>
          <span>变体</span>
          <select
            onChange={(event) => setSelectedVariantSku(event.target.value)}
            value={selectedVariantSku}
          >
            {(product.variants ?? []).map((variant, index) => (
              <option key={variant.variant_sku} value={variant.variant_sku}>
                {formatVariantOptionLabel(variant, index)}
              </option>
            ))}
          </select>
        </label>

        {variantSplitWarning ? (
          <p className={styles.sellingPointsEmpty}>
            当前后端只有 1 条变体记录。如果这其实是多个变体，请创建产品时用“添加变体”分别录入，每条变体会成为独立图片绑定目标。
          </p>
        ) : null}

        {selectedVariant ? (
          <div className={styles.variantImageFolder}>
            <strong>图片绑定目标</strong>
            <span>
              {formatVariantDisplayName(selectedVariant)} / {selectedVariant.variant_sku}
              {" / "}
              属性 {variantAttributesFromJson(selectedVariant.attributes_json).length} 项
            </span>
          </div>
        ) : null}

        <div className={styles.mediaCreateRow}>
          <div
            className={`${styles.mediaDropzone} ${
              isDraggingMedia ? styles.mediaDropzoneActive : ""
            }`}
            onClick={() => mediaInputRef.current?.click()}
            onDragEnter={(event) => {
              event.preventDefault();
              setIsDraggingMedia(true);
            }}
            onDragLeave={(event) => {
              event.preventDefault();
              setIsDraggingMedia(false);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDrop={handleMediaDrop}
            role="button"
            tabIndex={0}
          >
            <input
              accept="image/*"
              hidden
              multiple
              onChange={(event) =>
                setUploadFiles(Array.from(event.target.files ?? []))
              }
              ref={mediaInputRef}
              type="file"
            />
            <ImagePlus aria-hidden="true" size={18} />
            <div>
              <strong>{selectedMediaLabel}</strong>
              <span>支持一次选择多张图片，上传后绑定当前 product / variant</span>
            </div>
          </div>
          <button
            className="secondary-button"
            disabled={
              isUploadingMedia ||
              !selectedVariantSku
            }
            onClick={() =>
              selectedMediaFiles.length === 0
                ? mediaInputRef.current?.click()
                : void createMedia()
            }
            type="button"
          >
            {isUploadingMedia ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <ImagePlus aria-hidden="true" size={16} />
            )}
            {selectedMediaFiles.length === 0
              ? "选择图片"
              : selectedMediaFiles.length > 1
              ? `上传 ${selectedMediaFiles.length} 张`
              : "上传"}
          </button>
          {selectedMediaFiles.length > 0 ? (
            <button
              className="secondary-button"
              disabled={isUploadingMedia || !selectedVariantSku}
              onClick={() => void uploadAsReference()}
              title="把选中的本地图上传为作图参考图（供 AI 渲染/重做时参考），不会直接上架取图"
              type="button"
            >
              <ImagePlus aria-hidden="true" size={16} />
              上传为参考图
            </button>
          ) : null}
        </div>
        {mediaError ? (
          <p className={styles.sellingPointsError}>{mediaError}</p>
        ) : null}

        <ul className={styles.mediaList}>
          {pendingMediaUploads.map((item) => (
            <li key={item.id}>
              <div>
                <strong>{item.fileName}</strong>
                <span>
                  {mediaVariantDisplayName(product.variants, item.variantSku)} / 正在上传
                </span>
              </div>
              <div>
                <button className="secondary-button" disabled type="button">
                  <LoaderCircle aria-hidden="true" className="spin" size={15} />
                  上传中
                </button>
              </div>
            </li>
          ))}
          {activeMediaAssets.map((asset) => (
            <li key={asset.id}>
              <div className={styles.mediaPreview}>
                <img
                  alt=""
                  decoding="async"
                  loading="lazy"
                  src={
                    asset.file_url_placeholder || mediaAssetThumbnailUrl(asset.id)
                  }
                />
              </div>
              <div className={styles.mediaMeta}>
                <strong>{asset.object_key || asset.id}</strong>
                <span>
                  {mediaVariantDisplayName(product.variants, asset.variant_sku)} /{" "}
                  {displayMediaSource(asset.source)} / {displayMediaStatus(asset.status)}
                </span>
              </div>
              <div>
                <a
                  className="secondary-button"
                  download
                  href={asset.file_url_placeholder || mediaAssetFileUrl(asset.id)}
                  rel="noreferrer"
                  target={asset.file_url_placeholder ? "_blank" : undefined}
                >
                  <Download aria-hidden="true" size={15} />
                  下载
                </a>
                <button
                  className="secondary-button"
                  disabled={
                    isWorkflowBusy ||
                    asset.source === "i_system_asset" ||
                    !asset.variant_sku
                  }
                  onClick={() =>
                    asset.variant_sku
                      ? bindUploadedImage(asset.id, asset.variant_sku)
                      : undefined
                  }
                  type="button"
                >
                  <Send aria-hidden="true" size={15} />
                  绑定
                </button>
                {asset.source === "manual_upload_image" &&
                asset.asset_role !== "reference" ? (
                  <button
                    className="secondary-button"
                    disabled={bindingBoundIds.includes(asset.id)}
                    onClick={() => void toggleUploadBound(asset)}
                    title="绑定后这张手动图会随渲染图一起上架取图；不绑定则不取"
                    type="button"
                  >
                    {bindingBoundIds.includes(asset.id) ? (
                      <LoaderCircle aria-hidden="true" className="spin" size={15} />
                    ) : (
                      <Send aria-hidden="true" size={15} />
                    )}
                    {isUploadBound(asset) ? "已取图 · 点击移除" : "加入取图"}
                  </button>
                ) : null}
                <button
                  className="secondary-button"
                  disabled={deletingMediaIds.includes(asset.id)}
                  onClick={() => void deleteMedia(asset.id)}
                  type="button"
                >
                  {deletingMediaIds.includes(asset.id) ? (
                    <LoaderCircle aria-hidden="true" className="spin" size={15} />
                  ) : (
                    <Trash2 aria-hidden="true" size={15} />
                  )}
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>
        {activeMediaAssets.length === 0 && pendingMediaUploads.length === 0 ? (
          <p className={styles.sellingPointsEmpty}>
            暂无已上传图片。请至少上传 5 张后提交图片。
          </p>
        ) : null}

        <div className={styles.sectionFooter}>
          <span data-complete={imagesComplete}>
            {imagesComplete
              ? "图片已保存"
              : imagesDirty
                ? "图片已修改，待重新提交"
                : "图片不少于 5 张后可保存"}
          </span>
          <button
            className="primary-button"
            disabled={activeMediaAssets.length < 5 || isWorkflowBusy}
            onClick={() => void submitImageSection()}
            type="button"
          >
            <CheckCircle2 aria-hidden="true" size={16} />
            提交图片
          </button>
        </div>
      </section>
  );
}

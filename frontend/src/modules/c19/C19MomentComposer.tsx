"use client";

import { ImagePlus, LoaderCircle, Send, ShieldCheck, X } from "lucide-react";
import {
  type ChangeEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { ApiError } from "@/lib/api";

import {
  createC19MomentAssetUploadIntent,
  createC19MomentDraft,
  finalizeC19MomentAssetUpload,
  getC19MomentAssetStatus,
  publishC19Moment,
} from "./api";
import {
  C19AssetTransferError,
  assertC19UploadLocator,
  inspectC19AssetSelection,
  makeC19ClientAssetId,
  putC19AssetBytes,
  sha256C19File,
  waitForC19AssetPoll,
} from "./C19AssetTransfer";
import {
  C19_MOMENT_CONTENT_MAX_LENGTH,
  C19_MOMENT_IMAGE_ACCEPT,
  C19_MOMENT_MAX_AUDIENCE_AFFILIATIONS,
  C19_MOMENT_MAX_IMAGES,
  type C19PendingMomentImage,
  assertC19MomentImageCount,
  assertC19MomentImageSelection,
  makeC19ClientMomentId,
  retainC19MomentAudienceAffiliations,
} from "./C19MomentRuntime";
import styles from "./C19Moments.module.css";
import type {
  C19Asset,
  C19Moment,
  C19MomentVisibility,
  C19Profile,
} from "./types";

const ASSET_SCAN_POLL_LIMIT = 120;

type PendingPublication = {
  audienceAffiliationIds: string[];
  clientMomentId: string;
  content: string;
  images: C19PendingMomentImage[];
  momentId?: string;
  visibility: C19MomentVisibility;
};

function publicationErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "登录状态已失效，请重新登录。";
    if (error.status === 403 || error.status === 404) {
      return "当前朋友圈草稿或可见范围已不可用。";
    }
    if (error.status === 409) return error.message || "朋友圈幂等状态发生冲突。";
    if (error.status === 413) return "图片或朋友圈内容超过服务端限制。";
    if (error.status === 415) return "所选图片类型不受支持。";
    if (error.status === 422) return error.message || "朋友圈内容不符合发布规则。";
    if (error.status === 429) return "发布过于频繁，请稍后再试。";
    if (error.status >= 500) return "朋友圈服务暂时不可用，本次发布没有被假定为成功。";
    return error.message || "朋友圈发布未完成。";
  }
  return error instanceof Error && error.message
    ? error.message
    : "朋友圈发布未完成，可使用相同编号安全重试。";
}

function requireUsableAssetState(asset: C19Asset) {
  if (asset.status === "active") return;
  if (asset.status === "rejected" || asset.status === "quarantined") {
    throw new C19AssetTransferError("安全扫描拒绝了这张图片；朋友圈没有发布。");
  }
  if (
    asset.status === "deleted" ||
    asset.status === "delete_pending" ||
    asset.status === "expired"
  ) {
    throw new C19AssetTransferError("朋友圈图片草稿已失效，请取消后重新选择。");
  }
}

function requireMatchingAsset(
  asset: C19Asset,
  pending: C19PendingMomentImage,
) {
  if (
    asset.client_asset_id !== pending.clientAssetId ||
    asset.kind !== "image" ||
    asset.filename !== pending.filename ||
    asset.media_type !== pending.mediaType ||
    asset.size_bytes !== pending.sizeBytes ||
    asset.sha256_hex !== pending.sha256Hex
  ) {
    throw new C19AssetTransferError(
      "资产服务返回的朋友圈图片快照不一致，已停止发布。",
    );
  }
}

export function C19MomentComposer({
  onPublished,
  profile,
}: {
  onPublished: (moment: C19Moment) => void;
  profile: C19Profile;
}) {
  const [content, setContent] = useState("");
  const [visibility, setVisibility] =
    useState<C19MomentVisibility>("public");
  const [audienceAffiliationIds, setAudienceAffiliationIds] = useState<string[]>([]);
  const [images, setImages] = useState<C19PendingMomentImage[]>([]);
  const [pending, setPending] = useState<PendingPublication | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const imagesRef = useRef<C19PendingMomentImage[]>([]);
  const pendingRef = useRef<PendingPublication | null>(null);
  const operationRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const publishingRef = useRef(false);

  const setCurrentImages = useCallback((next: C19PendingMomentImage[]) => {
    imagesRef.current = next;
    setImages(next);
  }, []);

  const rememberPending = useCallback((next: PendingPublication | null) => {
    pendingRef.current = next;
    setPending(next);
    if (next) setCurrentImages(next.images);
  }, [setCurrentImages]);

  const revokeImages = useCallback((values: C19PendingMomentImage[]) => {
    for (const image of values) URL.revokeObjectURL(image.previewUrl);
  }, []);

  const resetComposer = useCallback(
    (abort = true) => {
      operationRef.current += 1;
      if (abort) abortRef.current?.abort();
      abortRef.current = null;
      publishingRef.current = false;
      setIsPublishing(false);
      const volatile = pendingRef.current?.images ?? imagesRef.current;
      revokeImages(volatile);
      pendingRef.current = null;
      setPending(null);
      setCurrentImages([]);
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
    [revokeImages, setCurrentImages],
  );

  useEffect(() => {
    const dispose = () => {
      abortRef.current?.abort();
      revokeImages(pendingRef.current?.images ?? imagesRef.current);
    };
    window.addEventListener("pagehide", dispose);
    return () => {
      window.removeEventListener("pagehide", dispose);
      dispose();
    };
  }, [revokeImages]);

  useEffect(() => {
    const activeIds = profile.affiliations.map((item) => item.affiliation_id);
    setAudienceAffiliationIds((current) =>
      retainC19MomentAudienceAffiliations(current, activeIds),
    );
  }, [profile.affiliations]);

  useEffect(() => {
    if (profile.affiliations.length === 0 && visibility === "org") {
      setVisibility("public");
      setError("");
    }
  }, [profile.affiliations.length, visibility]);

  const selectImages = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files ?? []);
      event.target.value = "";
      if (files.length === 0 || pendingRef.current || publishingRef.current) return;
      const createdPreviewUrls: string[] = [];
      try {
        assertC19MomentImageCount(imagesRef.current.length, files.length);
        const inspectedFiles = files.map((file) => ({
          file,
          inspected: assertC19MomentImageSelection(
            inspectC19AssetSelection(file),
          ),
        }));
        const added = inspectedFiles.map(({ file, inspected }) => {
          const previewUrl = URL.createObjectURL(file);
          createdPreviewUrls.push(previewUrl);
          return {
            ...inspected,
            clientAssetId: makeC19ClientAssetId(),
            file,
            previewUrl,
            progress: 0,
            status: "selected",
            statusText: "等待发布",
          } satisfies C19PendingMomentImage;
        });
        setCurrentImages([...imagesRef.current, ...added]);
        setError("");
      } catch (selectionError) {
        for (const previewUrl of createdPreviewUrls) {
          URL.revokeObjectURL(previewUrl);
        }
        setError(
          selectionError instanceof Error && selectionError.message
            ? selectionError.message
            : "无法选择这些朋友圈图片。",
        );
      }
    },
    [setCurrentImages],
  );

  const removeImage = useCallback(
    (clientAssetId: string) => {
      if (pendingRef.current || publishingRef.current) return;
      const target = imagesRef.current.find(
        (image) => image.clientAssetId === clientAssetId,
      );
      if (target) URL.revokeObjectURL(target.previewUrl);
      setCurrentImages(
        imagesRef.current.filter((image) => image.clientAssetId !== clientAssetId),
      );
    },
    [setCurrentImages],
  );

  const transmit = useCallback(
    async (publication: PendingPublication) => {
      if (publishingRef.current) return;
      publishingRef.current = true;
      setIsPublishing(true);
      setError("");
      const operation = operationRef.current + 1;
      operationRef.current = operation;
      const controller = new AbortController();
      abortRef.current?.abort();
      abortRef.current = controller;
      let current = publication;

      const isCurrent = () =>
        operationRef.current === operation && !controller.signal.aborted;
      const updatePublication = (next: PendingPublication) => {
        current = next;
        if (isCurrent()) rememberPending(next);
      };
      const updateImage = (
        imageIndex: number,
        patch: Partial<C19PendingMomentImage>,
      ) => {
        const nextImages = current.images.map((image, index) =>
          index === imageIndex ? { ...image, ...patch } : image,
        );
        updatePublication({ ...current, images: nextImages });
        return nextImages[imageIndex];
      };

      try {
        const draft = await createC19MomentDraft(
          { client_moment_id: current.clientMomentId },
          controller.signal,
        );
        if (draft.client_moment_id !== current.clientMomentId) {
          throw new Error("朋友圈草稿幂等响应不一致，已停止发布。");
        }
        if (current.momentId && current.momentId !== draft.moment_id) {
          throw new Error("朋友圈草稿编号发生冲突，已停止发布。");
        }
        updatePublication({ ...current, momentId: draft.moment_id });
        if (draft.state === "delete_pending" || draft.state === "deleted") {
          throw new C19AssetTransferError(
            "原朋友圈草稿已经删除，请取消后重新发布。",
            410,
          );
        }

        for (
          let index = 0;
          draft.state !== "published" && index < current.images.length;
          index += 1
        ) {
          let pendingImage = current.images[index];
          if (!pendingImage.sha256Hex) {
            pendingImage = updateImage(index, {
              progress: 0,
              status: "hashing",
              statusText: "本机计算 SHA-256",
            });
            const sha256Hex = await sha256C19File(
              pendingImage.file,
              controller.signal,
            );
            pendingImage = updateImage(index, { sha256Hex });
          }
          const sha256Hex = pendingImage.sha256Hex;
          if (!sha256Hex) throw new Error("朋友圈图片校验失败。");

          pendingImage = updateImage(index, {
            progress: 0,
            status: "intent",
            statusText: "申请一次性上传票",
          });
          const intent = await createC19MomentAssetUploadIntent(
            draft.moment_id,
            {
              client_asset_id: pendingImage.clientAssetId,
              filename: pendingImage.filename,
              kind: "image",
              media_type: pendingImage.mediaType,
              sha256_hex: sha256Hex,
              size_bytes: pendingImage.sizeBytes,
            },
            controller.signal,
          );
          if (intent.moment_id !== draft.moment_id) {
            throw new Error("朋友圈图片草稿范围不一致，已停止发布。");
          }
          if (pendingImage.assetId && pendingImage.assetId !== intent.asset.asset_id) {
            throw new Error("朋友圈图片幂等响应不一致，已停止发布。");
          }
          pendingImage = updateImage(index, { assetId: intent.asset.asset_id });
          let remoteAsset = intent.asset;
          requireMatchingAsset(remoteAsset, pendingImage);
          requireUsableAssetState(remoteAsset);

          if (remoteAsset.status === "pending_upload") {
            if (!intent.upload_locator) {
              throw new Error("资产服务没有为朋友圈图片签发上传票。");
            }
            pendingImage = updateImage(index, {
              progress: 0,
              status: "uploading",
              statusText: `顺序上传第 ${index + 1}/${current.images.length} 张`,
            });
            await putC19AssetBytes({
              file: pendingImage.file,
              locator: assertC19UploadLocator(intent.upload_locator),
              onProgress: (progress) => {
                if (isCurrent()) {
                  updateImage(index, {
                    progress,
                    status: "uploading",
                    statusText: `顺序上传第 ${index + 1}/${current.images.length} 张：${progress}%`,
                  });
                }
              },
              signal: controller.signal,
            });
            remoteAsset = await finalizeC19MomentAssetUpload(
              draft.moment_id,
              remoteAsset.asset_id,
              controller.signal,
            );
            pendingImage = current.images[index];
            requireMatchingAsset(remoteAsset, pendingImage);
            requireUsableAssetState(remoteAsset);
          }

          let polls = 0;
          while (remoteAsset.status !== "active") {
            if (polls >= ASSET_SCAN_POLL_LIMIT) {
              throw new Error("朋友圈图片安全扫描仍未完成，可使用相同草稿安全重试。");
            }
            pendingImage = updateImage(index, {
              progress: 100,
              status: "scanning",
              statusText: "隔离扫描与格式校验中",
            });
            await waitForC19AssetPoll(controller.signal);
            remoteAsset = await getC19MomentAssetStatus(
              draft.moment_id,
              remoteAsset.asset_id,
              controller.signal,
            );
            requireMatchingAsset(remoteAsset, pendingImage);
            requireUsableAssetState(remoteAsset);
            polls += 1;
          }
          updateImage(index, {
            progress: 100,
            status: "active",
            statusText: "安全扫描通过",
          });
        }

        const assetIds = current.images.map((image) => {
          if (!image.assetId) throw new Error("朋友圈图片缺少服务端编号。");
          return image.assetId;
        });
        const published = await publishC19Moment(
          draft.moment_id,
          {
            asset_ids: assetIds,
            audience_affiliation_ids:
              current.visibility === "org"
                ? current.audienceAffiliationIds
                : undefined,
            content: current.content,
            visibility: current.visibility,
          },
          controller.signal,
        );
        if (!isCurrent()) return;
        resetComposer(false);
        setContent("");
        setError("");
        onPublished(published);
      } catch (transmitError) {
        if (!isCurrent()) return;
        const message = publicationErrorMessage(transmitError);
        setError(message);
        updatePublication({
          ...current,
          images: current.images.map((image) =>
            image.status === "active"
              ? image
              : { ...image, status: "failed", statusText: message },
          ),
        });
      } finally {
        if (operationRef.current === operation) {
          publishingRef.current = false;
          setIsPublishing(false);
        }
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [onPublished, rememberPending, resetComposer],
  );

  const submit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const existing = pendingRef.current;
      if (existing) {
        void transmit(existing);
        return;
      }
      const normalizedContent = content.trim();
      if (!normalizedContent && imagesRef.current.length === 0) {
        setError("请填写文字或选择至少一张图片。");
        return;
      }
      if (visibility === "org" && audienceAffiliationIds.length === 0) {
        setError("组织可见朋友圈必须至少选择一个当前有效组织身份。");
        return;
      }
      const next = {
        audienceAffiliationIds:
          visibility === "org" ? [...audienceAffiliationIds] : [],
        clientMomentId: makeC19ClientMomentId(),
        content: normalizedContent,
        images: imagesRef.current,
        visibility,
      } satisfies PendingPublication;
      rememberPending(next);
      void transmit(next);
    },
    [audienceAffiliationIds, content, rememberPending, transmit, visibility],
  );

  const renderedImages = pending?.images ?? images;

  return (
    <form className={styles.momentComposer} onSubmit={submit}>
      <div className={styles.composerHeading}>
        <div>
          <span>朋友圈发布器</span>
          <h3>{profile.display_name}</h3>
        </div>
        <ShieldCheck aria-hidden="true" size={21} />
      </div>

      <textarea
        aria-label="朋友圈文字"
        disabled={Boolean(pending)}
        maxLength={C19_MOMENT_CONTENT_MAX_LENGTH}
        onChange={(event) => setContent(event.target.value)}
        placeholder="分享进度、想法或图片…"
        rows={5}
        value={content}
      />
      <div className={styles.characterCount}>
        {content.length}/{C19_MOMENT_CONTENT_MAX_LENGTH}
      </div>

      <fieldset className={styles.visibilityPicker} disabled={Boolean(pending)}>
        <legend>谁可以看</legend>
        {(
          [
            ["public", "所有 C19 用户"],
            ["org", "指定组织"],
            ["friends", "好友"],
            ["private", "仅自己"],
          ] as const
        ).map(([value, label]) => (
          <label key={value}>
            <input
              checked={visibility === value}
              disabled={value === "org" && profile.affiliations.length === 0}
              name="moment-visibility"
              onChange={() => setVisibility(value)}
              type="radio"
              value={value}
            />
            {label}
            {value === "org" && profile.affiliations.length === 0
              ? "（暂无组织资料）"
              : ""}
          </label>
        ))}
      </fieldset>

      {visibility === "org" ? (
        <fieldset className={styles.audiencePicker} disabled={Boolean(pending)}>
          <legend>选择当前有效组织（可多选）</legend>
          {profile.affiliations.map((affiliation) => (
            <label key={affiliation.affiliation_id}>
              <input
                checked={audienceAffiliationIds.includes(affiliation.affiliation_id)}
                onChange={(event) => {
                  if (
                    event.target.checked &&
                    audienceAffiliationIds.length >=
                      C19_MOMENT_MAX_AUDIENCE_AFFILIATIONS
                  ) {
                    setError(
                      `每条组织可见朋友圈最多选择 ${C19_MOMENT_MAX_AUDIENCE_AFFILIATIONS} 个组织身份。`,
                    );
                    return;
                  }
                  setError("");
                  setAudienceAffiliationIds((current) =>
                    event.target.checked
                      ? [...new Set([...current, affiliation.affiliation_id])]
                      : current.filter(
                          (item) => item !== affiliation.affiliation_id,
                        ),
                  );
                }}
                type="checkbox"
              />
              <span>{affiliation.org_name}</span>
              <small>{affiliation.role}</small>
            </label>
          ))}
        </fieldset>
      ) : null}

      <input
        accept={C19_MOMENT_IMAGE_ACCEPT}
        aria-label="选择朋友圈图片"
        className={styles.hiddenFileInput}
        disabled={Boolean(pending) || images.length >= C19_MOMENT_MAX_IMAGES}
        multiple
        onChange={selectImages}
        ref={fileInputRef}
        type="file"
      />
      <button
        className={styles.addImagesButton}
        disabled={Boolean(pending) || images.length >= C19_MOMENT_MAX_IMAGES}
        onClick={() => fileInputRef.current?.click()}
        type="button"
      >
        <ImagePlus aria-hidden="true" size={16} />
        选择图片（{renderedImages.length}/{C19_MOMENT_MAX_IMAGES}）
      </button>

      {renderedImages.length > 0 ? (
        <div className={styles.selectedMomentImages}>
          {renderedImages.map((image) => (
            <article key={image.clientAssetId}>
              <img alt={`${image.filename} 本地预览`} src={image.previewUrl} />
              <div>
                <strong title={image.filename}>{image.filename}</strong>
                <span>{image.statusText}</span>
                {image.status === "uploading" ? (
                  <progress max={100} value={image.progress}>{image.progress}%</progress>
                ) : null}
              </div>
              <button
                aria-label={`移除 ${image.filename}`}
                disabled={Boolean(pending)}
                onClick={() => removeImage(image.clientAssetId)}
                type="button"
              >
                <X aria-hidden="true" size={14} />
              </button>
            </article>
          ))}
        </div>
      ) : null}

      {error ? <div className={styles.runtimeError} role="alert">{error}</div> : null}
      {pending && error ? (
        <div className={styles.retryNotice}>
          <span>重试会复用同一草稿、图片和发布幂等编号，不会制造重复朋友圈。</span>
          <button
            disabled={isPublishing}
            onClick={() => {
              resetComposer();
              setError("");
            }}
            type="button"
          >
            取消本次草稿
          </button>
        </div>
      ) : null}

      <button
        className={styles.publishButton}
        disabled={
          isPublishing ||
          (!pending && !content.trim() && renderedImages.length === 0) ||
          (visibility === "org" && audienceAffiliationIds.length === 0)
        }
        type="submit"
      >
        {isPublishing ? (
          <LoaderCircle aria-hidden="true" className={styles.spinner} size={17} />
        ) : (
          <Send aria-hidden="true" size={16} />
        )}
        {isPublishing ? "安全发布中…" : pending ? "安全重试" : "发布朋友圈"}
      </button>
      <small className={styles.composerBoundary}>
        图片按选择顺序逐张直传隔离资产服务；JSON 代理不接触图片字节。
      </small>
    </form>
  );
}

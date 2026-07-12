"use client";

import { Download, FileText, ImageIcon, RefreshCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { createC19AssetAccessIntent } from "./api";
import { assertC19DownloadLocator } from "./C19AssetTransfer";
import styles from "./C19Workspace.module.css";
import type { C19AssetReference } from "./types";

function readableAssetSize(sizeBytes: number) {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KiB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function triggerAttachmentDownload(locator: string, filename: string) {
  const link = document.createElement("a");
  link.href = locator;
  link.download = filename;
  link.rel = "noreferrer";
  document.body.append(link);
  link.click();
  link.remove();
}

export function C19MessageAsset({
  asset,
  conversationId,
  recordId,
}: {
  asset: C19AssetReference;
  conversationId: string;
  recordId: string;
}) {
  const viewportTargetRef = useRef<HTMLDivElement | null>(null);
  const activeRef = useRef(true);
  const thumbnailRequestedRef = useRef(false);
  const thumbnailAbortRef = useRef<AbortController | null>(null);
  const downloadAbortRef = useRef<AbortController | null>(null);
  const [thumbnailLocator, setThumbnailLocator] = useState("");
  const [thumbnailLoading, setThumbnailLoading] = useState(false);
  const [thumbnailError, setThumbnailError] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const [downloading, setDownloading] = useState(false);

  const requestThumbnail = useCallback(async () => {
    if (asset.kind !== "image" || thumbnailRequestedRef.current) return;
    thumbnailRequestedRef.current = true;
    setThumbnailLoading(true);
    setThumbnailError("");
    const controller = new AbortController();
    thumbnailAbortRef.current?.abort();
    thumbnailAbortRef.current = controller;
    try {
      const intent = await createC19AssetAccessIntent(
        conversationId,
        recordId,
        asset.asset_id,
        "thumbnail",
        controller.signal,
      );
      if (!activeRef.current || controller.signal.aborted) return;
      setThumbnailLocator(assertC19DownloadLocator(intent.download_locator));
    } catch (error) {
      if (!activeRef.current || controller.signal.aborted) return;
      thumbnailRequestedRef.current = false;
      setThumbnailError(
        error instanceof Error && error.message
          ? error.message
          : "图片预览暂时不可用。",
      );
    } finally {
      if (activeRef.current && !controller.signal.aborted) {
        setThumbnailLoading(false);
      }
    }
  }, [asset.asset_id, asset.kind, conversationId, recordId]);

  useEffect(() => {
    activeRef.current = true;
    if (asset.kind !== "image") return;
    const target = viewportTargetRef.current;
    if (!target) return;
    if (typeof IntersectionObserver === "undefined") {
      setThumbnailError("当前浏览器不支持自动预览，可点击下载原图。");
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          void requestThumbnail();
        }
      },
      { rootMargin: "0px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [asset.kind, requestThumbnail]);

  useEffect(
    () => () => {
      activeRef.current = false;
      thumbnailAbortRef.current?.abort();
      downloadAbortRef.current?.abort();
    },
    [],
  );

  const downloadOriginal = useCallback(async () => {
    if (downloading) return;
    setDownloading(true);
    setDownloadError("");
    const controller = new AbortController();
    downloadAbortRef.current?.abort();
    downloadAbortRef.current = controller;
    try {
      const intent = await createC19AssetAccessIntent(
        conversationId,
        recordId,
        asset.asset_id,
        "original",
        controller.signal,
      );
      if (!activeRef.current || controller.signal.aborted) return;
      triggerAttachmentDownload(
        assertC19DownloadLocator(intent.download_locator),
        asset.filename,
      );
    } catch (error) {
      if (!activeRef.current || controller.signal.aborted) return;
      setDownloadError(
        error instanceof Error && error.message
          ? error.message
          : "文件访问票签发失败。",
      );
    } finally {
      if (activeRef.current && !controller.signal.aborted) setDownloading(false);
    }
  }, [asset.asset_id, asset.filename, conversationId, downloading, recordId]);

  if (asset.kind === "image") {
    return (
      <div className={styles.messageAsset} ref={viewportTargetRef}>
        <div className={styles.messageImageFrame}>
          {thumbnailLocator ? (
            <img
              alt={asset.filename}
              decoding="async"
              loading="lazy"
              onError={() => {
                setThumbnailLocator("");
                thumbnailRequestedRef.current = false;
                setThumbnailError("图片预览票已失效，可重新加载。");
              }}
              src={thumbnailLocator}
            />
          ) : (
            <span>
              <ImageIcon aria-hidden="true" size={22} />
              {thumbnailLoading ? "安全预览加载中…" : "图片预览"}
            </span>
          )}
        </div>
        <div className={styles.messageAssetMeta}>
          <span title={asset.filename}>{asset.filename}</span>
          <small>{readableAssetSize(asset.size_bytes)}</small>
        </div>
        <div className={styles.messageAssetActions}>
          {thumbnailError ? (
            <button onClick={() => void requestThumbnail()} type="button">
              <RefreshCcw aria-hidden="true" size={13} />重新预览
            </button>
          ) : null}
          <button disabled={downloading} onClick={() => void downloadOriginal()} type="button">
            <Download aria-hidden="true" size={13} />
            {downloading ? "签发中…" : "下载原图"}
          </button>
        </div>
        {thumbnailError ? <small className={styles.assetInlineError}>{thumbnailError}</small> : null}
        {downloadError ? <small className={styles.assetInlineError}>{downloadError}</small> : null}
      </div>
    );
  }

  return (
    <div className={styles.messageAsset}>
      <div className={styles.fileAttachment}>
        <FileText aria-hidden="true" size={22} />
        <div>
          <strong title={asset.filename}>{asset.filename}</strong>
          <span>{readableAssetSize(asset.size_bytes)} · 点击后签发短时下载票</span>
        </div>
      </div>
      <div className={styles.messageAssetActions}>
        <button disabled={downloading} onClick={() => void downloadOriginal()} type="button">
          <Download aria-hidden="true" size={13} />
          {downloading ? "签发中…" : "下载文件"}
        </button>
      </div>
      {downloadError ? <small className={styles.assetInlineError}>{downloadError}</small> : null}
    </div>
  );
}

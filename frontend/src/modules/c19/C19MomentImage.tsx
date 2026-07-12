"use client";

import { Download, Expand, ImageIcon, RefreshCcw, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

import { createC19MomentAssetAccessIntent } from "./api";
import { assertC19DownloadLocator } from "./C19AssetTransfer";
import styles from "./C19Moments.module.css";
import type { C19AssetReference } from "./types";

function triggerImageDownload(locator: string, filename: string) {
  const link = document.createElement("a");
  link.href = locator;
  link.download = filename;
  link.rel = "noreferrer";
  document.body.append(link);
  link.click();
  link.remove();
}

export function C19MomentImage({
  asset,
  momentId,
  onUnavailable,
}: {
  asset: C19AssetReference;
  momentId: string;
  onUnavailable: () => void;
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const activeRef = useRef(true);
  const thumbnailRequestedRef = useRef(false);
  const thumbnailAbortRef = useRef<AbortController | null>(null);
  const originalAbortRef = useRef<AbortController | null>(null);
  const [thumbnailLocator, setThumbnailLocator] = useState("");
  const [originalLocator, setOriginalLocator] = useState("");
  const [thumbnailLoading, setThumbnailLoading] = useState(false);
  const [originalLoading, setOriginalLoading] = useState(false);
  const [error, setError] = useState("");

  const requestAccess = useCallback(
    async (variant: "thumbnail" | "original") => {
      const controller = new AbortController();
      if (variant === "thumbnail") {
        thumbnailAbortRef.current?.abort();
        thumbnailAbortRef.current = controller;
        setThumbnailLoading(true);
      } else {
        originalAbortRef.current?.abort();
        originalAbortRef.current = controller;
        setOriginalLoading(true);
      }
      setError("");
      try {
        const intent = await createC19MomentAssetAccessIntent(
          momentId,
          asset.asset_id,
          variant,
          controller.signal,
        );
        if (!activeRef.current || controller.signal.aborted) return "";
        const locator = assertC19DownloadLocator(intent.download_locator);
        if (variant === "thumbnail") setThumbnailLocator(locator);
        else setOriginalLocator(locator);
        return locator;
      } catch (accessError) {
        if (!activeRef.current || controller.signal.aborted) return "";
        if (
          accessError instanceof ApiError &&
          (accessError.status === 403 || accessError.status === 404)
        ) {
          onUnavailable();
          return "";
        }
        if (variant === "thumbnail") thumbnailRequestedRef.current = false;
        setError(
          accessError instanceof Error && accessError.message
            ? accessError.message
            : "这张图片暂时不可用。",
        );
        return "";
      } finally {
        if (activeRef.current && !controller.signal.aborted) {
          if (variant === "thumbnail") setThumbnailLoading(false);
          else setOriginalLoading(false);
        }
      }
    },
    [asset.asset_id, momentId, onUnavailable],
  );

  const requestThumbnail = useCallback(async () => {
    if (thumbnailRequestedRef.current) return;
    thumbnailRequestedRef.current = true;
    await requestAccess("thumbnail");
  }, [requestAccess]);

  useEffect(() => {
    activeRef.current = true;
    const target = viewportRef.current;
    if (!target) return;
    if (typeof IntersectionObserver === "undefined") {
      void requestThumbnail();
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          void requestThumbnail();
        }
      },
      { rootMargin: "120px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [requestThumbnail]);

  useEffect(
    () => () => {
      activeRef.current = false;
      thumbnailAbortRef.current?.abort();
      originalAbortRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (!originalLocator) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOriginalLocator("");
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [originalLocator]);

  return (
    <div className={styles.momentImage} ref={viewportRef}>
      {thumbnailLocator ? (
        <button
          aria-label={`查看原图：${asset.filename}`}
          className={styles.momentImageButton}
          onClick={() => void requestAccess("original")}
          type="button"
        >
          <img
            alt={asset.filename}
            decoding="async"
            loading="lazy"
            onError={() => {
              setThumbnailLocator("");
              thumbnailRequestedRef.current = false;
              setError("图片预览票已失效，可重新加载。");
            }}
            src={thumbnailLocator}
          />
          <span><Expand aria-hidden="true" size={14} />查看原图</span>
        </button>
      ) : (
        <div className={styles.momentImagePlaceholder}>
          <ImageIcon aria-hidden="true" size={24} />
          <span>{thumbnailLoading ? "安全预览加载中…" : "图片预览"}</span>
          {!thumbnailLoading && error ? (
            <button onClick={() => void requestThumbnail()} type="button">
              <RefreshCcw aria-hidden="true" size={13} />重试
            </button>
          ) : null}
        </div>
      )}
      {originalLoading ? <span className={styles.imageLoading}>正在签发原图票…</span> : null}
      {error && thumbnailLocator ? <small className={styles.inlineError}>{error}</small> : null}

      {originalLocator ? (
        <div
          aria-label={`原图预览：${asset.filename}`}
          aria-modal="true"
          className={styles.lightbox}
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) setOriginalLocator("");
          }}
          role="dialog"
        >
          <div className={styles.lightboxToolbar}>
            <button
              onClick={() => triggerImageDownload(originalLocator, asset.filename)}
              type="button"
            >
              <Download aria-hidden="true" size={15} />下载原图
            </button>
            <button
              aria-label="关闭原图预览"
              autoFocus
              onClick={() => setOriginalLocator("")}
              type="button"
            >
              <X aria-hidden="true" size={17} />
            </button>
          </div>
          <img
            alt={asset.filename}
            decoding="async"
            onError={() => {
              setOriginalLocator("");
              setError("原图访问票已失效，请重新打开。");
            }}
            src={originalLocator}
          />
        </div>
      ) : null}
    </div>
  );
}

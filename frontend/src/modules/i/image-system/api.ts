"use client";

import type {
  IEditResponse,
  IGenerateResponse,
  IImageCandidate,
  IMediaListResponse,
  ISaveMediaResponse,
  ISourceType,
} from "./types";
import { apiRequest } from "@/lib/api";

/**
 * 出图的超时预算。两个接口都是**同步等模型返回**（gpt-image-2 出一张
 * 几十秒起步，多张更久），不是派单。收口前它们一个超时都没有；
 * `lib/api.ts` 给非 GET 的默认值是 15 秒，照默认走这两个按钮必然失败。
 */
const IMAGE_GENERATION_TIMEOUT_MS = 300_000;

// 只剩给媒体库文件/缩略图/预览拼 URL 在用（不是发请求）。
const API_PROXY_BASE = "/api/backend";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

export function imageDataUrl(candidate: Pick<IImageCandidate, "image_base64" | "mime_type">) {
  return `data:${candidate.mime_type};base64,${candidate.image_base64}`;
}

export async function generateImages(payload: {
  prompt: string;
  style_config: Record<string, unknown>;
  aspect_ratio: string;
  generation_count: number;
  product_id?: string | null;
  variant_id?: string | null;
  origin_context?: "i_direct" | "k_handoff";
}): Promise<IGenerateResponse> {
  return apiRequest<IGenerateResponse>("/i/images/generate", {
    body: payload,
    method: "POST",
    timeoutMs: IMAGE_GENERATION_TIMEOUT_MS,
  });
}

export async function editImages(payload: {
  prompt: string;
  style_config: Record<string, unknown>;
  aspect_ratio: string;
  generation_count: number;
  files: File[];
  product_id?: string | null;
  variant_id?: string | null;
  origin_context?: "i_direct" | "k_handoff";
}): Promise<IEditResponse> {
  const formData = new FormData();
  formData.append("prompt", payload.prompt);
  formData.append("style_config", JSON.stringify(payload.style_config));
  formData.append("aspect_ratio", payload.aspect_ratio);
  formData.append("generation_count", String(payload.generation_count));
  if (payload.product_id) {
    formData.append("product_id", payload.product_id);
  }
  if (payload.variant_id) {
    formData.append("variant_id", payload.variant_id);
  }
  if (payload.origin_context) {
    formData.append("origin_context", payload.origin_context);
  }
  for (const file of payload.files) {
    formData.append("files", file);
  }

  // FormData 直接交给 apiRequest：它不会 JSON.stringify，也不会手动设
  // Content-Type（multipart 的 boundary 由 fetch 自己按 FormData 生成，
  // 手动设就没了）。并发上传也不会再被 in-flight 去重合并 ——
  // 这两条都是 2026-09-02 收口时先补进 lib/api.ts + request-cache.ts 的。
  return apiRequest<IEditResponse>("/i/images/edit", {
    body: formData,
    method: "POST",
    timeoutMs: IMAGE_GENERATION_TIMEOUT_MS,
  });
}

export async function saveToMediaLibrary(payload: {
  source_type: ISourceType;
  prompt_original?: string | null;
  image_prompt_enhanced: string;
  style_config: Record<string, unknown>;
  aspect_ratio?: string | null;
  product_id?: string | null;
  variant_id?: string | null;
  images: IImageCandidate[];
}): Promise<ISaveMediaResponse> {
  return apiRequest<ISaveMediaResponse>("/i/media-library", {
    body: {
      ...payload,
      origin_context: "i_direct",
      images: payload.images.map((candidate) => ({
        candidate_id: candidate.candidate_id,
        content_sha256: candidate.content_sha256,
        height: candidate.height,
        image_base64: candidate.image_base64,
        metadata: candidate.metadata,
        mime_type: candidate.mime_type,
        width: candidate.width,
      })),
    },
    method: "POST",
    timeoutMs: 60_000,
  });
}

export async function getMediaLibrary(options?: {
  product_id?: string;
  variant_id?: string;
  source_type?: ISourceType | "";
  limit?: number;
  offset?: number;
}): Promise<IMediaListResponse> {
  const params = new URLSearchParams();
  if (options?.product_id?.trim()) {
    params.set("product_id", options.product_id.trim());
  }
  if (options?.variant_id?.trim()) {
    params.set("variant_id", options.variant_id.trim());
  }
  if (options?.source_type) {
    params.set("source_type", options.source_type);
  }
  if (options?.limit) {
    params.set("limit", String(options.limit));
  }
  if (options?.offset) {
    params.set("offset", String(options.offset));
  }

  const suffix = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<IMediaListResponse>(`/i/media-library${suffix}`, {
    timeoutMs: 20_000,
  });
}

export function iMediaFileUrl(assetId: string) {
  return `${API_PROXY_BASE}/i/media-library/${encodeURIComponent(assetId)}/file`;
}

export function iMediaThumbnailUrl(assetId: string) {
  return `${API_PROXY_BASE}/i/media-library/${encodeURIComponent(assetId)}/thumbnail`;
}

export function iMediaPreviewUrl(assetId: string) {
  return `${API_PROXY_BASE}/i/media-library/${encodeURIComponent(assetId)}/preview`;
}

export async function deleteMediaAsset(assetId: string): Promise<void> {
  await apiRequest<unknown>(`/i/media-library/${encodeURIComponent(assetId)}`, {
    method: "DELETE",
    timeoutMs: 20_000,
  });
}

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

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

class IImageApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "IImageApiError";
  }
}

function readAccessToken() {
  if (typeof window === "undefined") {
    return null;
  }

  return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
}

function buildHeaders(hasBody = false) {
  const headers = new Headers({ Accept: "application/json" });
  const accessToken = readAccessToken();

  if (hasBody) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  return headers;
}

async function errorMessage(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (
      payload.detail &&
      typeof payload.detail === "object" &&
      "message" in payload.detail
    ) {
      const detail = payload.detail as Record<string, unknown>;
      return typeof detail.message === "string" ? detail.message : "I 图片请求失败。";
    }
  } catch {
    // Keep fallback stable for non-JSON responses.
  }

  return "I 图片请求失败。";
}

async function readJson<T>(response: Response): Promise<T> {
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }
  if (!response.ok) {
    throw new IImageApiError(await errorMessage(response), response.status);
  }
  return (await response.json()) as T;
}

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
  const response = await fetch(`${API_PROXY_BASE}/i/images/generate`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });

  return readJson<IGenerateResponse>(response);
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

  const response = await fetch(`${API_PROXY_BASE}/i/images/edit`, {
    body: formData,
    cache: "no-store",
    headers: buildHeaders(),
    method: "POST",
  });

  return readJson<IEditResponse>(response);
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

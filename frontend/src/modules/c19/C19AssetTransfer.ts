import type { C19AssetKind } from "./types";

export const C19_IMAGE_MAX_BYTES = 20 * 1024 * 1024;
export const C19_FILE_MAX_BYTES = 50 * 1024 * 1024;
export const C19_ASSET_ACCEPT = [
  ".jpg",
  ".jpeg",
  ".png",
  ".webp",
  ".gif",
  ".pdf",
  ".txt",
  ".csv",
  ".docx",
  ".xlsx",
  ".pptx",
  ".zip",
].join(",");

const MEDIA_BY_EXTENSION = new Map<
  string,
  { kind: C19AssetKind; mediaType: string }
>([
  [".jpg", { kind: "image", mediaType: "image/jpeg" }],
  [".jpeg", { kind: "image", mediaType: "image/jpeg" }],
  [".png", { kind: "image", mediaType: "image/png" }],
  [".webp", { kind: "image", mediaType: "image/webp" }],
  [".gif", { kind: "image", mediaType: "image/gif" }],
  [".pdf", { kind: "file", mediaType: "application/pdf" }],
  [".txt", { kind: "file", mediaType: "text/plain" }],
  [".csv", { kind: "file", mediaType: "text/csv" }],
  [
    ".docx",
    {
      kind: "file",
      mediaType:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
  ],
  [
    ".xlsx",
    {
      kind: "file",
      mediaType:
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
  ],
  [
    ".pptx",
    {
      kind: "file",
      mediaType:
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    },
  ],
  [".zip", { kind: "file", mediaType: "application/zip" }],
]);

const BIDI_OR_DIRECTIONAL_CONTROL =
  /[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u;
const UPLOAD_LOCATOR_PATTERN =
  /^\/api\/backend\/c19-assets\/u\/[A-Za-z0-9_-]{43}$/;
const DOWNLOAD_LOCATOR_PATTERN =
  /^\/api\/backend\/c19-assets\/d\/[A-Za-z0-9_-]{43}$/;

export type C19AssetSelection = {
  filename: string;
  kind: C19AssetKind;
  mediaType: string;
  sizeBytes: number;
};

export class C19AssetTransferError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "C19AssetTransferError";
    this.status = status;
  }
}

function abortError(signal?: AbortSignal) {
  if (signal?.reason instanceof Error) return signal.reason;
  const error = new Error("Asset operation was aborted.");
  error.name = "AbortError";
  return error;
}

function fileExtension(filename: string) {
  const finalDot = filename.lastIndexOf(".");
  return finalDot <= 0 ? "" : filename.slice(finalDot).toLowerCase();
}

export function inspectC19AssetSelection(
  file: Pick<File, "name" | "size" | "type">,
): C19AssetSelection {
  const filename = file.name.normalize("NFC");
  if (
    !filename ||
    filename.length > 255 ||
    filename !== filename.trim() ||
    filename === "." ||
    filename === ".." ||
    filename.includes("/") ||
    filename.includes("\\") ||
    /[\u0000-\u001f\u007f]/u.test(filename) ||
    BIDI_OR_DIRECTIONAL_CONTROL.test(filename)
  ) {
    throw new C19AssetTransferError("文件名不符合安全规则，请重命名后再选择。");
  }

  const declaration = MEDIA_BY_EXTENSION.get(fileExtension(filename));
  if (!declaration) {
    throw new C19AssetTransferError(
      "仅支持 JPG、PNG、WebP、GIF、PDF、TXT、CSV、DOCX、XLSX、PPTX 和 ZIP。",
    );
  }
  const declaredBrowserType = file.type.trim().toLowerCase();
  const browserTypeMatchesImage =
    declaredBrowserType === declaration.mediaType ||
    (declaration.mediaType === "image/jpeg" && declaredBrowserType === "image/jpg");
  if (
    declaration.kind === "image" &&
    declaredBrowserType &&
    !browserTypeMatchesImage
  ) {
    throw new C19AssetTransferError(
      "图片扩展名与浏览器识别的类型不一致，请选择原始图片文件。",
    );
  }
  if (!Number.isSafeInteger(file.size) || file.size <= 0) {
    throw new C19AssetTransferError("不能发送空文件或无法读取大小的文件。");
  }
  const maximum =
    declaration.kind === "image" ? C19_IMAGE_MAX_BYTES : C19_FILE_MAX_BYTES;
  if (file.size > maximum) {
    throw new C19AssetTransferError(
      declaration.kind === "image"
        ? "图片不能超过 20 MiB。"
        : "普通文件不能超过 50 MiB。",
    );
  }

  return {
    filename,
    kind: declaration.kind,
    mediaType: declaration.mediaType,
    sizeBytes: file.size,
  };
}

export function makeC19ClientAssetId() {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi?.randomUUID) {
    return `client_asset_${cryptoApi.randomUUID().replaceAll("-", "")}`;
  }
  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  return `client_asset_${Array.from(bytes, (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("")}`;
}

export async function sha256C19File(file: File, signal?: AbortSignal) {
  if (signal?.aborted) throw abortError(signal);
  const bytes = await file.arrayBuffer();
  if (signal?.aborted) throw abortError(signal);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  if (signal?.aborted) throw abortError(signal);
  return Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
}

export function assertC19UploadLocator(locator: string) {
  if (!UPLOAD_LOCATOR_PATTERN.test(locator)) {
    throw new C19AssetTransferError("资产服务返回了无效的上传地址。");
  }
  return locator;
}

export function assertC19DownloadLocator(locator: string) {
  if (!DOWNLOAD_LOCATOR_PATTERN.test(locator)) {
    throw new C19AssetTransferError("资产服务返回了无效的访问地址。");
  }
  return locator;
}

/** Stream raw bytes directly to the same-origin Nginx asset data plane. */
export function putC19AssetBytes({
  file,
  locator,
  onProgress,
  signal,
}: {
  file: File;
  locator: string;
  onProgress: (percentage: number) => void;
  signal: AbortSignal;
}) {
  assertC19UploadLocator(locator);
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(abortError(signal));
      return;
    }

    const request = new XMLHttpRequest();
    let settled = false;
    const finish = (action: () => void) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", onAbort);
      action();
    };
    const onAbort = () => {
      request.abort();
      finish(() => reject(abortError(signal)));
    };

    request.open("PUT", locator, true);
    request.withCredentials = true;
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.upload.onprogress = (event) => {
      if (!event.lengthComputable || event.total <= 0) return;
      onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
    };
    request.onerror = () =>
      finish(() => reject(new C19AssetTransferError("文件上传连接中断。")));
    request.onabort = () =>
      finish(() => reject(abortError(signal)));
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress(100);
        finish(resolve);
        return;
      }
      finish(() =>
        reject(
          new C19AssetTransferError(
            request.status === 401 || request.status === 403
              ? "文件上传授权已失效，请安全重试。"
              : request.status === 413
                ? "文件实际大小超过服务端限制。"
                : "文件上传未被资产服务确认。",
            request.status,
          ),
        ),
      );
    };
    signal.addEventListener("abort", onAbort, { once: true });
    onProgress(0);
    request.send(file);
  });
}

export function waitForC19AssetPoll(
  signal: AbortSignal,
  delayMilliseconds = 1_200,
) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(abortError(signal));
      return;
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, delayMilliseconds);
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(abortError(signal));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

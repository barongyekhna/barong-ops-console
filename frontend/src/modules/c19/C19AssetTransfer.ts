import type { C19AssetKind } from "./types";

export const C19_IMAGE_MAX_BYTES = 32 * 1024 * 1024;
export const C19_FILE_MAX_BYTES = 200 * 1024 * 1024;
/** Empty: the picker shows every file; the tables below decide what is sent. */
export const C19_ASSET_ACCEPT = "";

const IMAGE_MEDIA_BY_EXTENSION = new Map<string, string>([
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".png", "image/png"],
  [".webp", "image/webp"],
  [".gif", "image/gif"],
  [".bmp", "image/bmp"],
  [".tif", "image/tiff"],
  [".tiff", "image/tiff"],
]);

// Mirrors c19_asset_service/schemas.py FILE_MEDIA_BY_EXTENSION. Anything not
// listed (and not blocked) travels as application/octet-stream, download only.
const FILE_MEDIA_BY_EXTENSION = new Map<string, string>([
  [".pdf", "application/pdf"],
  [".txt", "text/plain"],
  [".csv", "text/csv"],
  [
    ".docx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ],
  [
    ".xlsx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ],
  [
    ".pptx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ],
  [".zip", "application/zip"],
  [".doc", "application/msword"],
  [".xls", "application/vnd.ms-excel"],
  [".ppt", "application/vnd.ms-powerpoint"],
  [".rtf", "application/rtf"],
  [".odt", "application/vnd.oasis.opendocument.text"],
  [".ods", "application/vnd.oasis.opendocument.spreadsheet"],
  [".odp", "application/vnd.oasis.opendocument.presentation"],
  [".md", "text/markdown"],
  [".json", "application/json"],
  [".xml", "application/xml"],
  [".mp4", "video/mp4"],
  [".m4v", "video/x-m4v"],
  [".mov", "video/quicktime"],
  [".webm", "video/webm"],
  [".mkv", "video/x-matroska"],
  [".avi", "video/x-msvideo"],
  [".3gp", "video/3gpp"],
  [".wmv", "video/x-ms-wmv"],
  [".flv", "video/x-flv"],
  [".mpg", "video/mpeg"],
  [".mpeg", "video/mpeg"],
  [".mp3", "audio/mpeg"],
  [".wav", "audio/wav"],
  [".m4a", "audio/mp4"],
  [".aac", "audio/aac"],
  [".ogg", "audio/ogg"],
  [".flac", "audio/flac"],
  [".amr", "audio/amr"],
  [".wma", "audio/x-ms-wma"],
  [".rar", "application/vnd.rar"],
  [".7z", "application/x-7z-compressed"],
  [".tar", "application/x-tar"],
  [".gz", "application/gzip"],
  [".tgz", "application/gzip"],
  [".bz2", "application/x-bzip2"],
  [".xz", "application/x-xz"],
  [".psd", "image/vnd.adobe.photoshop"],
  [".ai", "application/postscript"],
  [".svg", "image/svg+xml"],
  [".heic", "image/heic"],
  [".heif", "image/heif"],
  [".dwg", "image/vnd.dwg"],
  [".dxf", "image/vnd.dxf"],
  [".step", "model/step"],
  [".stp", "model/step"],
  [".igs", "model/iges"],
  [".iges", "model/iges"],
  [".stl", "model/stl"],
  [".obj", "model/obj"],
]);

export const C19_OCTET_STREAM_MEDIA_TYPE = "application/octet-stream";

/** Programs and script hosts: the only things the chat refuses outright. */
const BLOCKED_EXTENSIONS = new Set([
  ".exe", ".dll", ".scr", ".com", ".bat", ".cmd", ".msi", ".msp",
  ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
  ".hta", ".lnk", ".jar", ".cpl", ".reg", ".sys", ".pif",
  ".app", ".dmg", ".apk", ".ipa", ".deb", ".rpm",
]);

export function c19AssetMediaFamily(mediaType: string) {
  if (mediaType.startsWith("video/")) return "video" as const;
  if (mediaType.startsWith("audio/")) return "audio" as const;
  if (
    mediaType === "application/zip" ||
    mediaType === "application/vnd.rar" ||
    mediaType === "application/x-7z-compressed" ||
    mediaType === "application/x-tar" ||
    mediaType === "application/gzip" ||
    mediaType === "application/x-bzip2" ||
    mediaType === "application/x-xz"
  ) {
    return "archive" as const;
  }
  return "document" as const;
}

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

  const extension = fileExtension(filename);
  if (BLOCKED_EXTENSIONS.has(extension)) {
    throw new C19AssetTransferError(
      "可执行程序和脚本不能通过聊天发送，请打包后再发或改用其他方式。",
    );
  }
  const imageMediaType = IMAGE_MEDIA_BY_EXTENSION.get(extension);
  const declaration: { kind: C19AssetKind; mediaType: string } = imageMediaType
    ? { kind: "image", mediaType: imageMediaType }
    : {
        kind: "file",
        mediaType:
          FILE_MEDIA_BY_EXTENSION.get(extension) ?? C19_OCTET_STREAM_MEDIA_TYPE,
      };
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
        ? "图片不能超过 32 MiB。"
        : "文件或视频不能超过 200 MiB。",
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

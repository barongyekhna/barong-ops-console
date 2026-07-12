import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  C19_FILE_MAX_BYTES,
  C19_IMAGE_MAX_BYTES,
  assertC19DownloadLocator,
  assertC19UploadLocator,
  inspectC19AssetSelection,
  putC19AssetBytes,
  sha256C19File,
} from "../../frontend/src/modules/c19/C19AssetTransfer.ts";
import {
  getBackendApiPath,
  isAllowedC19Path,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

const conversationId = "conv_0123456789abcdef0123456789abcdef";
const assetId = "att_0123456789abcdef0123456789abcdef";
const momentId = "mom_0123456789abcdef0123456789abcdef";
const uploadTicket = "A".repeat(43);
const downloadTicket = "b".repeat(43);

test("asset selection applies the exact Stage 4 type and size envelope", () => {
  assert.deepEqual(
    inspectC19AssetSelection({
      name: "产品图.webp",
      size: C19_IMAGE_MAX_BYTES,
      type: "image/webp",
    }),
    {
      filename: "产品图.webp",
      kind: "image",
      mediaType: "image/webp",
      sizeBytes: C19_IMAGE_MAX_BYTES,
    },
  );
  assert.deepEqual(
    inspectC19AssetSelection({
      name: "库存表.xlsx",
      size: C19_FILE_MAX_BYTES,
      type: "application/octet-stream",
    }),
    {
      filename: "库存表.xlsx",
      kind: "file",
      mediaType:
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      sizeBytes: C19_FILE_MAX_BYTES,
    },
  );
  assert.throws(
    () =>
      inspectC19AssetSelection({
        name: "too-large.png",
        size: C19_IMAGE_MAX_BYTES + 1,
        type: "image/png",
      }),
    /20 MiB/,
  );
  assert.throws(
    () =>
      inspectC19AssetSelection({
        name: "payload.svg",
        size: 10,
        type: "image/svg+xml",
      }),
    /仅支持/,
  );
  assert.throws(
    () =>
      inspectC19AssetSelection({
        name: "disguised.jpg",
        size: 10,
        type: "image/svg+xml",
      }),
    /扩展名与浏览器识别的类型不一致/,
  );
  assert.throws(
    () =>
      inspectC19AssetSelection({
        name: "..\\report.pdf",
        size: 10,
        type: "application/pdf",
      }),
    /文件名不符合安全规则/,
  );
});

test("asset transfer locators stay same-origin and SHA-256 uses Web Crypto", async () => {
  assert.equal(
    assertC19UploadLocator(`/api/backend/c19-assets/u/${uploadTicket}`),
    `/api/backend/c19-assets/u/${uploadTicket}`,
  );
  assert.equal(
    assertC19DownloadLocator(`/api/backend/c19-assets/d/${downloadTicket}`),
    `/api/backend/c19-assets/d/${downloadTicket}`,
  );
  assert.throws(() => assertC19UploadLocator("https://asset-vps.example/u/x"));
  assert.throws(() =>
    assertC19UploadLocator(`/api/c19-assets/u/${uploadTicket}`),
  );
  assert.throws(() =>
    assertC19DownloadLocator(`/api/c19-assets/d/${downloadTicket}`),
  );
  assert.throws(() => assertC19DownloadLocator("/api/backend/c19/storage/x"));

  const digest = await sha256C19File(
    new File(["abc"], "digest.txt", { type: "text/plain" }),
  );
  assert.equal(
    digest,
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
});

test("raw upload uses credentialed XHR progress and never the Next JSON path", async () => {
  const originalXhr = globalThis.XMLHttpRequest;
  const observations = { headers: {}, progress: [], sent: null, url: "" };

  class FakeXhr {
    upload = {};
    status = 204;
    withCredentials = false;

    open(method, url) {
      assert.equal(method, "PUT");
      observations.url = url;
    }

    setRequestHeader(name, value) {
      observations.headers[name] = value;
    }

    send(body) {
      observations.sent = body;
      queueMicrotask(() => {
        this.upload.onprogress?.({ lengthComputable: true, loaded: 3, total: 3 });
        this.onload?.();
      });
    }

    abort() {
      this.onabort?.();
    }
  }

  globalThis.XMLHttpRequest = FakeXhr;
  try {
    const file = new File(["abc"], "asset.txt", { type: "text/plain" });
    await putC19AssetBytes({
      file,
      locator: `/api/backend/c19-assets/u/${uploadTicket}`,
      onProgress: (value) => observations.progress.push(value),
      signal: new AbortController().signal,
    });
    assert.equal(observations.url, `/api/backend/c19-assets/u/${uploadTicket}`);
    assert.equal(observations.headers["Content-Type"], "application/octet-stream");
    assert.equal(observations.sent, file);
    assert.deepEqual(observations.progress, [0, 100, 100]);
  } finally {
    globalThis.XMLHttpRequest = originalXhr;
  }
});

test("Next exposes only small asset control JSON routes, never asset bytes", () => {
  const exactControls = [
    ["POST", ["c19", "conversations", conversationId, "assets", "upload-intents"]],
    ["GET", ["c19", "conversations", conversationId, "assets", assetId]],
    ["POST", ["c19", "conversations", conversationId, "assets", assetId, "finalize"]],
    [
      "POST",
      [
        "c19",
        "conversations",
        conversationId,
        "records",
        "record_01",
        "assets",
        assetId,
        "access-intents",
      ],
    ],
    ["POST", ["c19", "moments", momentId, "assets", "upload-intents"]],
    ["GET", ["c19", "moments", momentId, "assets", assetId]],
    ["POST", ["c19", "moments", momentId, "assets", assetId, "finalize"]],
    ["POST", ["c19", "moments", momentId, "assets", assetId, "access-intents"]],
  ];
  for (const [method, path] of exactControls) {
    assert.equal(isAllowedC19Path(method, path), true);
    assert.equal(getBackendApiPath(method, path), `/api/app/${path.join("/")}`);
  }

  for (const [method, path] of [
    ["PUT", ["c19-assets", "u", uploadTicket]],
    ["GET", ["c19-assets", "d", downloadTicket]],
    ["POST", ["c19", "storage", "upload-intents"]],
    ["POST", ["c19", "providers", "asset"]],
    ["POST", ["c19", "vps", "asset"]],
    ["GET", ["c19", "assets", "transfers", "authorize"]],
    ["POST", ["c19", "conversations", conversationId, "assets", assetId, "download"]],
    ["PUT", ["c19", "moments", momentId, "assets", assetId]],
    ["POST", ["c19", "moments", momentId, "assets", "bad", "finalize"]],
  ]) {
    assert.equal(getBackendApiPath(method, path), null);
  }
});

test("asset UI is volatile, viewport-scoped, and never embeds ordinary files", () => {
  const chatSource = readFileSync(
    "frontend/src/modules/c19/C19ChatPanel.tsx",
    "utf8",
  );
  const transferSource = readFileSync(
    "frontend/src/modules/c19/C19AssetTransfer.ts",
    "utf8",
  );
  const messageAssetSource = readFileSync(
    "frontend/src/modules/c19/C19MessageAsset.tsx",
    "utf8",
  );
  const proxySource = readFileSync(
    "frontend/src/app/api/backend/[...path]/route.ts",
    "utf8",
  );
  const nextConfigSource = readFileSync("frontend/next.config.ts", "utf8");

  assert.match(chatSource, /URL\.createObjectURL/);
  assert.match(chatSource, /URL\.revokeObjectURL/);
  assert.match(chatSource, /pagehide/);
  assert.match(chatSource, /clientAssetId: makeC19ClientAssetId\(\)/);
  assert.match(chatSource, /clientMessageId: makeClientMessageId\(\)/);
  assert.match(chatSource, /phase: "hashing"/);
  assert.match(chatSource, /phase: "uploading"/);
  assert.match(chatSource, /phase: "scanning"/);
  assert.match(chatSource, /phase: "active"/);
  assert.match(chatSource, /phase: "persisting"/);
  assert.match(transferSource, /new XMLHttpRequest\(\)/);
  assert.match(transferSource, /globalThis\.crypto\.subtle\.digest/);
  assert.match(messageAssetSource, /new IntersectionObserver/);
  assert.match(messageAssetSource, /loading="lazy"/);
  assert.match(messageAssetSource, /"thumbnail"/);
  assert.doesNotMatch(
    `${chatSource}\n${transferSource}\n${messageAssetSource}`,
    /FileReader|readAsDataURL|localStorage|sessionStorage|indexedDB|caches\.open/i,
  );
  assert.doesNotMatch(messageAssetSource, /<iframe|<object|<embed|next\/image/i);
  assert.match(proxySource, /C19_JSON|C19_MESSAGE_BODY_MAX_BYTES/);
  assert.match(proxySource, /文件字节不能经过此前端代理/);
  assert.match(nextConfigSource, /img-src 'self' data: blob:/);
});

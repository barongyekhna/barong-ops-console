import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  C19_MOMENT_COMMENT_MAX_LENGTH,
  C19_MOMENT_CONTENT_MAX_LENGTH,
  C19_MOMENT_MAX_IMAGES,
  C19_MOMENT_MAX_AUDIENCE_AFFILIATIONS,
  assertC19MomentImageCount,
  assertC19MomentImageSelection,
  c19MomentEventRequiresRemoval,
  c19MomentVisibilityLabel,
  makeC19ClientCommentId,
  makeC19ClientMomentId,
  mergeC19MomentFeed,
  removeC19Moment,
  retainC19MomentAudienceAffiliations,
  replaceC19Moment,
} from "../../frontend/src/modules/c19/C19MomentRuntime.ts";
import {
  inspectC19AssetSelection,
} from "../../frontend/src/modules/c19/C19AssetTransfer.ts";
import {
  getBackendApiPath,
  isAllowedC19Path,
  PUT,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

const momentId = "mom_0123456789abcdef0123456789abcdef";
const commentId = "cmt_0123456789abcdef0123456789abcdef";
const assetId = "att_0123456789abcdef0123456789abcdef";

function moment(id, content) {
  return {
    moment_id: id,
    client_moment_id: `client_${id}`,
    author: { user_id: 1, display_name: "成员", avatar_ref: null },
    author_org_id: null,
    visibility: "public",
    audience_organizations: [],
    content,
    state: "published",
    created_at: "2026-07-12T00:00:00Z",
    published_at: "2026-07-12T00:00:00Z",
    assets: [],
    like_count: 0,
    comment_count: 0,
    viewer_has_liked: false,
  };
}

test("Moment image selection is image-only and bounded to nine", () => {
  assert.equal(C19_MOMENT_MAX_IMAGES, 9);
  assert.equal(C19_MOMENT_MAX_AUDIENCE_AFFILIATIONS, 32);
  assert.equal(C19_MOMENT_CONTENT_MAX_LENGTH, 4_000);
  assert.equal(C19_MOMENT_COMMENT_MAX_LENGTH, 1_000);
  const selected = assertC19MomentImageSelection(
    inspectC19AssetSelection(
      new File(["image"], "产品图.webp", { type: "image/webp" }),
    ),
  );
  assert.equal(selected.kind, "image");
  assert.equal(selected.mediaType, "image/webp");
  assert.doesNotThrow(() => assertC19MomentImageCount(8, 1));
  assert.throws(() => assertC19MomentImageCount(9, 1), /最多选择 9 张/);
  assert.throws(
    () =>
      assertC19MomentImageSelection(
        inspectC19AssetSelection(
          new File(["file"], "report.pdf", { type: "application/pdf" }),
        ),
      ),
    /仅支持 JPG、PNG、WebP 和 GIF/,
  );
});

test("Moment client identifiers and feed reducers preserve retry and canonical order", () => {
  assert.match(makeC19ClientMomentId(), /^client_moment_[0-9a-f]{32}$/);
  assert.match(makeC19ClientCommentId(), /^client_comment_[0-9a-f]{32}$/);
  const firstId = "mom_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
  const secondId = "mom_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
  const first = moment(firstId, "first");
  const second = moment(secondId, "second");
  const canonicalFirst = moment(firstId, "canonical");
  assert.deepEqual(
    mergeC19MomentFeed([first], [second, canonicalFirst], "prepend").map(
      (item) => [item.moment_id, item.content],
    ),
    [
      [secondId, "second"],
      [firstId, "canonical"],
    ],
  );
  assert.equal(replaceC19Moment([first], canonicalFirst)[0].content, "canonical");
  assert.deepEqual(replaceC19Moment([first], second), [first]);
  assert.deepEqual(removeC19Moment([first, second], firstId), [second]);
  assert.equal(
    c19MomentEventRequiresRemoval({ event_type: "deleted" }),
    true,
  );
  assert.equal(
    c19MomentEventRequiresRemoval({ event_type: "commented" }),
    false,
  );
  assert.equal(c19MomentVisibilityLabel("public"), "所有内部成员");
  assert.equal(c19MomentVisibilityLabel("org"), "指定组织");
  assert.equal(c19MomentVisibilityLabel("friends"), "好友");
  assert.equal(c19MomentVisibilityLabel("private"), "仅自己");
});

test("Moment organization audience is retained only after explicit selection", () => {
  assert.deepEqual(
    retainC19MomentAudienceAffiliations([], ["aff-only"]),
    [],
    "a sole active affiliation must never be guessed or auto-selected",
  );
  assert.deepEqual(
    retainC19MomentAudienceAffiliations(
      ["aff-selected", "aff-expired", "aff-selected"],
      ["aff-selected", "aff-new"],
    ),
    ["aff-selected"],
    "profile changes may retain explicit active choices but never add a new one",
  );
});

test("Moment proxy allowlist is exact for IDs, methods, and control-plane JSON", () => {
  const allowed = [
    ["POST", ["c19", "moments", "drafts"]],
    ["GET", ["c19", "moments", "feed"]],
    ["GET", ["c19", "moments", "events"]],
    ["GET", ["c19", "moments", "events", "tail"]],
    ["GET", ["c19", "moments", momentId]],
    ["DELETE", ["c19", "moments", momentId]],
    ["POST", ["c19", "moments", momentId, "publish"]],
    ["PUT", ["c19", "moments", momentId, "like"]],
    ["DELETE", ["c19", "moments", momentId, "like"]],
    ["GET", ["c19", "moments", momentId, "likes"]],
    ["GET", ["c19", "moments", momentId, "comments"]],
    ["POST", ["c19", "moments", momentId, "comments"]],
    ["DELETE", ["c19", "moments", momentId, "comments", commentId]],
    ["POST", ["c19", "moments", momentId, "assets", "upload-intents"]],
    ["GET", ["c19", "moments", momentId, "assets", assetId]],
    ["POST", ["c19", "moments", momentId, "assets", assetId, "finalize"]],
    ["POST", ["c19", "moments", momentId, "assets", assetId, "access-intents"]],
  ];
  for (const [method, path] of allowed) {
    assert.equal(isAllowedC19Path(method, path), true);
    assert.equal(getBackendApiPath(method, path), `/api/app/${path.join("/")}`);
  }
  for (const [method, path] of [
    ["GET", ["c19", "moments", "mom_abc"]],
    ["PATCH", ["c19", "moments", momentId]],
    ["POST", ["c19", "moments", momentId, "like"]],
    ["POST", ["c19", "moments", momentId, "likes"]],
    ["DELETE", ["c19", "moments", momentId, "comments", "cmt_bad"]],
    ["POST", ["c19", "moments", momentId, "assets", "att_bad", "finalize"]],
    ["GET", ["c19", "moments", "events", "tail", "extra"]],
  ]) {
    assert.equal(isAllowedC19Path(method, path), false);
    assert.equal(getBackendApiPath(method, path), null);
  }
});

test("Moment PUT writes are capped by the 16 KiB JSON proxy boundary", async () => {
  const path = ["c19", "moments", momentId, "like"];
  const url = `http://frontend.local/api/backend/${path.join("/")}`;
  const request = new Request(url, {
    body: JSON.stringify({ padding: "x".repeat(17 * 1024) }),
    headers: { "Content-Type": "application/json" },
    method: "PUT",
  });
  Object.defineProperty(request, "nextUrl", { value: new URL(url) });
  const previousBaseUrl = process.env.BACKEND_API_URL;
  process.env.BACKEND_API_URL = "http://backend.local";
  try {
    const response = await PUT(request, {
      params: Promise.resolve({ path }),
    });
    assert.equal(response.status, 413);
    assert.match(await response.text(), /C19 JSON 控制请求体过大/);
  } finally {
    if (previousBaseUrl === undefined) delete process.env.BACKEND_API_URL;
    else process.env.BACKEND_API_URL = previousBaseUrl;
  }
});

test("Moment UI uses explicit affiliation audiences, sequential direct bytes, and volatile previews", () => {
  const apiSource = readFileSync("frontend/src/modules/c19/api.ts", "utf8");
  const typesSource = readFileSync("frontend/src/modules/c19/types.ts", "utf8");
  const composerSource = readFileSync(
    "frontend/src/modules/c19/C19MomentComposer.tsx",
    "utf8",
  );
  const panelSource = readFileSync(
    "frontend/src/modules/c19/C19MomentsPanel.tsx",
    "utf8",
  );
  const imageSource = readFileSync(
    "frontend/src/modules/c19/C19MomentImage.tsx",
    "utf8",
  );
  const proxySource = readFileSync(
    "frontend/src/app/api/backend/[...path]/route.ts",
    "utf8",
  );

  assert.match(typesSource, /"public" \| "org" \| "friends" \| "private"/);
  assert.match(composerSource, /audience_affiliation_ids/);
  assert.match(
    composerSource,
    /useState<string\[\]>\(\[\]\)/,
  );
  assert.match(composerSource, /retainC19MomentAudienceAffiliations\(current, activeIds\)/);
  assert.doesNotMatch(composerSource, /affiliations\.length === 1/);
  assert.doesNotMatch(composerSource, /audience_org_ids|\borg_id\b/);
  assert.match(composerSource, /multiple/);
  assert.match(composerSource, /for\s*\(\s*let index = 0;/);
  assert.match(composerSource, /putC19AssetBytes/);
  assert.match(composerSource, /asset_ids: assetIds/);
  assert.match(composerSource, /draft\.state !== "published"/);
  assert.match(composerSource, /publishC19Moment/);
  assert.doesNotMatch(composerSource, /draft\.state === "published"[\s\S]{0,300}getC19Moment/);
  assert.match(composerSource, /makeC19ClientMomentId/);
  assert.match(composerSource, /重试会复用同一草稿、图片和发布幂等编号/);
  assert.match(composerSource, /URL\.createObjectURL/);
  assert.match(composerSource, /URL\.revokeObjectURL/);
  assert.match(composerSource, /pagehide/);
  assert.doesNotMatch(
    `${composerSource}\n${panelSource}\n${imageSource}`,
    /dangerouslySetInnerHTML|localStorage|sessionStorage|indexedDB|caches\.open|FileReader|readAsDataURL/,
  );
  assert.match(imageSource, /new IntersectionObserver/);
  assert.match(imageSource, /assertC19DownloadLocator/);
  assert.doesNotMatch(imageSource, /<iframe|<object|<embed|next\/image/i);
  assert.match(panelSource, /getC19MomentEventTail/);
  assert.match(panelSource, /listC19MomentEvents/);
  assert.match(panelSource, /new EventSource/);
  assert.match(panelSource, /EVENT_POLL_INTERVAL_MS = 4_000/);
  assert.match(panelSource, /SSE_RECONNECT_INTERVAL_MS = 30_000/);
  assert.match(panelSource, /page\.next_cursor/);
  assert.match(panelSource, /let streamPageFailed = false/);
  assert.match(panelSource, /streamPageFailed = false;[\s\S]{0,120}streamGeneration/);
  assert.match(panelSource, /streamPageFailed = true;[\s\S]{0,220}startPolling\(\)/);
  assert.match(panelSource, /streamPageFailed \|\|[\s\S]{0,120}generation !== streamGeneration/);
  const acceptPageSource = panelSource.slice(
    panelSource.indexOf("const acceptEventPage"),
    panelSource.indexOf("const connect"),
  );
  assert.ok(
    acceptPageSource.indexOf("await processEvents(page.events)") <
      acceptPageSource.indexOf("rememberEventCursor(page.next_cursor)"),
    "SSE cursor must advance only after the whole page is processed",
  );
  assert.match(apiSource, /C19_MOMENT_EVENT_PROXY_PATH/);
  assert.doesNotMatch(typesSource, /author_user_id|audience_org_ids/);
  assert.match(proxySource, /C19_JSON_BODY_MAX_BYTES = 16 \* 1024/);
  assert.match(proxySource, /isC19MomentJsonWrite/);
  assert.match(proxySource, /isC19MomentId/);
  assert.match(proxySource, /isC19MomentCommentId/);
  assert.match(proxySource, /export function PUT\(/);
});

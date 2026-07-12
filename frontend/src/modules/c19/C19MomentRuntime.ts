import type {
  C19AssetSelection,
} from "./C19AssetTransfer";
import type {
  C19AssetKind,
  C19Moment,
  C19MomentEvent,
  C19MomentVisibility,
} from "./types";

export const C19_MOMENT_MAX_IMAGES = 9;
export const C19_MOMENT_MAX_AUDIENCE_AFFILIATIONS = 32;
export const C19_MOMENT_CONTENT_MAX_LENGTH = 4_000;
export const C19_MOMENT_COMMENT_MAX_LENGTH = 1_000;
export const C19_MOMENT_IMAGE_ACCEPT = ".jpg,.jpeg,.png,.webp,.gif";

export type C19PendingMomentImage = {
  assetId?: string;
  clientAssetId: string;
  file: File;
  filename: string;
  kind: C19AssetKind;
  mediaType: string;
  previewUrl: string;
  progress: number;
  sha256Hex?: string;
  sizeBytes: number;
  status:
    | "selected"
    | "hashing"
    | "intent"
    | "uploading"
    | "scanning"
    | "active"
    | "failed";
  statusText: string;
};

function randomClientIdentifier(prefix: string) {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi?.randomUUID) {
    return `${prefix}_${cryptoApi.randomUUID().replaceAll("-", "")}`;
  }
  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  return `${prefix}_${Array.from(bytes, (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("")}`;
}

export function makeC19ClientMomentId() {
  return randomClientIdentifier("client_moment");
}

export function makeC19ClientCommentId() {
  return randomClientIdentifier("client_comment");
}

export function assertC19MomentImageSelection(inspected: C19AssetSelection) {
  if (inspected.kind !== "image") {
    throw new Error("朋友圈仅支持 JPG、PNG、WebP 和 GIF 图片。");
  }
  return inspected;
}

export function assertC19MomentImageCount(current: number, added: number) {
  if (
    !Number.isSafeInteger(current) ||
    !Number.isSafeInteger(added) ||
    current < 0 ||
    added < 0 ||
    current + added > C19_MOMENT_MAX_IMAGES
  ) {
    throw new Error(`每条朋友圈最多选择 ${C19_MOMENT_MAX_IMAGES} 张图片。`);
  }
}

export function retainC19MomentAudienceAffiliations(
  selectedAffiliationIds: string[],
  activeAffiliationIds: string[],
) {
  const active = new Set(activeAffiliationIds);
  const retained: string[] = [];
  const seen = new Set<string>();
  for (const affiliationId of selectedAffiliationIds) {
    if (
      active.has(affiliationId) &&
      !seen.has(affiliationId) &&
      retained.length < C19_MOMENT_MAX_AUDIENCE_AFFILIATIONS
    ) {
      seen.add(affiliationId);
      retained.push(affiliationId);
    }
  }
  return retained;
}

export function mergeC19MomentFeed(
  current: C19Moment[],
  incoming: C19Moment[],
  mode: "append" | "prepend",
) {
  const incomingById = new Map(incoming.map((moment) => [moment.moment_id, moment]));
  const currentWithoutIncoming = current.filter(
    (moment) => !incomingById.has(moment.moment_id),
  );
  return mode === "prepend"
    ? [...incoming, ...currentWithoutIncoming]
    : [...currentWithoutIncoming, ...incoming];
}

export function replaceC19Moment(
  current: C19Moment[],
  replacement: C19Moment,
) {
  let found = false;
  const next = current.map((moment) => {
    if (moment.moment_id !== replacement.moment_id) return moment;
    found = true;
    return replacement;
  });
  return found ? next : current;
}

export function removeC19Moment(current: C19Moment[], momentId: string) {
  return current.filter((moment) => moment.moment_id !== momentId);
}

export function c19MomentEventRequiresRemoval(event: C19MomentEvent) {
  return event.event_type === "deleted";
}

export function c19MomentVisibilityLabel(visibility: C19MomentVisibility) {
  if (visibility === "public") return "所有内部成员";
  if (visibility === "org") return "指定组织";
  if (visibility === "friends") return "好友";
  return "仅自己";
}

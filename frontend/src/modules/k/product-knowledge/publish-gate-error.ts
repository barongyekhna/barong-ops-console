export type PublishGateConflictDetail = {
  ready: boolean;
  blockers: string[];
};

export function parsePublishGateConflictDetail(
  value: unknown,
): PublishGateConflictDetail | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }

  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  if (
    keys.length !== 2 ||
    !keys.includes("ready") ||
    !keys.includes("blockers") ||
    typeof record.ready !== "boolean" ||
    !Array.isArray(record.blockers) ||
    !record.blockers.every((blocker) => typeof blocker === "string")
  ) {
    return null;
  }

  return {
    ready: record.ready,
    blockers: [...record.blockers],
  };
}

export function publishGateConflictMessage(
  productLabel: string,
  value: unknown,
): string | null {
  const detail = parsePublishGateConflictDetail(value);
  if (!detail || detail.blockers.length === 0) {
    return null;
  }
  return `「${productLabel}」未过上架门禁：${detail.blockers.join("；")}`;
}

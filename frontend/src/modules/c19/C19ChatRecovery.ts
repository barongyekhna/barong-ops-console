import type {
  C19MessageHistoryPage,
  C19MessageRecord,
  C19ResumePosition,
} from "./types";

const DEFAULT_MAX_FENCE_ATTEMPTS = 5;

export function c19ReceiptSafetyScope(
  userId: number | string,
  conversationId: string,
) {
  return `${String(userId)}:${conversationId}`;
}

export function isC19ReceiptSafetyScopeActive(
  activeScope: string | null,
  expectedScope: string,
) {
  return activeScope === expectedScope;
}

export class C19RecoverySafetyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "C19RecoverySafetyError";
  }
}

export type C19MessageWindowMerge = {
  records: C19MessageRecord[];
  evictedOlderRenderedRecord: boolean;
};

export function mergeC19MessageWindow({
  current,
  incoming,
  maxRecords,
  preserveWindowBounds = false,
  windowDirection = "newest",
}: {
  current: C19MessageRecord[];
  incoming: C19MessageRecord[];
  maxRecords: number;
  preserveWindowBounds?: boolean;
  windowDirection?: "newest" | "older";
}): C19MessageWindowMerge {
  if (preserveWindowBounds) {
    const updates = new Map(
      incoming.map((record) => [record.record_id, record]),
    );
    return {
      evictedOlderRenderedRecord: false,
      records: current.map((record) => updates.get(record.record_id) ?? record),
    };
  }

  const byRecordId = new Map(
    current.map((record) => [record.record_id, record]),
  );
  for (const record of incoming) {
    byRecordId.set(record.record_id, record);
  }
  const sorted = [...byRecordId.values()].sort(
    (left, right) => left.sequence - right.sequence,
  );
  const records =
    windowDirection === "older"
      ? sorted.slice(0, maxRecords)
      : sorted.slice(-maxRecords);
  const retainedRecordIds = new Set(records.map((record) => record.record_id));
  const evictedOlderRenderedRecord =
    windowDirection === "newest" &&
    current.some((record) => !retainedRecordIds.has(record.record_id));

  return { evictedOlderRenderedRecord, records };
}

export type C19RecoveryWindow = {
  latestPage: C19MessageHistoryPage;
  resume: C19ResumePosition;
};

/**
 * Establishes a recoverable history cut.
 *
 * The latest page is deliberately read before the resume position. A message
 * committed between those reads is therefore represented by resume_cursor,
 * instead of being rendered from a newer page while receipts remain pinned to
 * an older, concurrently-read resume snapshot.
 *
 * A different client may advance delivery while this client is starting. In
 * that case resume_cursor can legitimately be null while the first latest page
 * is stale. Re-read the page and fence again until both snapshots agree.
 */
export async function initializeC19RecoveryWindow({
  conversationId,
  establishEventBoundary,
  historyLimit,
  listLatest,
  getResume,
  maxFenceAttempts = DEFAULT_MAX_FENCE_ATTEMPTS,
}: {
  conversationId: string;
  establishEventBoundary: () => Promise<unknown>;
  historyLimit: number;
  listLatest: (
    conversationId: string,
    options: { limit: number },
  ) => Promise<C19MessageHistoryPage>;
  getResume: (conversationId: string) => Promise<C19ResumePosition>;
  maxFenceAttempts?: number;
}): Promise<C19RecoveryWindow> {
  if (!Number.isInteger(maxFenceAttempts) || maxFenceAttempts < 1) {
    throw new C19RecoverySafetyError("恢复快照重试次数配置无效。");
  }

  await establishEventBoundary();
  let latestPage = await listLatest(conversationId, { limit: historyLimit });

  for (let attempt = 0; attempt < maxFenceAttempts; attempt += 1) {
    const resume = await getResume(conversationId);
    if (resume.resume_cursor) {
      return { latestPage, resume };
    }
    if (latestPage.latest_sequence === resume.latest_sequence) {
      return { latestPage, resume };
    }

    if (latestPage.latest_sequence < resume.latest_sequence) {
      latestPage = await listLatest(conversationId, { limit: historyLimit });
    }
    // If the page is ahead (for example, a lagging resume replica), keep the
    // newer page and fence resume again. We never promote receipts from it.
  }

  throw new C19RecoverySafetyError(
    "聊天记录持续变化，未能建立安全恢复快照；回执保持冻结。",
  );
}

export type C19ForwardRecoveryProgress = {
  nextCursor: string | null;
  pages: number;
  safeSequence: number;
};

/** Drain one cooperative batch without ever inferring receipt safety from the
 * page-level latest_sequence. Only records actually returned by the forward
 * cursor may advance safeSequence.
 */
export async function drainC19ForwardRecoveryBatch({
  conversationId,
  initialCursor,
  initialSafeSequence,
  seenCursors,
  maxPages,
  maxTrackedCursors,
  pageLimit,
  listPage,
  onPage,
}: {
  conversationId: string;
  initialCursor: string;
  initialSafeSequence: number;
  seenCursors: Set<string>;
  maxPages: number;
  maxTrackedCursors: number;
  pageLimit: number;
  listPage: (
    conversationId: string,
    options: { cursor: string; limit: number },
  ) => Promise<C19MessageHistoryPage>;
  onPage?: (
    page: C19MessageHistoryPage,
    progress: C19ForwardRecoveryProgress,
  ) => void | Promise<void>;
}): Promise<C19ForwardRecoveryProgress> {
  let cursor: string | null = initialCursor;
  let pages = 0;
  let safeSequence = initialSafeSequence;

  while (cursor && pages < maxPages) {
    if (seenCursors.has(cursor)) {
      throw new C19RecoverySafetyError(
        "恢复游标发生循环，已暂停自动恢复；回执保持冻结。",
      );
    }
    if (seenCursors.size >= maxTrackedCursors) {
      seenCursors.clear();
    }

    const requestedCursor = cursor;
    const page = await listPage(conversationId, {
      cursor: requestedCursor,
      limit: pageLimit,
    });
    seenCursors.add(requestedCursor);
    pages += 1;
    for (const record of page.records) {
      safeSequence = Math.max(safeSequence, record.sequence);
    }
    cursor = page.next_cursor;
    await onPage?.(page, {
      nextCursor: cursor,
      pages,
      safeSequence,
    });
  }

  return { nextCursor: cursor, pages, safeSequence };
}

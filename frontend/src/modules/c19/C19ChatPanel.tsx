"use client";

import {
  ChevronUp,
  FileText,
  ImageIcon,
  LoaderCircle,
  Paperclip,
  RefreshCcw,
  Send,
  Smile,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import {
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ApiError } from "@/lib/api";

import {
  advanceC19Delivery,
  advanceC19Read,
  c19EventStreamUrl,
  createC19AssetUploadIntent,
  finalizeC19AssetUpload,
  getC19AssetStatus,
  getC19MessageEventTail,
  getC19ResumePosition,
  getC19UnreadPosition,
  listC19MessageEvents,
  listC19MessageHistory,
  sendC19Message,
} from "./api";
import {
  C19_ASSET_ACCEPT,
  C19AssetTransferError,
  assertC19UploadLocator,
  inspectC19AssetSelection,
  makeC19ClientAssetId,
  putC19AssetBytes,
  sha256C19File,
  waitForC19AssetPoll,
} from "./C19AssetTransfer";
import {
  C19RecoverySafetyError as RecoverySafetyError,
  c19ReceiptSafetyScope,
  drainC19ForwardRecoveryBatch,
  initializeC19RecoveryWindow,
  isC19ReceiptSafetyScopeActive,
  mergeC19MessageWindow,
} from "./C19ChatRecovery";
import { c19SseReconnectDelay } from "./C19EventStreamRecovery";
import { C19CardMessage, parseC19Card } from "./C19CardMessage";
import { C19MessageAsset } from "./C19MessageAsset";
import { announceC19UnreadChanged } from "./C19UnreadStatus";
import styles from "./C19Workspace.module.css";
import type {
  C19Conversation,
  C19Asset,
  C19AssetKind,
  C19MessageContentType,
  C19MessageEvent,
  C19MessageEventPage,
  C19MessageRecord,
  C19Profile,
  C19ResumePosition,
  C19UnreadPosition,
} from "./types";

const HISTORY_LIMIT = 50;
const RECOVERY_PAGE_LIMIT = 100;
const RECOVERY_BATCH_PAGES = 20;
const MAX_RENDERED_MESSAGES = 2_000;
const MAX_TRACKED_CURSORS = 5_000;
const EVENT_LIMIT = 200;
const MAX_EVENT_DRAIN_PAGES = 50;
const EVENT_POLL_INTERVAL_MS = 4_000;
const SSE_HANDSHAKE_TIMEOUT_MS = 12_000;
// 后台对账提示只在真卡住时才打扰用户:补齐提示延迟到超过 1.5s 才显示;
// 报错横条只在连续失败到达阈值后才亮(偶发一次自愈的失败不惊扰)。
const RECOVERY_SLOW_HINT_MS = 1500;
const RECOVERY_ERROR_VISIBLE_THRESHOLD = 3;
const STATUS_REFRESH_INTERVAL_MS = 15_000;
const MESSAGE_MAX_LENGTH = 4_000;
const ASSET_SCAN_POLL_LIMIT = 120;
const EMOJI_CATEGORIES = [
  {
    id: "common",
    label: "常用",
    emojis: [
      "😀", "😂", "😊", "😍", "🥳", "😎", "😭", "😡",
      "👍", "👏", "🙏", "❤️", "🎉", "🔥", "✅", "💯",
    ],
  },
  {
    id: "faces",
    label: "表情",
    emojis: [
      "😄", "😁", "😅", "🤣", "🙂", "🙃", "😉", "🥰",
      "😘", "🤔", "🤗", "🤩", "😴", "🤯", "🥺", "😇",
    ],
  },
  {
    id: "gestures",
    label: "手势",
    emojis: [
      "👋", "👌", "✌️", "🤞", "🤟", "🤝", "💪", "🙌",
      "👊", "🤙", "☝️", "👏", "🙏", "👍", "👎", "🫶",
    ],
  },
  {
    id: "objects",
    label: "活动",
    emojis: [
      "🎈", "🎁", "🎊", "🏆", "🚀", "💡", "📌", "📣",
      "💬", "⭐", "🌈", "☀️", "🌙", "🍀", "☕", "🍻",
    ],
  },
] as const;
const eventCursorMemory = new Map<string, string>();

type ConnectionMode = "connecting" | "live" | "polling" | "offline";
type RenderWindowMode = "latest" | "older";

type PendingMessage = {
  clientMessageId: string;
  content: string;
  contentType: C19MessageContentType;
  asset?: PendingAsset;
};

type PendingAsset = {
  assetId?: string;
  clientAssetId: string;
  file: File;
  filename: string;
  kind: C19AssetKind;
  mediaType: string;
  previewUrl: string | null;
  sha256Hex?: string;
  sizeBytes: number;
};

type AssetTransferPhase =
  | "selected"
  | "hashing"
  | "intent"
  | "uploading"
  | "scanning"
  | "active"
  | "persisting"
  | "failed";

type AssetTransferState = {
  phase: AssetTransferPhase;
  progress: number;
  statusText: string;
};

type RecoveryCheckpoint = {
  conversationId: string;
  forwardCursor: string | null;
  forwardCursors: Set<string>;
  historyCursor: string | null;
  olderCursor: string | null;
  olderCursors: Set<string>;
  phase: "forward" | "older" | "complete";
  pagingGeneration: number;
  recoveredCount: number;
  resume: C19ResumePosition;
  safeSequence: number;
};

type HistoryPagingState = {
  conversationId: string;
  cursor: string | null;
  generation: number;
  initialized: boolean;
  newestWindowEvictedOlder: boolean;
};

function runtimeErrorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "登录状态已失效，请重新登录。";
    if (error.status === 403) return "你已不再拥有这个会话的访问权。";
    if (error.status === 404) return "会话或消息不存在。";
    if (error.status === 409) return error.message || "消息状态发生冲突，请刷新后重试。";
    if (error.status === 413) return "图片或文件超过资产服务允许的大小。";
    if (error.status === 415) return "图片或文件类型不受支持。";
    if (error.status === 422) return error.message || "消息内容不符合发送规则。";
    if (error.status === 429) return "发送过于频繁，请稍后再试。";
    if (error.status >= 500) return "聊天服务暂时不可用，消息未发送成功，请重试。";
    return error.message || fallback;
  }
  return error instanceof Error && error.message ? error.message : fallback;
}

function makeClientMessageId() {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi?.randomUUID) {
    return `client_msg_${cryptoApi.randomUUID().replaceAll("-", "")}`;
  }

  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  return `client_msg_${Array.from(bytes, (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("")}`;
}

function contentTypeFor(value: string): C19MessageContentType {
  const hasEmoji = /[\p{Extended_Pictographic}\p{Emoji_Presentation}]/u.test(value);
  const remaining = value.replace(
    /[\p{Extended_Pictographic}\p{Emoji_Presentation}\u200d\ufe0f\s]/gu,
    "",
  );
  return !hasEmoji || remaining || value.length > 64 || /[\n\t]/.test(value)
    ? "text"
    : "emoji";
}

function messageTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function receiptLabel(status: C19MessageRecord["status"]) {
  if (status === "read") return "已读";
  if (status === "delivered") return "已送达";
  return "已发送";
}

function isSameUser(left: number | string, right: number | string) {
  return String(left) === String(right);
}

export function C19ChatPanel({
  conversation,
  headerActions,
  profiles,
  title,
  userId,
}: {
  conversation: C19Conversation;
  headerActions?: ReactNode;
  profiles: C19Profile[];
  title?: string;
  userId: number;
}) {
  const conversationId = conversation.conversation_id;
  const receiptSafetyScope = c19ReceiptSafetyScope(userId, conversationId);
  const [records, setRecords] = useState<C19MessageRecord[]>([]);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [latestSequence, setLatestSequence] = useState(0);
  const [unreadPosition, setUnreadPosition] =
    useState<C19UnreadPosition | null>(null);
  const [resumePosition, setResumePosition] =
    useState<C19ResumePosition | null>(null);
  const [draft, setDraft] = useState("");
  const [emojiCategory, setEmojiCategory] = useState<string>(
    EMOJI_CATEGORIES[0].id,
  );
  const [emojiPickerOpen, setEmojiPickerOpen] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<PendingAsset | null>(null);
  const [assetTransfer, setAssetTransfer] =
    useState<AssetTransferState | null>(null);
  const [pendingMessage, setPendingMessage] = useState<PendingMessage | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [sendError, setSendError] = useState("");
  const [receiptError, setReceiptError] = useState("");
  const [recoveryError, setRecoveryError] = useState("");
  const [isRecovering, setIsRecovering] = useState(true);
  const [recoverySlow, setRecoverySlow] = useState(false);
  const [recoveryReady, setRecoveryReady] = useState(false);
  const recoveryFailureStreakRef = useRef(0);

  // 补齐提示延迟显示:对账通常一两秒就完成,只有真卡住(>1.5s)才提示,
  // 避免每次进会话都闪一下"正在补齐历史消息"。
  useEffect(() => {
    if (!isRecovering) {
      setRecoverySlow(false);
      return;
    }
    const timer = setTimeout(() => setRecoverySlow(true), RECOVERY_SLOW_HINT_MS);
    return () => clearTimeout(timer);
  }, [isRecovering]);
  const [safeReceiptSequence, setSafeReceiptSequence] = useState(0);
  const [historyWindowLimited, setHistoryWindowLimited] = useState(false);
  const [renderWindowMode, setRenderWindowMode] =
    useState<RenderWindowMode>("latest");
  const [connectionMode, setConnectionMode] =
    useState<ConnectionMode>("connecting");
  const [visibilityTick, setVisibilityTick] = useState(0);
  const eventCursorRef = useRef<string | null>(
    eventCursorMemory.get(String(userId)) ?? null,
  );
  const eventTailBootstrapPromiseRef = useRef<Promise<string | null> | null>(null);
  const activeUserIdRef = useRef(userId);
  const activeConversationRef = useRef(conversationId);
  const seenEventIdsRef = useRef(new Set<string>());
  const receiptInFlightRef = useRef({ delivered: 0, read: 0 });
  const receiptSafetyScopeRef = useRef<string | null>(null);
  const pendingMessageRef = useRef<PendingMessage | null>(null);
  const assetAbortRef = useRef<AbortController | null>(null);
  const assetPreviewUrlRef = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const emojiPickerRef = useRef<HTMLDivElement | null>(null);
  const sendInFlightRef = useRef(false);
  const sendOperationRef = useRef(0);
  const messageHistoryRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);
  const recoveryPromiseRef = useRef<Promise<boolean> | null>(null);
  const recoveryOperationRef = useRef(0);
  const recoveryRunnerRef = useRef<
    ((manual?: boolean) => Promise<boolean>) | null
  >(null);
  const unreadRefreshRunnerRef = useRef<(() => Promise<void>) | null>(null);
  const automaticRecoveryPausedRef = useRef(false);
  const recoveryCheckpointRef = useRef<RecoveryCheckpoint | null>(null);
  const renderedRecordsRef = useRef<C19MessageRecord[]>([]);
  const renderWindowModeRef = useRef<RenderWindowMode>("latest");
  const historyPagingRef = useRef<HistoryPagingState>({
    conversationId,
    cursor: null,
    generation: 0,
    initialized: false,
    newestWindowEvictedOlder: false,
  });
  activeConversationRef.current = conversationId;
  activeUserIdRef.current = userId;

  useEffect(() => {
    if (!emojiPickerOpen) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !emojiPickerRef.current?.contains(event.target)
      ) {
        setEmojiPickerOpen(false);
      }
    };
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setEmojiPickerOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [emojiPickerOpen]);

  const revokeAssetPreview = useCallback(() => {
    if (assetPreviewUrlRef.current) {
      URL.revokeObjectURL(assetPreviewUrlRef.current);
      assetPreviewUrlRef.current = null;
    }
  }, []);

  const resetAssetComposer = useCallback(
    (abort = true) => {
      if (abort) assetAbortRef.current?.abort();
      assetAbortRef.current = null;
      revokeAssetPreview();
      setSelectedAsset(null);
      setAssetTransfer(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
    [revokeAssetPreview],
  );

  useEffect(() => {
    const disposeVolatileAsset = () => {
      assetAbortRef.current?.abort();
      revokeAssetPreview();
    };
    window.addEventListener("pagehide", disposeVolatileAsset);
    return () => {
      window.removeEventListener("pagehide", disposeVolatileAsset);
      disposeVolatileAsset();
    };
  }, [revokeAssetPreview]);

  const profileNames = useMemo(
    () => new Map(profiles.map((profile) => [profile.user_id, profile.display_name])),
    [profiles],
  );

  useEffect(() => {
    eventCursorRef.current = eventCursorMemory.get(String(userId)) ?? null;
    eventTailBootstrapPromiseRef.current = null;
    seenEventIdsRef.current = new Set();
  }, [userId]);

  const mergeRenderedRecords = useCallback(
    (
      incoming: C19MessageRecord[],
      windowDirection: "newest" | "older" = "newest",
    ) => {
      const merged = mergeC19MessageWindow({
        current: renderedRecordsRef.current,
        incoming,
        maxRecords: MAX_RENDERED_MESSAGES,
        preserveWindowBounds:
          renderWindowModeRef.current === "older" &&
          windowDirection === "newest",
        windowDirection,
      });
      renderedRecordsRef.current = merged.records;

      const paging = historyPagingRef.current;
      if (
        merged.evictedOlderRenderedRecord &&
        renderWindowModeRef.current === "latest" &&
        paging.conversationId === conversationId &&
        paging.initialized
      ) {
        historyPagingRef.current = {
          conversationId,
          cursor: null,
          generation: paging.generation + 1,
          initialized: false,
          newestWindowEvictedOlder: true,
        };
        setHistoryCursor(null);
      }
      setRecords(merged.records);
      return merged.evictedOlderRenderedRecord;
    },
    [conversationId],
  );

  const ensureEventTailBoundary = useCallback(() => {
    if (eventCursorRef.current) {
      return Promise.resolve(eventCursorRef.current);
    }
    if (eventTailBootstrapPromiseRef.current) {
      return eventTailBootstrapPromiseRef.current;
    }

    const bootstrapUserId = String(userId);
    const bootstrap = getC19MessageEventTail().then((tail) => {
      if (String(activeUserIdRef.current) !== bootstrapUserId) return null;
      eventCursorRef.current = tail.cursor;
      eventCursorMemory.set(bootstrapUserId, tail.cursor);
      return tail.cursor;
    });
    eventTailBootstrapPromiseRef.current = bootstrap;
    const clearBootstrap = () => {
      if (eventTailBootstrapPromiseRef.current === bootstrap) {
        eventTailBootstrapPromiseRef.current = null;
      }
    };
    void bootstrap.then(clearBootstrap, clearBootstrap);
    return bootstrap;
  }, [userId]);

  const recoverFromResume = useCallback((manual = false) => {
    if (automaticRecoveryPausedRef.current && !manual) {
      return Promise.resolve(false);
    }
    if (manual && automaticRecoveryPausedRef.current) {
      automaticRecoveryPausedRef.current = false;
      recoveryCheckpointRef.current = null;
    }
    if (recoveryPromiseRef.current) return recoveryPromiseRef.current;

    const operation = recoveryOperationRef.current + 1;
    recoveryOperationRef.current = operation;
    receiptSafetyScopeRef.current = null;
    const recovery = (async () => {
      setIsRecovering(true);
      setRecoveryReady(false);
      setRecoveryError("");
      try {
        let checkpoint = recoveryCheckpointRef.current;
        if (!checkpoint || checkpoint.conversationId !== conversationId) {
          const { resume, latestPage } = await initializeC19RecoveryWindow({
            conversationId,
            establishEventBoundary: ensureEventTailBoundary,
            getResume: getC19ResumePosition,
            historyLimit: HISTORY_LIMIT,
            listLatest: listC19MessageHistory,
          });
          if (
            activeConversationRef.current !== conversationId ||
            recoveryOperationRef.current !== operation
          ) {
            return false;
          }
          setResumePosition(resume);
          const pagingNeedsLatestRebase =
            renderWindowModeRef.current === "latest" &&
            historyPagingRef.current.conversationId === conversationId &&
            historyPagingRef.current.newestWindowEvictedOlder;
          if (pagingNeedsLatestRebase) {
            renderedRecordsRef.current = [];
            setRecords([]);
          }
          const evictedWhileMergingLatest = mergeRenderedRecords(
            latestPage.records,
          );
          if (evictedWhileMergingLatest) {
            // The existing opaque cursor was anchored before a record that is
            // no longer rendered. Rebase both the window and cursor to this
            // exact latest-page snapshot instead of leaving a history gap.
            renderedRecordsRef.current = [];
            setRecords([]);
            mergeRenderedRecords(latestPage.records);
          }
          setLatestSequence((current) =>
            Math.max(current, latestPage.latest_sequence, resume.latest_sequence),
          );
          checkpoint = {
            conversationId,
            forwardCursor: resume.resume_cursor,
            forwardCursors: new Set<string>(),
            historyCursor: latestPage.next_cursor,
            olderCursor: latestPage.next_cursor,
            olderCursors: new Set<string>(),
            pagingGeneration: historyPagingRef.current.generation,
            phase: resume.resume_cursor
              ? "forward"
              : resume.read_through_sequence < resume.delivered_through_sequence &&
                  latestPage.next_cursor
                ? "older"
                : "complete",
            recoveredCount: latestPage.records.length,
            resume,
            safeSequence: resume.delivered_through_sequence,
          };
          recoveryCheckpointRef.current = checkpoint;
        } else {
          setResumePosition(checkpoint.resume);
        }

        while (checkpoint.phase !== "complete") {
          let batchPages = 0;
          while (
            batchPages < RECOVERY_BATCH_PAGES &&
            checkpoint.phase !== "complete"
          ) {
            const cursor =
              checkpoint.phase === "forward"
                ? checkpoint.forwardCursor
                : checkpoint.olderCursor;
            if (!cursor) {
              checkpoint.phase =
                checkpoint.phase === "forward" &&
                checkpoint.resume.read_through_sequence <
                  checkpoint.resume.delivered_through_sequence &&
                checkpoint.olderCursor
                  ? "older"
                  : "complete";
              continue;
            }

            if (checkpoint.phase === "forward") {
              const progress = await drainC19ForwardRecoveryBatch({
                conversationId,
                initialCursor: cursor,
                initialSafeSequence: checkpoint.safeSequence,
                listPage: listC19MessageHistory,
                maxPages: RECOVERY_BATCH_PAGES - batchPages,
                maxTrackedCursors: MAX_TRACKED_CURSORS,
                onPage: async (page, pageProgress) => {
                  if (
                    activeConversationRef.current !== conversationId ||
                    recoveryOperationRef.current !== operation
                  ) {
                    throw new Error("C19 recovery operation superseded");
                  }
                  checkpoint.recoveredCount += page.records.length;
                  if (checkpoint.recoveredCount > MAX_RENDERED_MESSAGES) {
                    setHistoryWindowLimited(true);
                  }
                  mergeRenderedRecords(page.records);
                  setLatestSequence((current) =>
                    Math.max(current, page.latest_sequence),
                  );
                  checkpoint.forwardCursor = pageProgress.nextCursor;
                  checkpoint.safeSequence = pageProgress.safeSequence;
                  recoveryCheckpointRef.current = checkpoint;
                },
                pageLimit: RECOVERY_PAGE_LIMIT,
                seenCursors: checkpoint.forwardCursors,
              });
              batchPages += progress.pages;
              checkpoint.forwardCursor = progress.nextCursor;
              checkpoint.safeSequence = progress.safeSequence;
              if (!checkpoint.forwardCursor) {
                checkpoint.phase =
                  checkpoint.resume.read_through_sequence <
                    checkpoint.resume.delivered_through_sequence &&
                  checkpoint.olderCursor
                    ? "older"
                    : "complete";
              }
              recoveryCheckpointRef.current = checkpoint;
              continue;
            }

            const trackedCursors = checkpoint.olderCursors;
            if (trackedCursors.has(cursor)) {
              throw new RecoverySafetyError(
                "消息恢复出现问题，已暂停，请刷新会话后重试。",
              );
            }
            if (trackedCursors.size >= MAX_TRACKED_CURSORS) {
              trackedCursors.clear();
            }

            const page = await listC19MessageHistory(conversationId, {
              cursor,
              limit: RECOVERY_PAGE_LIMIT,
            });
            if (
              activeConversationRef.current !== conversationId ||
              recoveryOperationRef.current !== operation
            ) {
              return false;
            }
            trackedCursors.add(cursor);
            batchPages += 1;
            checkpoint.recoveredCount += page.records.length;
            if (checkpoint.recoveredCount > MAX_RENDERED_MESSAGES) {
              setHistoryWindowLimited(true);
            }
            mergeRenderedRecords(page.records);
            setLatestSequence((current) =>
              Math.max(current, page.latest_sequence),
            );

            const reachedReadPosition = page.records.some(
              (record) =>
                record.sequence <= checkpoint.resume.read_through_sequence,
            );
            checkpoint.olderCursor = page.next_cursor;
            if (reachedReadPosition || !checkpoint.olderCursor) {
              checkpoint.phase = "complete";
            }
            recoveryCheckpointRef.current = checkpoint;
          }

          if (checkpoint.phase !== "complete") {
            await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
            if (
              activeConversationRef.current !== conversationId ||
              recoveryOperationRef.current !== operation
            ) {
              return false;
            }
          }
        }

        recoveryCheckpointRef.current = null;
        let paging = historyPagingRef.current;
        if (
          paging.conversationId !== conversationId ||
          (!paging.initialized &&
            renderWindowModeRef.current === "latest")
        ) {
          const pagingGeneration =
            paging.conversationId === conversationId
              ? paging.generation
              : checkpoint.pagingGeneration;
          paging = {
            conversationId,
            cursor: checkpoint.historyCursor,
            generation: pagingGeneration,
            initialized: true,
            newestWindowEvictedOlder: false,
          };
          historyPagingRef.current = paging;
        }
        setHistoryCursor(paging.cursor);
        setSafeReceiptSequence(checkpoint.safeSequence);
        receiptInFlightRef.current = {
          delivered: checkpoint.resume.delivered_through_sequence,
          read: checkpoint.resume.read_through_sequence,
        };
        receiptSafetyScopeRef.current = receiptSafetyScope;
        setRecoveryReady(true);
        setRecoveryError("");
        recoveryFailureStreakRef.current = 0;
        if (paging.initialized) {
          setHistoryError("");
        }
        return true;
      } catch (error) {
        if (
          activeConversationRef.current === conversationId &&
          recoveryOperationRef.current === operation
        ) {
          const recoveryPaused = error instanceof RecoverySafetyError;
          if (recoveryPaused) {
            automaticRecoveryPausedRef.current = true;
          }
          if (
            error instanceof ApiError &&
            (error.status === 400 || error.status === 422)
          ) {
            recoveryCheckpointRef.current = null;
          }
          // 只有自动恢复被暂停(不会自愈)、或连续失败到阈值,才把报错亮给用户;
          // 偶发一次、下一轮就恢复的失败保持静默,避免"服务暂时不可用"反复跳。
          recoveryFailureStreakRef.current += 1;
          if (
            recoveryPaused ||
            recoveryFailureStreakRef.current >= RECOVERY_ERROR_VISIBLE_THRESHOLD
          ) {
            setRecoveryError(
              runtimeErrorMessage(error, "断线后消息补齐失败，请刷新会话后重试。"),
            );
          }
        }
        return false;
      } finally {
        if (
          activeConversationRef.current === conversationId &&
          recoveryOperationRef.current === operation
        ) {
          setIsRecovering(false);
        }
      }
    })();
    recoveryPromiseRef.current = recovery;
    void recovery.finally(() => {
      if (recoveryPromiseRef.current === recovery) {
        recoveryPromiseRef.current = null;
      }
    });
    return recovery;
  }, [
    conversationId,
    ensureEventTailBoundary,
    mergeRenderedRecords,
    receiptSafetyScope,
  ]);

  const refreshUnread = useCallback(async () => {
    try {
      const position = await getC19UnreadPosition(conversationId);
      if (activeConversationRef.current === conversationId) {
        setUnreadPosition(position);
      }
    } catch (error) {
      if (activeConversationRef.current === conversationId) {
        setReceiptError(runtimeErrorMessage(error, "未读位置同步失败。"));
      }
    }
  }, [conversationId]);

  recoveryRunnerRef.current = recoverFromResume;
  unreadRefreshRunnerRef.current = refreshUnread;

  useEffect(() => {
    let cancelled = false;
    receiptSafetyScopeRef.current = null;
    setRecords([]);
    renderedRecordsRef.current = [];
    renderWindowModeRef.current = "latest";
    setRenderWindowMode("latest");
    setHistoryCursor(null);
    historyPagingRef.current = {
      conversationId,
      cursor: null,
      generation: 0,
      initialized: false,
      newestWindowEvictedOlder: false,
    };
    setLatestSequence(0);
    setUnreadPosition(null);
    setResumePosition(null);
    setDraft("");
    setEmojiPickerOpen(false);
    resetAssetComposer();
    setPendingMessage(null);
    pendingMessageRef.current = null;
    sendInFlightRef.current = false;
    sendOperationRef.current += 1;
    stickToBottomRef.current = true;
    setIsSending(false);
    setIsLoadingOlder(false);
    setHistoryError("");
    setSendError("");
    setReceiptError("");
    setRecoveryError("");
    recoveryFailureStreakRef.current = 0;
    setIsRecovering(true);
    setRecoveryReady(false);
    setSafeReceiptSequence(0);
    setHistoryWindowLimited(false);
    setIsLoadingHistory(true);
    receiptInFlightRef.current = { delivered: 0, read: 0 };
    recoveryOperationRef.current += 1;
    recoveryPromiseRef.current = null;
    recoveryCheckpointRef.current = null;
    automaticRecoveryPausedRef.current = false;

    void Promise.allSettled([
      getC19UnreadPosition(conversationId),
      recoverFromResume(),
    ]).then(([unreadResult]) => {
      if (cancelled) return;

      if (unreadResult.status === "fulfilled") {
        setUnreadPosition(unreadResult.value);
      } else {
        setReceiptError(
          runtimeErrorMessage(unreadResult.reason, "未读位置读取失败。"),
        );
      }

      setIsLoadingHistory(false);
    });

    return () => {
      cancelled = true;
    };
  }, [conversationId, recoverFromResume, resetAssetComposer]);

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const frame = window.requestAnimationFrame(() => {
      const viewport = messageHistoryRef.current;
      if (viewport) viewport.scrollTop = viewport.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [records]);

  useEffect(() => {
    const onVisibilityChange = () => setVisibilityTick((current) => current + 1);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, []);

  const visibleWindowMaxSequence = records.at(-1)?.sequence ?? 0;
  const safeReadReceiptSequence =
    renderWindowMode === "older"
      ? Math.min(safeReceiptSequence, visibleWindowMaxSequence)
      : safeReceiptSequence;

  useEffect(() => {
    if (
      !isC19ReceiptSafetyScopeActive(
        receiptSafetyScopeRef.current,
        receiptSafetyScope,
      )
    ) {
      return;
    }
    if (!recoveryReady || isRecovering || safeReceiptSequence <= 0) return;
    const deliveredThrough =
      resumePosition?.delivered_through_sequence ?? 0;
    if (
      safeReceiptSequence <= deliveredThrough ||
      safeReceiptSequence <= receiptInFlightRef.current.delivered
    ) {
      return;
    }

    receiptInFlightRef.current.delivered = safeReceiptSequence;
    void advanceC19Delivery(conversationId, safeReceiptSequence)
      .then((position) => {
        if (
          !isC19ReceiptSafetyScopeActive(
            receiptSafetyScopeRef.current,
            receiptSafetyScope,
          )
        ) {
          return;
        }
        setResumePosition((current) => ({
          conversation_id: position.conversation_id,
          delivered_through_sequence: Math.max(
            current?.delivered_through_sequence ?? 0,
            position.delivered_through_sequence,
          ),
          latest_sequence: Math.max(current?.latest_sequence ?? 0, latestSequence),
          read_through_sequence: Math.max(
            current?.read_through_sequence ?? 0,
            position.read_through_sequence,
          ),
          resume_cursor: current?.resume_cursor ?? null,
          user_id: position.user_id,
        }));
        setReceiptError("");
      })
      .catch((error) => {
        if (
          isC19ReceiptSafetyScopeActive(
            receiptSafetyScopeRef.current,
            receiptSafetyScope,
          )
        ) {
          receiptInFlightRef.current.delivered = deliveredThrough;
          setReceiptError(runtimeErrorMessage(error, "已读状态更新失败。"));
        }
      });
  }, [
    conversationId,
    isRecovering,
    latestSequence,
    recoveryReady,
    receiptSafetyScope,
    resumePosition,
    safeReceiptSequence,
  ]);

  useEffect(() => {
    if (
      !isC19ReceiptSafetyScopeActive(
        receiptSafetyScopeRef.current,
        receiptSafetyScope,
      )
    ) {
      return;
    }
    if (!recoveryReady || isRecovering || safeReadReceiptSequence <= 0) return;
    if (document.visibilityState !== "visible") return;
    const readThrough = resumePosition?.read_through_sequence ?? 0;
    if (
      safeReadReceiptSequence <= readThrough ||
      safeReadReceiptSequence <= receiptInFlightRef.current.read
    ) {
      return;
    }

    receiptInFlightRef.current.read = safeReadReceiptSequence;
    void advanceC19Read(conversationId, safeReadReceiptSequence)
      .then((position) => {
        if (
          !isC19ReceiptSafetyScopeActive(
            receiptSafetyScopeRef.current,
            receiptSafetyScope,
          )
        ) {
          return;
        }
        setResumePosition((current) => ({
          conversation_id: position.conversation_id,
          delivered_through_sequence: Math.max(
            current?.delivered_through_sequence ?? 0,
            position.delivered_through_sequence,
          ),
          latest_sequence: Math.max(current?.latest_sequence ?? 0, latestSequence),
          read_through_sequence: Math.max(
            current?.read_through_sequence ?? 0,
            position.read_through_sequence,
          ),
          resume_cursor: current?.resume_cursor ?? null,
          user_id: position.user_id,
        }));
        if (safeReadReceiptSequence >= latestSequence) {
          setUnreadPosition((current) =>
            current
              ? {
                  ...current,
                  first_unread_sequence: null,
                  unread_count: 0,
                }
              : current,
          );
        } else {
          void refreshUnread();
        }
        setReceiptError("");
        announceC19UnreadChanged();
      })
      .catch((error) => {
        if (
          isC19ReceiptSafetyScopeActive(
            receiptSafetyScopeRef.current,
            receiptSafetyScope,
          )
        ) {
          receiptInFlightRef.current.read = readThrough;
          setReceiptError(runtimeErrorMessage(error, "已读位置更新失败。"));
        }
      });
  }, [
    conversationId,
    isRecovering,
    latestSequence,
    recoveryReady,
    refreshUnread,
    receiptSafetyScope,
    resumePosition,
    safeReadReceiptSequence,
    visibilityTick,
  ]);

  const processEvents = useCallback((events: C19MessageEvent[]) => {
    const unseen = events.filter((event) => {
      if (seenEventIdsRef.current.has(event.event_id)) return false;
      seenEventIdsRef.current.add(event.event_id);
      return true;
    });
    if (seenEventIdsRef.current.size > 2_000) {
      seenEventIdsRef.current = new Set(
        [...seenEventIdsRef.current].slice(-1_000),
      );
    }
    return unseen.some(
      (event) => event.conversation_id === activeConversationRef.current,
    );
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void recoverFromResume().then((recovered) => {
          if (recovered) void refreshUnread();
        });
      }
    }, STATUS_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [recoverFromResume, refreshUnread]);

  useEffect(() => {
    let stopped = false;
    let source: EventSource | null = null;
    let pollTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let handshakeTimer: number | null = null;
    let pollingActive = false;
    let pollInFlight = false;
    let streamConnecting = false;
    let streamGeneration = 0;
    let failedReconnectAttempts = 0;

    const clearHandshakeTimer = () => {
      if (handshakeTimer !== null) {
        window.clearTimeout(handshakeTimer);
        handshakeTimer = null;
      }
    };

    const recoverSelectedConversation = async () => {
      const recover = recoveryRunnerRef.current;
      if (!recover) return;
      const recoveryWasAlreadyRunning = recoveryPromiseRef.current !== null;
      let recovered = await recover();
      if (recoveryWasAlreadyRunning && !stopped) {
        // The event may have arrived after the active recovery's resume fence.
        // Run one fresh fenced pass instead of treating the coalesced promise
        // as proof that this event was included.
        await new Promise<void>((resolve) => window.queueMicrotask(resolve));
        recovered = await recoveryRunnerRef.current?.() ?? false;
      }
      if (recovered && !stopped) await unreadRefreshRunnerRef.current?.();
    };

    const drainEventPages = async (
      initialCursor: string | null,
      forceRecovery = false,
    ) => {
      let cursor = initialCursor;
      let selectedConversationChanged = false;
      const visitedCursors = new Set<string>();

      for (let pageNumber = 0; pageNumber < MAX_EVENT_DRAIN_PAGES; pageNumber += 1) {
        if (stopped) return;
        if (cursor) {
          if (visitedCursors.has(cursor)) {
            throw new Error("消息同步出现问题，请刷新会话。");
          }
          visitedCursors.add(cursor);
        }
        const page = await listC19MessageEvents({
          cursor,
          limit: EVENT_LIMIT,
        });
        if (stopped) return;
        selectedConversationChanged =
          processEvents(page.events) || selectedConversationChanged;
        if (page.next_cursor) {
          eventCursorRef.current = page.next_cursor;
          eventCursorMemory.set(String(userId), page.next_cursor);
        }

        const lastEventSequence = page.events.at(-1)?.event_sequence ?? 0;
        if (
          page.events.length === 0 ||
          lastEventSequence >= page.latest_event_sequence
        ) {
          if (selectedConversationChanged || forceRecovery) {
            await recoverSelectedConversation();
          }
          return;
        }
        if (!page.next_cursor || page.next_cursor === cursor) {
          throw new Error("消息同步出现问题，请刷新会话。");
        }
        cursor = page.next_cursor;
      }
      if (selectedConversationChanged || forceRecovery) {
        await recoverSelectedConversation();
      }
      throw new Error("待同步的消息较多，正在分批加载。");
    };

    const schedulePoll = () => {
      if (
        !stopped &&
        pollingActive &&
        !streamConnecting &&
        pollTimer === null
      ) {
        pollTimer = window.setTimeout(() => {
          pollTimer = null;
          void pollEvents();
        }, EVENT_POLL_INTERVAL_MS);
      }
    };

    const pollEvents = async () => {
      if (stopped || !pollingActive || streamConnecting || pollInFlight) return;
      pollInFlight = true;
      try {
        await ensureEventTailBoundary();
        if (!eventCursorRef.current) {
          throw new Error("消息同步尚未就绪，请稍候。");
        }
        await drainEventPages(eventCursorRef.current);
        if (stopped || !pollingActive) return;
        setConnectionMode("polling");
        if (source === null && reconnectTimer === null) scheduleReconnect();
      } catch (error) {
        if (
          !stopped &&
          error instanceof ApiError &&
          (error.status === 400 || error.status === 422) &&
          eventCursorRef.current
        ) {
          eventCursorRef.current = null;
          eventCursorMemory.delete(String(userId));
          try {
            await ensureEventTailBoundary();
            if (!eventCursorRef.current) {
              throw new Error("消息同步失败，请刷新会话。");
            }
            await recoverSelectedConversation();
            await drainEventPages(eventCursorRef.current, true);
            if (!stopped && pollingActive) {
              setConnectionMode("polling");
              if (source === null && reconnectTimer === null) {
                scheduleReconnect();
              }
            }
          } catch {
            if (!stopped && pollingActive) setConnectionMode("offline");
          }
        } else if (!stopped && pollingActive) {
          setConnectionMode("offline");
        }
      } finally {
        pollInFlight = false;
        schedulePoll();
      }
    };

    const startPolling = () => {
      if (pollingActive) return;
      pollingActive = true;
      setConnectionMode("polling");
      void pollEvents();
    };

    const scheduleReconnect = (): void => {
      if (
        stopped ||
        typeof EventSource === "undefined" ||
        reconnectTimer !== null
      ) {
        return;
      }
      const delay = c19SseReconnectDelay(failedReconnectAttempts);
      failedReconnectAttempts += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connectEventStream();
      }, delay);
    };

    const connectEventStream = (): void => {
      if (stopped || typeof EventSource === "undefined") {
        startPolling();
        return;
      }
      if (pollInFlight) {
        if (reconnectTimer === null) {
          reconnectTimer = window.setTimeout(() => {
            reconnectTimer = null;
            connectEventStream();
          }, 250);
        }
        return;
      }
      streamConnecting = true;
      clearHandshakeTimer();
      if (pollTimer !== null) {
        window.clearTimeout(pollTimer);
        pollTimer = null;
      }
      const generation = streamGeneration + 1;
      streamGeneration = generation;
      if (!pollingActive) setConnectionMode("connecting");

      let nextSource: EventSource;
      try {
        nextSource = new EventSource(c19EventStreamUrl(eventCursorRef.current), {
          withCredentials: true,
        });
      } catch {
        streamConnecting = false;
        pollingActive = false;
        startPolling();
        scheduleReconnect();
        return;
      }
      source = nextSource;

      const handleStreamFailure = () => {
        if (
          stopped ||
          generation !== streamGeneration ||
          source !== nextSource
        ) {
          return;
        }
        clearHandshakeTimer();
        nextSource.close();
        source = null;
        streamConnecting = false;
        pollingActive = false;
        startPolling();
        scheduleReconnect();
      };

      nextSource.onopen = () => {
        if (
          stopped ||
          generation !== streamGeneration ||
          source !== nextSource
        ) {
          return;
        }
        failedReconnectAttempts = 0;
        clearHandshakeTimer();
        streamConnecting = false;
        pollingActive = false;
        if (pollTimer !== null) {
          window.clearTimeout(pollTimer);
          pollTimer = null;
        }
        setConnectionMode("live");
      };
      handshakeTimer = window.setTimeout(
        handleStreamFailure,
        SSE_HANDSHAKE_TIMEOUT_MS,
      );
      nextSource.onmessage = (message) => {
        if (
          stopped ||
          generation !== streamGeneration ||
          source !== nextSource
        ) {
          return;
        }
        try {
          const payload = JSON.parse(message.data) as
            | C19MessageEvent
            | C19MessageEventPage;
          if (!("events" in payload) || !payload.next_cursor) {
            throw new Error("SSE 必须返回带 next_cursor 的事件页。");
          }
          eventCursorRef.current = payload.next_cursor;
          eventCursorMemory.set(String(userId), payload.next_cursor);
          const selectedConversationChanged = processEvents(payload.events);
          if (selectedConversationChanged) {
            void recoverSelectedConversation();
          }
        } catch {
          handleStreamFailure();
        }
      };
      nextSource.onerror = handleStreamFailure;
    };

    const onOnline = () => {
      if (stopped || typeof EventSource === "undefined") return;
      failedReconnectAttempts = 0;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      streamGeneration += 1;
      clearHandshakeTimer();
      source?.close();
      source = null;
      connectEventStream();
    };

    const onVisibilityChange = () => {
      if (document.visibilityState !== "visible" || !pollingActive) return;
      void pollEvents();
      if (source === null) onOnline();
    };

    window.addEventListener("online", onOnline);
    document.addEventListener("visibilitychange", onVisibilityChange);

    void ensureEventTailBoundary()
      .then(() => {
        if (!eventCursorRef.current) {
          throw new Error("消息同步尚未就绪，请稍候。");
        }
        return drainEventPages(eventCursorRef.current, true);
      })
      .then(() => {
        if (!stopped) connectEventStream();
      })
      .catch(() => {
        if (!stopped) {
          setConnectionMode("offline");
          startPolling();
        }
      });
    return () => {
      stopped = true;
      pollingActive = false;
      streamGeneration += 1;
      source?.close();
      clearHandshakeTimer();
      if (pollTimer !== null) window.clearTimeout(pollTimer);
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      window.removeEventListener("online", onOnline);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [
    ensureEventTailBoundary,
    processEvents,
    userId,
  ]);

  const returnToLatest = useCallback(async () => {
    const pendingRecovery = recoveryPromiseRef.current;
    if (pendingRecovery) {
      await pendingRecovery;
      if (recoveryPromiseRef.current === pendingRecovery) {
        recoveryPromiseRef.current = null;
      }
    }
    if (activeConversationRef.current !== conversationId) return;

    receiptSafetyScopeRef.current = null;
    setRecoveryReady(false);
    renderWindowModeRef.current = "latest";
    setRenderWindowMode("latest");
    renderedRecordsRef.current = [];
    setRecords([]);
    historyPagingRef.current = {
      conversationId,
      cursor: null,
      generation:
        historyPagingRef.current.conversationId === conversationId
          ? historyPagingRef.current.generation + 1
          : 0,
      initialized: false,
      newestWindowEvictedOlder: false,
    };
    setHistoryCursor(null);
    recoveryCheckpointRef.current = null;
    setHistoryError("");
    setHistoryWindowLimited(false);
    stickToBottomRef.current = true;
    setIsLoadingHistory(true);
    try {
      await recoverFromResume(true);
    } finally {
      if (activeConversationRef.current === conversationId) {
        setIsLoadingHistory(false);
      }
    }
  }, [conversationId, recoverFromResume]);

  const loadOlder = useCallback(async () => {
    if (!historyCursor || isLoadingOlder) return;
    const requestedCursor = historyCursor;
    const requestedPagingGeneration = historyPagingRef.current.generation;
    if (
      historyPagingRef.current.conversationId !== conversationId ||
      !historyPagingRef.current.initialized ||
      historyPagingRef.current.cursor !== requestedCursor
    ) {
      return;
    }
    setIsLoadingOlder(true);
    try {
      const page = await listC19MessageHistory(conversationId, {
        cursor: requestedCursor,
        limit: HISTORY_LIMIT,
      });
      if (activeConversationRef.current !== conversationId) return;
      if (
        historyPagingRef.current.conversationId !== conversationId ||
        !historyPagingRef.current.initialized ||
        historyPagingRef.current.cursor !== requestedCursor ||
        historyPagingRef.current.generation !== requestedPagingGeneration
      ) {
        return;
      }
      renderWindowModeRef.current = "older";
      setRenderWindowMode("older");
      mergeRenderedRecords(page.records, "older");
      historyPagingRef.current = {
        conversationId,
        cursor: page.next_cursor,
        generation: requestedPagingGeneration,
        initialized: true,
        newestWindowEvictedOlder: false,
      };
      setHistoryCursor(page.next_cursor);
      setLatestSequence((current) => Math.max(current, page.latest_sequence));
      setHistoryError("");
    } catch (error) {
      if (activeConversationRef.current === conversationId) {
        const requestIsStillCurrent =
          historyPagingRef.current.conversationId === conversationId &&
          historyPagingRef.current.initialized &&
          historyPagingRef.current.cursor === requestedCursor &&
          historyPagingRef.current.generation === requestedPagingGeneration;
        if (!requestIsStillCurrent) return;
        if (
          error instanceof ApiError &&
          (error.status === 400 || error.status === 422)
        ) {
          historyPagingRef.current = {
            conversationId,
            cursor: null,
            generation: requestedPagingGeneration + 1,
            initialized: false,
            newestWindowEvictedOlder: false,
          };
          setHistoryCursor(null);
        }
        setHistoryError(runtimeErrorMessage(error, "更早的消息读取失败。"));
      }
    } finally {
      if (activeConversationRef.current === conversationId) {
        setIsLoadingOlder(false);
      }
    }
  }, [conversationId, historyCursor, isLoadingOlder, mergeRenderedRecords]);

  const selectAsset = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0] ?? null;
      event.target.value = "";
      if (!file) return;
      if (renderWindowModeRef.current === "older") {
        setSendError("正在浏览历史消息，请先回到最新消息后再选择图片或文件。");
        return;
      }
      if (pendingMessageRef.current || sendInFlightRef.current) return;

      try {
        const inspected = inspectC19AssetSelection(file);
        resetAssetComposer();
        const previewUrl =
          inspected.kind === "image" ? URL.createObjectURL(file) : null;
        assetPreviewUrlRef.current = previewUrl;
        const selected = {
          clientAssetId: makeC19ClientAssetId(),
          file,
          filename: inspected.filename,
          kind: inspected.kind,
          mediaType: inspected.mediaType,
          previewUrl,
          sizeBytes: inspected.sizeBytes,
        } satisfies PendingAsset;
        setSelectedAsset(selected);
        setAssetTransfer({
          phase: "selected",
          progress: 0,
          statusText: "已选择，发送时会自动检查图片。",
        });
        setSendError("");
      } catch (error) {
        resetAssetComposer();
        setSendError(
          error instanceof Error && error.message
            ? error.message
            : "无法选择这个图片或文件。",
        );
      }
    },
    [resetAssetComposer],
  );

  const cancelAssetOperation = useCallback(() => {
    if (assetTransfer?.phase === "persisting") return;
    sendOperationRef.current += 1;
    assetAbortRef.current?.abort();
    sendInFlightRef.current = false;
    setIsSending(false);
    pendingMessageRef.current = null;
    setPendingMessage(null);
    setSendError("");
    resetAssetComposer();
  }, [assetTransfer?.phase, resetAssetComposer]);

  const transmit = useCallback(
    async (pending: PendingMessage) => {
      if (sendInFlightRef.current) return;
      const operation = sendOperationRef.current + 1;
      sendOperationRef.current = operation;
      sendInFlightRef.current = true;
      setIsSending(true);
      setSendError("");
      const controller = new AbortController();
      assetAbortRef.current?.abort();
      assetAbortRef.current = controller;
      let currentPending = pending;
      let messagePersistenceStarted = false;

      const operationIsCurrent = () =>
        activeConversationRef.current === conversationId &&
        sendOperationRef.current === operation &&
        !controller.signal.aborted;

      const rememberAsset = (asset: PendingAsset) => {
        currentPending = { ...currentPending, asset };
        if (!operationIsCurrent()) return;
        pendingMessageRef.current = currentPending;
        setPendingMessage(currentPending);
        setSelectedAsset(asset);
      };

      const updateAssetTransfer = (next: AssetTransferState) => {
        if (operationIsCurrent()) setAssetTransfer(next);
      };

      const requireUsableAssetState = (asset: C19Asset) => {
        if (asset.status === "active") return;
        if (asset.status === "rejected" || asset.status === "quarantined") {
          throw new C19AssetTransferError(
            "安全扫描拒绝了这个文件；消息没有被假定为成功。",
          );
        }
        if (
          asset.status === "deleted" ||
          asset.status === "delete_pending" ||
          asset.status === "expired"
        ) {
          throw new C19AssetTransferError(
            "上传资产已失效，请取消后重新选择文件。",
          );
        }
      };

      const requireMatchingAssetSnapshot = (
        asset: C19Asset,
        pendingAsset: PendingAsset,
      ) => {
        if (
          asset.client_asset_id !== pendingAsset.clientAssetId ||
          asset.kind !== pendingAsset.kind ||
          asset.filename !== pendingAsset.filename ||
          asset.media_type !== pendingAsset.mediaType ||
          asset.size_bytes !== pendingAsset.sizeBytes ||
          asset.sha256_hex !== pendingAsset.sha256Hex
        ) {
          throw new C19AssetTransferError(
            "图片校验不一致，已停止发送，请重新选择。",
          );
        }
      };

      try {
        if (currentPending.asset) {
          let pendingAsset = currentPending.asset;
          if (!pendingAsset.sha256Hex) {
            updateAssetTransfer({
              phase: "hashing",
              progress: 0,
              statusText: "正在准备图片…",
            });
            const sha256Hex = await sha256C19File(
              pendingAsset.file,
              controller.signal,
            );
            pendingAsset = { ...pendingAsset, sha256Hex };
            rememberAsset(pendingAsset);
          }
          if (!pendingAsset.sha256Hex) {
            throw new C19AssetTransferError("图片准备失败，请重试。");
          }

          updateAssetTransfer({
            phase: "intent",
            progress: 0,
            statusText: "正在申请一次性上传票。",
          });
          const intent = await createC19AssetUploadIntent(
            conversationId,
            {
              client_asset_id: pendingAsset.clientAssetId,
              filename: pendingAsset.filename,
              kind: pendingAsset.kind,
              media_type: pendingAsset.mediaType,
              sha256_hex: pendingAsset.sha256Hex,
              size_bytes: pendingAsset.sizeBytes,
            },
            controller.signal,
          );
          if (
            pendingAsset.assetId &&
            pendingAsset.assetId !== intent.asset.asset_id
          ) {
            throw new C19AssetTransferError("这条似乎已发送，请刷新后查看。");
          }
          pendingAsset = { ...pendingAsset, assetId: intent.asset.asset_id };
          rememberAsset(pendingAsset);
          let remoteAsset = intent.asset;
          requireMatchingAssetSnapshot(remoteAsset, pendingAsset);
          requireUsableAssetState(remoteAsset);

          if (remoteAsset.status === "pending_upload") {
            if (!intent.upload_locator) {
              throw new C19AssetTransferError(
                "资产服务没有为待上传文件签发上传票。",
              );
            }
            updateAssetTransfer({
              phase: "uploading",
              progress: 0,
              statusText: "正在上传图片…",
            });
            await putC19AssetBytes({
              file: pendingAsset.file,
              locator: assertC19UploadLocator(intent.upload_locator),
              onProgress: (progress) =>
                updateAssetTransfer({
                  phase: "uploading",
                  progress,
                  statusText:
                    progress < 100
                      ? `正在上传：${progress}%`
                      : "上传完成，等待确认…",
                }),
              signal: controller.signal,
            });
            remoteAsset = await finalizeC19AssetUpload(
              conversationId,
              remoteAsset.asset_id,
              controller.signal,
            );
            requireMatchingAssetSnapshot(remoteAsset, pendingAsset);
            requireUsableAssetState(remoteAsset);
          }

          let scanPolls = 0;
          while (remoteAsset.status !== "active") {
            if (scanPolls >= ASSET_SCAN_POLL_LIMIT) {
              throw new C19AssetTransferError(
                "安全扫描仍未完成，可使用相同资产编号继续重试。",
              );
            }
            updateAssetTransfer({
              phase: "scanning",
              progress: 100,
              statusText: "正在检查图片…",
            });
            await waitForC19AssetPoll(controller.signal);
            remoteAsset = await getC19AssetStatus(
              conversationId,
              remoteAsset.asset_id,
              controller.signal,
            );
            requireMatchingAssetSnapshot(remoteAsset, pendingAsset);
            requireUsableAssetState(remoteAsset);
            scanPolls += 1;
          }

          updateAssetTransfer({
            phase: "active",
            progress: 100,
            statusText: "安全扫描通过，正在写入消息记录。",
          });
          await waitForC19AssetPoll(controller.signal, 0);
          updateAssetTransfer({
            phase: "persisting",
            progress: 100,
            statusText: "正在保存…",
          });
        }

        messagePersistenceStarted = true;
        const persisted = await sendC19Message(conversationId, {
          asset: currentPending.asset?.assetId
            ? { asset_id: currentPending.asset.assetId }
            : undefined,
          client_message_id: currentPending.clientMessageId,
          content: currentPending.content,
          content_type: currentPending.contentType,
        }, controller.signal);
        if (
          activeConversationRef.current !== conversationId ||
          sendOperationRef.current !== operation
        ) {
          return;
        }
        mergeRenderedRecords([persisted]);
        stickToBottomRef.current = true;
        setLatestSequence((current) => Math.max(current, persisted.sequence));
        setPendingMessage(null);
        pendingMessageRef.current = null;
        setDraft("");
        if (currentPending.asset) {
          assetAbortRef.current = null;
          resetAssetComposer(false);
        }
      } catch (error) {
        if (
          activeConversationRef.current !== conversationId ||
          sendOperationRef.current !== operation
        ) {
          return;
        }
        if (error instanceof ApiError && error.status === 410) {
          pendingMessageRef.current = null;
          setPendingMessage(null);
          if (currentPending.asset) resetAssetComposer(false);
          setSendError(
            !messagePersistenceStarted
              ? "这张图片已失效，请重新选择后发送。"
              : currentPending.asset
                ? "原消息已被删除，请重新选择图片后发送。"
                : "原消息已被删除，内容已保留，再次发送即可。",
          );
          return;
        }
        const errorMessage = runtimeErrorMessage(
          error,
          currentPending.asset
            ? "消息未确认成功，请重试（不会重复发送）。"
            : "发送失败，请重试（不会重复发送）。",
        );
        setSendError(errorMessage);
        if (currentPending.asset) {
          setAssetTransfer({
            phase: "failed",
            progress: 0,
            statusText: errorMessage,
          });
        }
      } finally {
        if (sendOperationRef.current === operation) {
          sendInFlightRef.current = false;
          setIsSending(false);
        }
        if (assetAbortRef.current === controller) assetAbortRef.current = null;
      }
    },
    [conversationId, mergeRenderedRecords, resetAssetComposer],
  );

  const submitMessage = useCallback(
    (event?: FormEvent<HTMLFormElement>) => {
      event?.preventDefault();
      if (renderWindowModeRef.current === "older") {
        setSendError("正在浏览历史消息，请先回到最新消息后再发送。");
        return;
      }
      const retryMessage = pendingMessageRef.current ?? pendingMessage;
      if (retryMessage) {
        void transmit(retryMessage);
        return;
      }
      const content = draft.trim();
      if ((!content && !selectedAsset) || conversation.status !== "active") return;
      const pending = {
        asset: selectedAsset ?? undefined,
        clientMessageId: makeClientMessageId(),
        content,
        contentType: selectedAsset?.kind ?? contentTypeFor(content),
      } satisfies PendingMessage;
      setPendingMessage(pending);
      pendingMessageRef.current = pending;
      void transmit(pending);
    },
    [conversation.status, draft, pendingMessage, selectedAsset, transmit],
  );

  // 数字员工待确认卡上的按钮:替用户发一条普通文本(「确认 #ab12」),不走输入框。
  const sendQuickReply = useCallback(
    (content: string) => {
      if (conversation.status !== "active" || pendingMessageRef.current) return;
      const pending = {
        asset: undefined,
        clientMessageId: makeClientMessageId(),
        content,
        contentType: "text",
      } satisfies PendingMessage;
      setPendingMessage(pending);
      pendingMessageRef.current = pending;
      void transmit(pending);
    },
    [conversation.status, transmit],
  );

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitMessage();
    }
  };

  const insertEmoji = (emoji: string) => {
    const textarea = composerInputRef.current;
    const selectionStart = textarea?.selectionStart ?? draft.length;
    const selectionEnd = textarea?.selectionEnd ?? selectionStart;
    const nextDraft = `${draft.slice(0, selectionStart)}${emoji}${draft.slice(
      selectionEnd,
    )}`;
    if (nextDraft.length > MESSAGE_MAX_LENGTH) return;
    const nextCaret = selectionStart + emoji.length;
    setDraft(nextDraft);
    setEmojiPickerOpen(false);
    window.requestAnimationFrame(() => {
      composerInputRef.current?.focus();
      composerInputRef.current?.setSelectionRange(nextCaret, nextCaret);
    });
  };

  const selectedEmojiCategory =
    EMOJI_CATEGORIES.find((category) => category.id === emojiCategory) ??
    EMOJI_CATEGORIES[0];

  const connectionLabel =
    connectionMode === "live"
      ? "实时连接"
      : connectionMode === "polling"
        ? "备用连接"
        : connectionMode === "connecting"
          ? "正在连接"
          : "连接中断";

  return (
    <section className={styles.chatPanel} aria-labelledby="c19-chat-title">
      <header className={styles.chatHeading}>
        <div>
          <h3 id="c19-chat-title">
            {title ||
              conversation.title ||
              (conversation.type === "group" ? "群组聊天" : "单聊")}
          </h3>
          <span
            aria-live="polite"
            data-mode={connectionMode}
            role="status"
          >
            {connectionMode === "offline" ? (
              <WifiOff aria-hidden="true" size={14} />
            ) : (
              <Wifi aria-hidden="true" size={14} />
            )}
            {connectionLabel}
          </span>
        </div>
        <div className={styles.chatRuntimeState}>
          {unreadPosition?.unread_count ? (
            <strong>{unreadPosition.unread_count} 条未读</strong>
          ) : null}
          {headerActions}
        </div>
      </header>

      <div
        aria-busy={isLoadingHistory || isRecovering}
        aria-live="polite"
        className={styles.messageHistory}
        onScroll={(event) => {
          const viewport = event.currentTarget;
          stickToBottomRef.current =
            viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 120;
        }}
        ref={messageHistoryRef}
      >
        {renderWindowMode === "older" ? (
          <button
            className={styles.loadOlderButton}
            disabled={isLoadingHistory || isLoadingOlder || isRecovering}
            onClick={() => void returnToLatest()}
            type="button"
          >
            <RefreshCcw aria-hidden="true" size={15} />
            回到最新消息
          </button>
        ) : null}

        {historyCursor ? (
          <button
            className={styles.loadOlderButton}
            disabled={isLoadingOlder}
            onClick={() => void loadOlder()}
            type="button"
          >
            <ChevronUp aria-hidden="true" size={15} />
            {isLoadingOlder ? "读取中…" : "加载更早消息"}
          </button>
        ) : null}

        {isLoadingHistory ? (
          <div className={styles.chatEmpty} role="status">正在加载消息…</div>
        ) : records.length === 0 ? (
          <div className={styles.chatEmpty} role="status">
            还没有消息，可以发送第一条消息。
          </div>
        ) : (
          records.map((record) => {
            const own = isSameUser(record.sender_user_id, userId);
            const senderId = Number(record.sender_user_id);
            return (
              <article
                className={own ? styles.ownMessage : styles.peerMessage}
                key={record.record_id}
              >
                {!own ? (
                  <strong>
                    {profileNames.get(senderId) ?? "未命名成员"}
                  </strong>
                ) : null}
                {record.assets.map((asset) => (
                  <C19MessageAsset
                    asset={asset}
                    conversationId={conversationId}
                    key={`${record.record_id}:${asset.asset_id}:${asset.ordinal}`}
                    recordId={record.record_id}
                  />
                ))}
                {(record.content_type === "image" || record.content_type === "file") &&
                record.assets.length === 0 ? (
                  <small className={styles.assetInlineError}>
                    这条消息的资产引用不可用。
                  </small>
                ) : null}
                {(() => {
                  const card = own ? null : parseC19Card(record.content);
                  if (!card) {
                    return record.content ? <p>{record.content}</p> : null;
                  }
                  const isLatest = records[records.length - 1]?.record_id === record.record_id;
                  return (
                    <C19CardMessage
                      actionable={isLatest}
                      busy={Boolean(pendingMessage)}
                      card={card}
                      onAction={sendQuickReply}
                    />
                  );
                })()}
                <footer>
                  <time dateTime={record.persisted_at}>{messageTime(record.persisted_at)}</time>
                  {own ? <span>{receiptLabel(record.status)}</span> : null}
                </footer>
              </article>
            );
          })
        )}
      </div>

      {historyWindowLimited ? (
        <div className={styles.chatRuntimeWarning} role="status">
          {recoveryReady ? "历史消息已全部加载" : "正在加载历史消息"}；
          界面仅保留最近 {MAX_RENDERED_MESSAGES} 条，可使用“加载更早消息”按需查看，
          加载完成后会更新已读状态。
        </div>
      ) : null}
      {historyError ? (
        <div className={styles.chatRuntimeError} role="alert">
          <span>{historyError}</span>
          <button
            onClick={() => {
              if (
                renderWindowModeRef.current === "older" &&
                !historyPagingRef.current.initialized
              ) {
                void returnToLatest();
              } else {
                void recoverFromResume(true);
              }
            }}
            type="button"
          >
            <RefreshCcw aria-hidden="true" size={14} />重试同步
          </button>
        </div>
      ) : null}
      {recoverySlow && !isLoadingHistory ? (
        <div className={styles.chatRuntimeWarning} role="status">
          正在补齐历史消息，完成后会更新已读状态。
        </div>
      ) : null}
      {recoveryError ? (
        <div className={styles.chatRuntimeError} role="alert">
          <span>{recoveryError}</span>
          <button onClick={() => void recoverFromResume(true)} type="button">
            <RefreshCcw aria-hidden="true" size={14} />重新恢复
          </button>
        </div>
      ) : null}
      {receiptError ? (
        <div className={styles.chatRuntimeWarning} role="status">{receiptError}</div>
      ) : null}
      {renderWindowMode === "older" ? (
        <div className={styles.chatRuntimeWarning} role="status">
          正在浏览连续历史窗口；新消息保持在最新窗口，请先“回到最新消息”再发送。
        </div>
      ) : null}

      <form className={styles.composer} onSubmit={submitMessage}>
        <div className={styles.quickEmoji} ref={emojiPickerRef}>
          <button
            aria-expanded={emojiPickerOpen}
            aria-haspopup="dialog"
            aria-label="打开表情选择器"
            className={styles.emojiTrigger}
            disabled={
              renderWindowMode === "older" ||
              Boolean(pendingMessage) ||
              conversation.status !== "active"
            }
            onClick={() => setEmojiPickerOpen((current) => !current)}
            type="button"
          >
            <Smile aria-hidden="true" size={17} />
            表情
          </button>
          {emojiPickerOpen ? (
            <div
              aria-label="选择表情"
              className={styles.emojiPicker}
              role="dialog"
            >
              <div
                aria-label="表情分类"
                className={styles.emojiCategories}
                role="tablist"
              >
                {EMOJI_CATEGORIES.map((category) => (
                  <button
                    aria-selected={category.id === selectedEmojiCategory.id}
                    key={category.id}
                    onClick={() => setEmojiCategory(category.id)}
                    role="tab"
                    type="button"
                  >
                    {category.label}
                  </button>
                ))}
              </div>
              <div
                aria-label={`${selectedEmojiCategory.label}表情`}
                className={styles.emojiGrid}
                role="tabpanel"
              >
                {selectedEmojiCategory.emojis.map((emoji) => (
                  <button
                    aria-label={`插入表情 ${emoji}`}
                    key={emoji}
                    onClick={() => insertEmoji(emoji)}
                    type="button"
                  >
                    {emoji}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
        <div className={styles.assetPickerRow}>
          <input
            accept={C19_ASSET_ACCEPT}
            aria-label="选择一张图片或一个普通文件"
            className={styles.assetFileInput}
            disabled={
              renderWindowMode === "older" ||
              Boolean(pendingMessage) ||
              conversation.status !== "active"
            }
            onChange={selectAsset}
            ref={fileInputRef}
            type="file"
          />
          <button
            disabled={
              renderWindowMode === "older" ||
              Boolean(pendingMessage) ||
              conversation.status !== "active"
            }
            onClick={() => fileInputRef.current?.click()}
            type="button"
          >
            <Paperclip aria-hidden="true" size={15} />
            {selectedAsset ? "更换附件" : "添加图片或文件"}
          </button>
          <span>图片 ≤ 20 MiB · 文件 ≤ 50 MiB · 每条消息 1 个</span>
        </div>
        {selectedAsset ? (
          <div className={styles.selectedAssetCard}>
            {selectedAsset.kind === "image" && selectedAsset.previewUrl ? (
              <img
                alt={`${selectedAsset.filename} 本地预览`}
                decoding="async"
                src={selectedAsset.previewUrl}
              />
            ) : selectedAsset.kind === "image" ? (
              <ImageIcon aria-hidden="true" size={24} />
            ) : (
              <FileText aria-hidden="true" size={24} />
            )}
            <div>
              <strong>{selectedAsset.filename}</strong>
              <span aria-live="polite">
                {assetTransfer?.statusText ?? "等待发送"}
              </span>
              {assetTransfer?.phase === "uploading" ? (
                <progress max={100} value={assetTransfer.progress}>
                  {assetTransfer.progress}%
                </progress>
              ) : null}
              <small>
                {selectedAsset.clientAssetId}
                {selectedAsset.assetId ? ` · ${selectedAsset.assetId}` : ""}
              </small>
            </div>
            {isSending && assetTransfer?.phase !== "failed" ? (
              <LoaderCircle
                aria-hidden="true"
                className={styles.assetSpinner}
                size={18}
              />
            ) : null}
            <button
              aria-label="取消当前图片或文件"
              disabled={assetTransfer?.phase === "persisting"}
              onClick={cancelAssetOperation}
              type="button"
            >
              <X aria-hidden="true" size={15} />
            </button>
          </div>
        ) : null}
        <textarea
          aria-label="消息内容"
          disabled={
            renderWindowMode === "older" ||
            Boolean(pendingMessage) ||
            conversation.status !== "active"
          }
          maxLength={MESSAGE_MAX_LENGTH}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onComposerKeyDown}
          placeholder={
            renderWindowMode === "older"
              ? "请先回到最新消息后再发送"
              : selectedAsset
                ? "可填写图片或文件说明；也可以留空"
              : conversation.status === "active"
              ? "输入文字或 Emoji；Enter 发送，Shift+Enter 换行"
              : "该会话已经关闭"
          }
          rows={3}
          ref={composerInputRef}
          value={draft}
        />
        <div className={styles.composerFooter}>
          <span>
            {draft.length}/{MESSAGE_MAX_LENGTH}
          </span>
          <button
            className={styles.sendButton}
            disabled={
              isSending ||
              renderWindowMode === "older" ||
              conversation.status !== "active" ||
              (!pendingMessage && !draft.trim() && !selectedAsset)
            }
            type="submit"
          >
            <Send aria-hidden="true" size={16} />
            {isSending
              ? selectedAsset
                ? "图片处理中…"
                : "发送中…"
              : pendingMessage
                ? "安全重试"
                : "发送"}
          </button>
        </div>
        {sendError && pendingMessage ? (
          <div className={styles.pendingRetry} role="alert">
            <div>
              <strong>消息尚未确认成功</strong>
              <span>{sendError}</span>
              <small>
                重试不会制造重复消息。
              </small>
            </div>
            <button
              disabled={isSending}
              onClick={() => {
                if (pendingMessage.asset) {
                  cancelAssetOperation();
                } else {
                  setPendingMessage(null);
                  pendingMessageRef.current = null;
                  setSendError("");
                }
              }}
              type="button"
            >
              取消重试
            </button>
          </div>
        ) : null}
        {sendError && !pendingMessage ? (
          <div className={styles.chatRuntimeWarning} role="status">
            {sendError}
          </div>
        ) : null}
      </form>
    </section>
  );
}

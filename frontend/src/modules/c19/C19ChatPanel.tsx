"use client";

import {
  ChevronUp,
  MessageSquareText,
  RefreshCcw,
  Send,
  Smile,
  Wifi,
  WifiOff,
} from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent,
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
  getC19MessageEventTail,
  getC19ResumePosition,
  getC19UnreadPosition,
  listC19MessageEvents,
  listC19MessageHistory,
  sendC19Message,
} from "./api";
import {
  C19RecoverySafetyError as RecoverySafetyError,
  c19ReceiptSafetyScope,
  drainC19ForwardRecoveryBatch,
  initializeC19RecoveryWindow,
  isC19ReceiptSafetyScopeActive,
  mergeC19MessageWindow,
} from "./C19ChatRecovery";
import styles from "./C19Workspace.module.css";
import type {
  C19Conversation,
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
const SSE_RECONNECT_INTERVAL_MS = 30_000;
const STATUS_REFRESH_INTERVAL_MS = 15_000;
const MESSAGE_MAX_LENGTH = 4_000;
const QUICK_EMOJI = ["👍", "❤️", "😊", "🎉", "收到", "谢谢"] as const;
const eventCursorMemory = new Map<string, string>();

type ConnectionMode = "connecting" | "live" | "polling" | "offline";
type RenderWindowMode = "latest" | "older";

type PendingMessage = {
  clientMessageId: string;
  content: string;
  contentType: C19MessageContentType;
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
    if (error.status === 404) return "会话或消息运行时不存在。";
    if (error.status === 409) return error.message || "消息状态发生冲突，请刷新后重试。";
    if (error.status === 422) return error.message || "消息内容不符合发送规则。";
    if (error.status === 429) return "发送过于频繁，请稍后再试。";
    if (error.status >= 500) return "聊天记录服务暂时不可用，消息没有被假定为成功。";
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
  profiles,
  userId,
}: {
  conversation: C19Conversation;
  profiles: C19Profile[];
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
  const [pendingMessage, setPendingMessage] = useState<PendingMessage | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [sendError, setSendError] = useState("");
  const [receiptError, setReceiptError] = useState("");
  const [recoveryError, setRecoveryError] = useState("");
  const [isRecovering, setIsRecovering] = useState(true);
  const [recoveryReady, setRecoveryReady] = useState(false);
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
  const sendInFlightRef = useRef(false);
  const sendOperationRef = useRef(0);
  const messageHistoryRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);
  const recoveryPromiseRef = useRef<Promise<boolean> | null>(null);
  const recoveryOperationRef = useRef(0);
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
                "恢复游标发生循环，已暂停自动恢复；回执保持冻结。",
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
        if (paging.initialized) {
          setHistoryError("");
        }
        return true;
      } catch (error) {
        if (
          activeConversationRef.current === conversationId &&
          recoveryOperationRef.current === operation
        ) {
          if (error instanceof RecoverySafetyError) {
            automaticRecoveryPausedRef.current = true;
          }
          if (
            error instanceof ApiError &&
            (error.status === 400 || error.status === 422)
          ) {
            recoveryCheckpointRef.current = null;
          }
          setRecoveryError(
            runtimeErrorMessage(error, "断线消息恢复失败；送达与已读位置保持冻结。"),
          );
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
  }, [conversationId, recoverFromResume]);

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
          setReceiptError(runtimeErrorMessage(error, "送达位置更新失败。"));
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

  const processEvents = useCallback(
    (events: C19MessageEvent[]) => {
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
      return unseen.some((event) => event.conversation_id === conversationId);
    },
    [conversationId],
  );

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
    let pollingActive = false;
    let sseOpened = false;

    const recoverSelectedConversation = async () => {
      const recoveryWasAlreadyRunning = recoveryPromiseRef.current !== null;
      let recovered = await recoverFromResume();
      if (recoveryWasAlreadyRunning && !stopped) {
        // The event may have arrived after the active recovery's resume fence.
        // Run one fresh fenced pass instead of treating the coalesced promise
        // as proof that this event was included.
        await new Promise<void>((resolve) => window.queueMicrotask(resolve));
        recovered = await recoverFromResume();
      }
      if (recovered && !stopped) await refreshUnread();
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
            throw new Error("事件游标发生循环，已停止推进。");
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
          throw new Error("事件游标未能向前推进，已停止推进。");
        }
        cursor = page.next_cursor;
      }
      if (selectedConversationChanged || forceRecovery) {
        await recoverSelectedConversation();
      }
      throw new Error("事件积压超过单次安全恢复上限，将从当前游标继续。");
    };

    const schedulePoll = () => {
      if (!stopped && pollingActive) {
        pollTimer = window.setTimeout(pollEvents, EVENT_POLL_INTERVAL_MS);
      }
    };

    const pollEvents = async () => {
      if (stopped || !pollingActive) return;
      try {
        await ensureEventTailBoundary();
        if (!eventCursorRef.current) {
          throw new Error("事件尾游标尚未就绪。");
        }
        await drainEventPages(eventCursorRef.current);
        if (stopped) return;
        setConnectionMode("polling");
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
              throw new Error("事件尾游标恢复失败。");
            }
            await recoverSelectedConversation();
            await drainEventPages(eventCursorRef.current, true);
            if (!stopped) {
              setConnectionMode("polling");
            }
          } catch {
            if (!stopped) setConnectionMode("offline");
          }
        } else if (!stopped) {
          setConnectionMode("offline");
        }
      } finally {
        schedulePoll();
      }
    };

    const startPolling = () => {
      pollingActive = true;
      if (pollTimer !== null) window.clearTimeout(pollTimer);
      setConnectionMode("polling");
      void pollEvents();
    };

    const connectEventStream = () => {
      if (stopped || typeof EventSource === "undefined") {
        startPolling();
        return;
      }
      pollingActive = false;
      if (pollTimer !== null) window.clearTimeout(pollTimer);
      setConnectionMode("connecting");
      source = new EventSource(c19EventStreamUrl(eventCursorRef.current), {
        withCredentials: true,
      });
      source.onopen = () => {
        if (!stopped) {
          sseOpened = true;
          setConnectionMode("live");
        }
      };
      source.onmessage = (message) => {
        if (stopped) return;
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
          source?.close();
          startPolling();
        }
      };
      source.onerror = () => {
        const reconnectSse = sseOpened;
        sseOpened = false;
        source?.close();
        source = null;
        startPolling();
        if (reconnectSse) {
          reconnectTimer = window.setTimeout(() => {
            if (pollTimer !== null) window.clearTimeout(pollTimer);
            connectEventStream();
          }, SSE_RECONNECT_INTERVAL_MS);
        }
      };
    };

    void ensureEventTailBoundary()
      .then(() => {
        if (!eventCursorRef.current) {
          throw new Error("事件尾游标尚未就绪。");
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
      source?.close();
      if (pollTimer !== null) window.clearTimeout(pollTimer);
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
    };
  }, [
    ensureEventTailBoundary,
    processEvents,
    recoverFromResume,
    refreshUnread,
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

  const transmit = useCallback(
    async (pending: PendingMessage) => {
      if (sendInFlightRef.current) return;
      const operation = sendOperationRef.current + 1;
      sendOperationRef.current = operation;
      sendInFlightRef.current = true;
      setIsSending(true);
      setSendError("");
      try {
        const persisted = await sendC19Message(conversationId, {
          client_message_id: pending.clientMessageId,
          content: pending.content,
          content_type: pending.contentType,
        });
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
          setSendError(
            "这条消息的旧记录已经删除，原 client_message_id 不能继续重放；内容已保留，再次发送会生成新的消息编号。",
          );
          return;
        }
        setSendError(
          runtimeErrorMessage(
            error,
            "发送失败；服务端未确认持久化，可使用同一消息编号安全重试。",
          ),
        );
      } finally {
        if (sendOperationRef.current === operation) {
          sendInFlightRef.current = false;
          setIsSending(false);
        }
      }
    },
    [conversationId, mergeRenderedRecords],
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
      if (!content || conversation.status !== "active") return;
      const pending = {
        clientMessageId: makeClientMessageId(),
        content,
        contentType: contentTypeFor(content),
      } satisfies PendingMessage;
      setPendingMessage(pending);
      pendingMessageRef.current = pending;
      void transmit(pending);
    },
    [conversation.status, draft, pendingMessage, transmit],
  );

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitMessage();
    }
  };

  const connectionLabel =
    isRecovering
      ? "正在补齐断线消息"
      : connectionMode === "live"
      ? "实时连接"
      : connectionMode === "polling"
        ? "HTTP 恢复模式"
        : connectionMode === "connecting"
          ? "正在连接"
          : "连接中断";

  return (
    <section className={styles.chatPanel} aria-labelledby="c19-chat-title">
      <header className={styles.chatHeading}>
        <div>
          <span>文字与 Emoji</span>
          <h3 id="c19-chat-title">
            <MessageSquareText aria-hidden="true" size={20} />
            {conversation.title || (conversation.type === "group" ? "群组聊天" : "单聊")}
          </h3>
        </div>
        <div className={styles.chatRuntimeState}>
          <span data-mode={isRecovering ? "connecting" : connectionMode}>
            {connectionMode === "offline" ? (
              <WifiOff aria-hidden="true" size={14} />
            ) : (
              <Wifi aria-hidden="true" size={14} />
            )}
            {connectionLabel}
          </span>
          {unreadPosition?.unread_count ? (
            <strong>{unreadPosition.unread_count} 条未读</strong>
          ) : null}
        </div>
      </header>

      <div
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
          <div className={styles.chatEmpty} role="status">正在读取持久化消息…</div>
        ) : records.length === 0 ? (
          <div className={styles.chatEmpty}>还没有消息，可以发送第一条文字或 Emoji。</div>
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
                    {profileNames.get(senderId) ?? `成员 #${record.sender_user_id}`}
                  </strong>
                ) : null}
                <p>{record.content}</p>
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
          {recoveryReady ? "大量消息已按游标完整校验" : "正在分批校验大量消息"}；
          界面仅保留最近 {MAX_RENDERED_MESSAGES} 条，可使用“加载更早消息”按需查看，
          回执不会跨越未恢复区间。
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
      {isRecovering && !isLoadingHistory ? (
        <div className={styles.chatRuntimeWarning} role="status">
          正在按恢复游标连续补齐消息；完成前不会推进送达或已读位置。
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
        <div className={styles.quickEmoji} aria-label="快捷 Emoji">
          <Smile aria-hidden="true" size={16} />
          {QUICK_EMOJI.map((emoji) => (
            <button
              disabled={
                renderWindowMode === "older" ||
                Boolean(pendingMessage) ||
                conversation.status !== "active"
              }
              key={emoji}
              onClick={() =>
                setDraft((current) =>
                  `${current}${current && !current.endsWith(" ") ? " " : ""}${emoji}`,
                )
              }
              type="button"
            >
              {emoji}
            </button>
          ))}
        </div>
        <textarea
          aria-label="C19 消息内容"
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
              : conversation.status === "active"
              ? "输入文字或 Emoji；Enter 发送，Shift+Enter 换行"
              : "该会话已经关闭"
          }
          rows={3}
          value={draft}
        />
        <div className={styles.composerFooter}>
          <span>
            {draft.length}/{MESSAGE_MAX_LENGTH} · 图片、文件、朋友圈及音视频未开放
          </span>
          <button
            className={styles.sendButton}
            disabled={
              isSending ||
              renderWindowMode === "older" ||
              conversation.status !== "active" ||
              (!pendingMessage && !draft.trim())
            }
            type="submit"
          >
            <Send aria-hidden="true" size={16} />
            {isSending ? "持久化中…" : pendingMessage ? "安全重试" : "发送"}
          </button>
        </div>
        {sendError && pendingMessage ? (
          <div className={styles.pendingRetry} role="alert">
            <div>
              <strong>消息尚未确认成功</strong>
              <span>{sendError}</span>
              <small>重试会复用同一 client_message_id，不会制造重复消息。</small>
            </div>
            <button
              disabled={isSending}
              onClick={() => {
                setPendingMessage(null);
                pendingMessageRef.current = null;
                setSendError("");
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

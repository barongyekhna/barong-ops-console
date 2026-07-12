"use client";

import { LoaderCircle, RefreshCcw, Sparkles, Wifi, WifiOff } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

import {
  c19MomentEventStreamUrl,
  getC19Moment,
  getC19MomentEventTail,
  listC19MomentEvents,
  listC19MomentFeed,
} from "./api";
import { C19MomentCard } from "./C19MomentCard";
import { C19MomentComposer } from "./C19MomentComposer";
import {
  c19MomentEventRequiresRemoval,
  mergeC19MomentFeed,
  removeC19Moment,
  replaceC19Moment,
} from "./C19MomentRuntime";
import styles from "./C19Moments.module.css";
import type {
  C19Moment,
  C19MomentEvent,
  C19MomentEventPage,
  C19Profile,
} from "./types";

const FEED_LIMIT = 30;
const EVENT_LIMIT = 200;
const MAX_EVENT_DRAIN_PAGES = 50;
const EVENT_POLL_INTERVAL_MS = 4_000;
const SSE_RECONNECT_INTERVAL_MS = 30_000;
const momentEventCursorMemory = new Map<string, string>();

type ConnectionMode = "connecting" | "live" | "polling" | "offline";

function feedErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "登录状态已失效，请重新登录。";
    if (error.status === 403) return "这条朋友圈已因关系或可见范围变化而不可读。";
    if (error.status === 404) return "朋友圈运行时不可用。";
    if (error.status === 422) return "朋友圈游标已失效，正在从最新内容恢复。";
    if (error.status === 429) return "朋友圈同步过于频繁，请稍后再试。";
    if (error.status >= 500) return "朋友圈服务暂时不可用。";
    return error.message || "朋友圈读取失败。";
  }
  return error instanceof Error && error.message
    ? error.message
    : "朋友圈读取失败。";
}

export function C19MomentsPanel({
  profile,
  userId,
}: {
  profile: C19Profile;
  userId: number;
}) {
  const [moments, setMoments] = useState<C19Moment[]>([]);
  const [feedCursor, setFeedCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [feedError, setFeedError] = useState("");
  const [eventError, setEventError] = useState("");
  const [connectionMode, setConnectionMode] =
    useState<ConnectionMode>("connecting");
  const [eventsReady, setEventsReady] = useState(false);
  const activeRef = useRef(true);
  const feedGenerationRef = useRef(0);
  const feedAbortRef = useRef<AbortController | null>(null);
  const eventCursorRef = useRef<string | null>(
    momentEventCursorMemory.get(String(userId)) ?? null,
  );
  const seenEventIdsRef = useRef(new Set<string>());

  const rememberEventCursor = useCallback(
    (cursor: string) => {
      eventCursorRef.current = cursor;
      momentEventCursorMemory.set(String(userId), cursor);
    },
    [userId],
  );

  const removeMoment = useCallback((momentId: string) => {
    setMoments((current) => removeC19Moment(current, momentId));
  }, []);

  const replaceMoment = useCallback((moment: C19Moment) => {
    setMoments((current) => replaceC19Moment(current, moment));
  }, []);

  const prependMoment = useCallback((moment: C19Moment) => {
    setMoments((current) => mergeC19MomentFeed(current, [moment], "prepend"));
  }, []);

  const refreshFeed = useCallback(async () => {
    const generation = feedGenerationRef.current + 1;
    feedGenerationRef.current = generation;
    const controller = new AbortController();
    feedAbortRef.current?.abort();
    feedAbortRef.current = controller;
    setIsLoading(true);
    setFeedError("");
    try {
      const page = await listC19MomentFeed(
        { limit: FEED_LIMIT },
        controller.signal,
      );
      if (
        !activeRef.current ||
        controller.signal.aborted ||
        feedGenerationRef.current !== generation
      ) {
        return false;
      }
      setMoments(page.moments);
      setFeedCursor(page.next_cursor);
      return true;
    } catch (error) {
      if (activeRef.current && !controller.signal.aborted) {
        setFeedError(feedErrorMessage(error));
      }
      return false;
    } finally {
      if (
        activeRef.current &&
        feedGenerationRef.current === generation &&
        !controller.signal.aborted
      ) {
        setIsLoading(false);
      }
      if (feedAbortRef.current === controller) feedAbortRef.current = null;
    }
  }, []);

  const processEvents = useCallback(
    async (events: C19MomentEvent[]) => {
      for (const event of events) {
        if (seenEventIdsRef.current.has(event.event_id)) continue;
        if (c19MomentEventRequiresRemoval(event)) {
          removeMoment(event.moment_id);
          seenEventIdsRef.current.add(event.event_id);
          continue;
        }
        try {
          const canonical = await getC19Moment(event.moment_id);
          if (!activeRef.current) return;
          if (event.event_type === "published") prependMoment(canonical);
          else replaceMoment(canonical);
          seenEventIdsRef.current.add(event.event_id);
        } catch (error) {
          if (
            error instanceof ApiError &&
            (error.status === 403 || error.status === 404)
          ) {
            removeMoment(event.moment_id);
            seenEventIdsRef.current.add(event.event_id);
            continue;
          }
          throw error;
        }
      }
      if (seenEventIdsRef.current.size > 5_000) {
        seenEventIdsRef.current = new Set(
          [...seenEventIdsRef.current].slice(-2_500),
        );
      }
    },
    [prependMoment, removeMoment, replaceMoment],
  );

  const drainEventPages = useCallback(
    async (initialCursor: string) => {
      let cursor = initialCursor;
      const visited = new Set<string>();
      for (let pageNumber = 0; pageNumber < MAX_EVENT_DRAIN_PAGES; pageNumber += 1) {
        if (!activeRef.current) return;
        if (visited.has(cursor)) throw new Error("朋友圈事件游标发生循环。");
        visited.add(cursor);
        const page = await listC19MomentEvents({ cursor, limit: EVENT_LIMIT });
        if (!activeRef.current) return;
        await processEvents(page.events);
        if (!activeRef.current) return;
        if (page.next_cursor) rememberEventCursor(page.next_cursor);
        const lastSequence = page.events.at(-1)?.event_sequence ?? 0;
        if (
          page.events.length === 0 ||
          lastSequence >= page.latest_event_sequence
        ) {
          return;
        }
        if (!page.next_cursor || page.next_cursor === cursor) {
          throw new Error("朋友圈事件游标未能向前推进。");
        }
        cursor = page.next_cursor;
      }
      throw new Error("朋友圈事件积压超过单次安全恢复上限。");
    },
    [processEvents, rememberEventCursor],
  );

  const resetEventFenceAndFeed = useCallback(async () => {
    eventCursorRef.current = null;
    momentEventCursorMemory.delete(String(userId));
    seenEventIdsRef.current = new Set();
    const tail = await getC19MomentEventTail();
    if (!activeRef.current) return;
    rememberEventCursor(tail.cursor);
    setMoments([]);
    setFeedCursor(null);
    await refreshFeed();
    if (!activeRef.current) return;
    await drainEventPages(tail.cursor);
  }, [drainEventPages, refreshFeed, rememberEventCursor, userId]);

  const loadMore = useCallback(async () => {
    if (!feedCursor || isLoadingMore) return;
    const requestedCursor = feedCursor;
    const requestedGeneration = feedGenerationRef.current;
    setIsLoadingMore(true);
    setFeedError("");
    try {
      const page = await listC19MomentFeed({
        cursor: requestedCursor,
        limit: FEED_LIMIT,
      });
      if (
        !activeRef.current ||
        requestedGeneration !== feedGenerationRef.current
      ) {
        return;
      }
      if (page.next_cursor === requestedCursor) {
        throw new Error("朋友圈分页游标未能向前推进。");
      }
      setMoments((current) => mergeC19MomentFeed(current, page.moments, "append"));
      setFeedCursor(page.next_cursor);
    } catch (error) {
      if (!activeRef.current) return;
      if (
        error instanceof ApiError &&
        (error.status === 400 || error.status === 422)
      ) {
        await refreshFeed();
      } else {
        setFeedError(feedErrorMessage(error));
      }
    } finally {
      if (activeRef.current) setIsLoadingMore(false);
    }
  }, [feedCursor, isLoadingMore, refreshFeed]);

  useEffect(() => {
    activeRef.current = true;
    eventCursorRef.current = momentEventCursorMemory.get(String(userId)) ?? null;
    seenEventIdsRef.current = new Set();
    setMoments([]);
    setFeedCursor(null);
    setEventsReady(false);
    setEventError("");
    setConnectionMode("connecting");
    void (async () => {
      try {
        if (!eventCursorRef.current) {
          const tail = await getC19MomentEventTail();
          if (!activeRef.current) return;
          rememberEventCursor(tail.cursor);
        }
        const cursor = eventCursorRef.current;
        await refreshFeed();
        if (!activeRef.current || !cursor) return;
        try {
          await drainEventPages(cursor);
        } catch (error) {
          if (
            error instanceof ApiError &&
            (error.status === 400 || error.status === 422)
          ) {
            await resetEventFenceAndFeed();
          } else {
            throw error;
          }
        }
      } catch (error) {
        if (activeRef.current) {
          setEventError(feedErrorMessage(error));
          if (moments.length === 0) await refreshFeed();
        }
      } finally {
        if (activeRef.current) setEventsReady(true);
      }
    })();
    return () => {
      activeRef.current = false;
      feedAbortRef.current?.abort();
    };
    // `moments` is deliberately excluded: bootstrap owns only the mount/user fence.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drainEventPages, refreshFeed, rememberEventCursor, resetEventFenceAndFeed, userId]);

  useEffect(() => {
    if (!eventsReady) return;
    let stopped = false;
    let source: EventSource | null = null;
    let pollTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let cycleTimer: number | null = null;
    let polling = false;
    let eventQueue = Promise.resolve();
    let streamPageFailed = false;
    let streamGeneration = 0;

    const schedulePoll = () => {
      if (!stopped && polling) {
        pollTimer = window.setTimeout(pollEvents, EVENT_POLL_INTERVAL_MS);
      }
    };

    const recoverCursor = async () => {
      try {
        await resetEventFenceAndFeed();
      } catch (error) {
        if (!stopped) setEventError(feedErrorMessage(error));
        throw error;
      }
    };

    const pollEvents = async () => {
      if (stopped || !polling) return;
      try {
        if (!eventCursorRef.current) await recoverCursor();
        if (!eventCursorRef.current) throw new Error("朋友圈事件尾游标尚未就绪。");
        await drainEventPages(eventCursorRef.current);
        if (!stopped) {
          setConnectionMode("polling");
          setEventError("");
        }
      } catch (error) {
        if (
          !stopped &&
          error instanceof ApiError &&
          (error.status === 400 || error.status === 422)
        ) {
          try {
            await recoverCursor();
          } catch {
            if (!stopped) setConnectionMode("offline");
          }
        } else if (!stopped) {
          setConnectionMode("offline");
          setEventError(feedErrorMessage(error));
        }
      } finally {
        schedulePoll();
      }
    };

    const startPolling = () => {
      polling = true;
      if (pollTimer !== null) window.clearTimeout(pollTimer);
      setConnectionMode("polling");
      void pollEvents();
    };

    const acceptEventPage = async (page: C19MomentEventPage) => {
      if (stopped) return;
      if (!page.next_cursor) throw new Error("SSE 必须返回带 next_cursor 的朋友圈事件页。");
      await processEvents(page.events);
      if (!stopped) {
        rememberEventCursor(page.next_cursor);
        setEventError("");
      }
    };

    const connect = () => {
      if (stopped || typeof EventSource === "undefined") {
        startPolling();
        return;
      }
      polling = false;
      streamPageFailed = false;
      const generation = streamGeneration + 1;
      streamGeneration = generation;
      if (pollTimer !== null) window.clearTimeout(pollTimer);
      setConnectionMode("connecting");
      source = new EventSource(c19MomentEventStreamUrl(eventCursorRef.current), {
        withCredentials: true,
      });
      source.onopen = () => {
        if (stopped || generation !== streamGeneration) return;
        setConnectionMode("live");
        cycleTimer = window.setTimeout(() => {
          if (stopped || generation !== streamGeneration) return;
          source?.close();
          source = null;
          startPolling();
          reconnectTimer = window.setTimeout(connect, 250);
        }, SSE_RECONNECT_INTERVAL_MS);
      };
      source.onmessage = (message) => {
        if (
          stopped ||
          streamPageFailed ||
          generation !== streamGeneration
        ) {
          return;
        }
        try {
          const payload = JSON.parse(message.data) as
            | C19MomentEvent
            | C19MomentEventPage;
          if (!("events" in payload)) throw new Error("朋友圈 SSE 页面格式无效。");
          eventQueue = eventQueue
            .then(async () => {
              if (
                stopped ||
                streamPageFailed ||
                generation !== streamGeneration
              ) {
                return;
              }
              await acceptEventPage(payload);
            })
            .catch((error) => {
              if (!stopped && generation === streamGeneration) {
                streamPageFailed = true;
                setEventError(feedErrorMessage(error));
                source?.close();
                source = null;
                startPolling();
              }
            });
        } catch (error) {
          if (generation !== streamGeneration) return;
          streamPageFailed = true;
          setEventError(feedErrorMessage(error));
          source?.close();
          source = null;
          startPolling();
        }
      };
      source.onerror = () => {
        if (stopped || generation !== streamGeneration) return;
        if (cycleTimer !== null) window.clearTimeout(cycleTimer);
        source?.close();
        source = null;
        startPolling();
        reconnectTimer = window.setTimeout(connect, SSE_RECONNECT_INTERVAL_MS);
      };
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible" && polling) void pollEvents();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    connect();
    return () => {
      stopped = true;
      polling = false;
      source?.close();
      if (pollTimer !== null) window.clearTimeout(pollTimer);
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      if (cycleTimer !== null) window.clearTimeout(cycleTimer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [drainEventPages, eventsReady, processEvents, rememberEventCursor, resetEventFenceAndFeed]);

  const connectionLabel =
    connectionMode === "live"
      ? "朋友圈实时连接"
      : connectionMode === "polling"
        ? "朋友圈恢复模式"
        : connectionMode === "connecting"
          ? "正在连接朋友圈"
          : "朋友圈连接中断";

  return (
    <section className={styles.momentsWorkspace} aria-labelledby="c19-moments-title">
      <aside>
        <C19MomentComposer onPublished={prependMoment} profile={profile} />
      </aside>
      <div aria-busy={isLoading || isLoadingMore} className={styles.feedColumn}>
        <header className={styles.feedHeading}>
          <div>
            <span>Moments</span>
            <h3 id="c19-moments-title"><Sparkles aria-hidden="true" size={20} />朋友圈</h3>
            <p>只显示服务器按当前关系和可见范围授权的动态。</p>
          </div>
          <div className={styles.feedRuntime}>
            <span aria-live="polite" data-mode={connectionMode} role="status">
              {connectionMode === "offline" ? (
                <WifiOff aria-hidden="true" size={14} />
              ) : (
                <Wifi aria-hidden="true" size={14} />
              )}
              {connectionLabel}
            </span>
            <button disabled={isLoading} onClick={() => void refreshFeed()} type="button">
              <RefreshCcw aria-hidden="true" size={14} />刷新动态
            </button>
          </div>
        </header>

        {feedError ? (
          <div className={styles.runtimeError} role="alert">
            <span>{feedError}</span>
            <button disabled={isLoading} onClick={() => void refreshFeed()} type="button">
              <RefreshCcw aria-hidden="true" size={13} />重试
            </button>
          </div>
        ) : null}
        {eventError ? <div className={styles.runtimeWarning} role="status">{eventError}</div> : null}
        {isLoading && moments.length === 0 ? (
          <div className={styles.feedState} role="status">
            <LoaderCircle aria-hidden="true" className={styles.spinner} size={20} />
            正在读取朋友圈…
          </div>
        ) : null}
        {!isLoading && moments.length === 0 && !feedError ? (
          <div className={styles.feedState}>还没有可见的朋友圈，可以发布第一条。</div>
        ) : null}

        <div className={styles.momentList}>
          {moments.map((moment) => (
            <C19MomentCard
              currentUserId={userId}
              key={moment.moment_id}
              moment={moment}
              onChanged={replaceMoment}
              onRemoved={removeMoment}
            />
          ))}
        </div>
        {feedCursor ? (
          <button
            className={styles.loadMoreButton}
            disabled={isLoadingMore}
            onClick={() => void loadMore()}
            type="button"
          >
            {isLoadingMore ? (
              <><LoaderCircle className={styles.spinner} size={15} />读取中…</>
            ) : (
              "加载更早朋友圈"
            )}
          </button>
        ) : null}
      </div>
    </section>
  );
}

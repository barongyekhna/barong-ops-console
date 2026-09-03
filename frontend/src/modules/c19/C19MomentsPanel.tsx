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
import { c19SseReconnectDelay } from "./C19EventStreamRecovery";
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
const SSE_HANDSHAKE_TIMEOUT_MS = 12_000;
const SSE_STREAM_REFRESH_INTERVAL_MS = 30_000;
const momentEventCursorMemory = new Map<string, string>();

type ConnectionMode = "connecting" | "live" | "polling" | "offline";

function feedErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "登录状态已失效，请重新登录。";
    if (error.status === 403) return "这条朋友圈已因关系或可见范围变化而不可读。";
    if (error.status === 404) return "朋友圈暂时打不开，请稍后再试。";
    if (error.status === 422) return "朋友圈已更新，正在刷新到最新。";
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
  const bootstrapGenerationRef = useRef(0);
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
    const bootstrapGeneration = bootstrapGenerationRef.current;
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
        bootstrapGenerationRef.current !== bootstrapGeneration ||
        controller.signal.aborted ||
        feedGenerationRef.current !== generation
      ) {
        return false;
      }
      setMoments(page.moments);
      setFeedCursor(page.next_cursor);
      return true;
    } catch (error) {
      if (
        activeRef.current &&
        bootstrapGenerationRef.current === bootstrapGeneration &&
        !controller.signal.aborted
      ) {
        setFeedError(feedErrorMessage(error));
      }
      return false;
    } finally {
      if (
        activeRef.current &&
        bootstrapGenerationRef.current === bootstrapGeneration &&
        feedGenerationRef.current === generation &&
        !controller.signal.aborted
      ) {
        setIsLoading(false);
      }
      if (feedAbortRef.current === controller) feedAbortRef.current = null;
    }
  }, []);

  const processEvents = useCallback(
    async (
      events: C19MomentEvent[],
      isCurrent: () => boolean = () => activeRef.current,
    ) => {
      for (const event of events) {
        if (!activeRef.current || !isCurrent()) return;
        if (seenEventIdsRef.current.has(event.event_id)) continue;
        if (c19MomentEventRequiresRemoval(event)) {
          if (!isCurrent()) return;
          removeMoment(event.moment_id);
          seenEventIdsRef.current.add(event.event_id);
          continue;
        }
        try {
          const canonical = await getC19Moment(event.moment_id);
          if (!activeRef.current || !isCurrent()) return;
          if (event.event_type === "published") prependMoment(canonical);
          else replaceMoment(canonical);
          if (!isCurrent()) return;
          seenEventIdsRef.current.add(event.event_id);
        } catch (error) {
          if (
            error instanceof ApiError &&
            (error.status === 403 || error.status === 404)
          ) {
            if (!isCurrent()) return;
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
    async (
      initialCursor: string,
      isCurrent: () => boolean = () => activeRef.current,
    ) => {
      let cursor = initialCursor;
      const visited = new Set<string>();
      for (let pageNumber = 0; pageNumber < MAX_EVENT_DRAIN_PAGES; pageNumber += 1) {
        if (!activeRef.current || !isCurrent()) return;
        if (visited.has(cursor)) throw new Error("朋友圈同步出现问题，请刷新。");
        visited.add(cursor);
        const page = await listC19MomentEvents({ cursor, limit: EVENT_LIMIT });
        if (!activeRef.current || !isCurrent()) return;
        await processEvents(page.events, isCurrent);
        if (!activeRef.current || !isCurrent()) return;
        if (page.next_cursor) rememberEventCursor(page.next_cursor);
        const lastSequence = page.events.at(-1)?.event_sequence ?? 0;
        if (
          page.events.length === 0 ||
          lastSequence >= page.latest_event_sequence
        ) {
          return;
        }
        if (!page.next_cursor || page.next_cursor === cursor) {
          throw new Error("朋友圈同步出现问题，请刷新。");
        }
        cursor = page.next_cursor;
      }
      throw new Error("朋友圈事件积压超过单次安全恢复上限。");
    },
    [processEvents, rememberEventCursor],
  );

  const resetEventFenceAndFeed = useCallback(async (
    isCurrent: () => boolean = () => activeRef.current,
  ) => {
    if (!activeRef.current || !isCurrent()) return;
    eventCursorRef.current = null;
    momentEventCursorMemory.delete(String(userId));
    seenEventIdsRef.current = new Set();
    const tail = await getC19MomentEventTail();
    if (!activeRef.current || !isCurrent()) return;
    rememberEventCursor(tail.cursor);
    setMoments([]);
    setFeedCursor(null);
    await refreshFeed();
    if (!activeRef.current || !isCurrent()) return;
    await drainEventPages(tail.cursor, isCurrent);
  }, [drainEventPages, refreshFeed, rememberEventCursor, userId]);

  const loadMore = useCallback(async () => {
    if (!feedCursor || isLoadingMore) return;
    const requestedBootstrapGeneration = bootstrapGenerationRef.current;
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
        bootstrapGenerationRef.current !== requestedBootstrapGeneration ||
        requestedGeneration !== feedGenerationRef.current
      ) {
        return;
      }
      if (page.next_cursor === requestedCursor) {
        throw new Error("朋友圈加载出现问题，请刷新。");
      }
      setMoments((current) => mergeC19MomentFeed(current, page.moments, "append"));
      setFeedCursor(page.next_cursor);
    } catch (error) {
      if (
        !activeRef.current ||
        bootstrapGenerationRef.current !== requestedBootstrapGeneration
      ) {
        return;
      }
      if (
        error instanceof ApiError &&
        (error.status === 400 || error.status === 422)
      ) {
        await refreshFeed();
      } else {
        setFeedError(feedErrorMessage(error));
      }
    } finally {
      if (
        activeRef.current &&
        bootstrapGenerationRef.current === requestedBootstrapGeneration
      ) {
        setIsLoadingMore(false);
      }
    }
  }, [feedCursor, isLoadingMore, refreshFeed]);

  useEffect(() => {
    const bootstrapGeneration = bootstrapGenerationRef.current + 1;
    bootstrapGenerationRef.current = bootstrapGeneration;
    activeRef.current = true;
    const isCurrentBootstrap = () =>
      activeRef.current &&
      bootstrapGenerationRef.current === bootstrapGeneration;
    eventCursorRef.current = momentEventCursorMemory.get(String(userId)) ?? null;
    seenEventIdsRef.current = new Set();
    setMoments([]);
    setFeedCursor(null);
    setEventsReady(false);
    setEventError("");
    setConnectionMode("connecting");
    void (async () => {
      let feedLoaded = false;
      try {
        if (!eventCursorRef.current) {
          const tail = await getC19MomentEventTail();
          if (!isCurrentBootstrap()) return;
          rememberEventCursor(tail.cursor);
        }
        const cursor = eventCursorRef.current;
        feedLoaded = await refreshFeed();
        if (!isCurrentBootstrap() || !cursor) return;
        try {
          await drainEventPages(cursor, isCurrentBootstrap);
        } catch (error) {
          if (!isCurrentBootstrap()) return;
          if (
            error instanceof ApiError &&
            (error.status === 400 || error.status === 422)
          ) {
            await resetEventFenceAndFeed(isCurrentBootstrap);
          } else {
            throw error;
          }
        }
      } catch (error) {
        if (isCurrentBootstrap()) {
          setEventError(feedErrorMessage(error));
          if (!feedLoaded) await refreshFeed();
        }
      } finally {
        if (isCurrentBootstrap()) setEventsReady(true);
      }
    })();
    return () => {
      if (bootstrapGenerationRef.current === bootstrapGeneration) {
        bootstrapGenerationRef.current += 1;
        activeRef.current = false;
      }
      feedAbortRef.current?.abort();
    };
  }, [drainEventPages, refreshFeed, rememberEventCursor, resetEventFenceAndFeed, userId]);

  useEffect(() => {
    if (!eventsReady) return;
    let stopped = false;
    let source: EventSource | null = null;
    let pollTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let cycleTimer: number | null = null;
    let handshakeTimer: number | null = null;
    let polling = false;
    let eventQueue = Promise.resolve();
    let eventPageInFlight = false;
    let pollInFlight = false;
    let streamConnecting = false;
    let streamPageFailed = false;
    let streamGeneration = 0;
    let failedReconnectAttempts = 0;

    const clearHandshakeTimer = () => {
      if (handshakeTimer !== null) {
        window.clearTimeout(handshakeTimer);
        handshakeTimer = null;
      }
    };

    const schedulePoll = () => {
      if (!stopped && polling && !streamConnecting && pollTimer === null) {
        pollTimer = window.setTimeout(() => {
          pollTimer = null;
          void pollEvents();
        }, EVENT_POLL_INTERVAL_MS);
      }
    };

    const recoverCursor = async () => {
      try {
        await resetEventFenceAndFeed(
          () => !stopped && polling && !streamConnecting,
        );
      } catch (error) {
        if (!stopped) setEventError(feedErrorMessage(error));
        throw error;
      }
    };

    const pollEvents = async () => {
      if (stopped || !polling || streamConnecting || pollInFlight) return;
      if (eventPageInFlight) {
        schedulePoll();
        return;
      }
      pollInFlight = true;
      try {
        if (!eventCursorRef.current) await recoverCursor();
        if (!eventCursorRef.current) throw new Error("朋友圈同步尚未就绪，请稍候。");
        await drainEventPages(
          eventCursorRef.current,
          () => !stopped && polling && !streamConnecting,
        );
        if (!stopped && polling) {
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
            if (!stopped && polling) setConnectionMode("offline");
          }
        } else if (!stopped && polling) {
          setConnectionMode("offline");
          setEventError(feedErrorMessage(error));
        }
      } finally {
        pollInFlight = false;
        schedulePoll();
      }
    };

    const startPolling = () => {
      if (polling) return;
      polling = true;
      setConnectionMode("polling");
      void pollEvents();
    };

    const scheduleReconnect = (): void => {
      if (stopped || typeof EventSource === "undefined") return;
      if (reconnectTimer !== null) return;
      const delay = c19SseReconnectDelay(failedReconnectAttempts);
      failedReconnectAttempts += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };

    const acceptEventPage = async (
      page: C19MomentEventPage,
      generation: number,
    ) => {
      if (stopped || generation !== streamGeneration || streamPageFailed) return;
      if (!page.next_cursor) throw new Error("SSE 必须返回带 next_cursor 的朋友圈事件页。");
      await processEvents(
        page.events,
        () =>
          !stopped &&
          generation === streamGeneration &&
          !streamPageFailed,
      );
      if (
        !stopped &&
        generation === streamGeneration &&
        !streamPageFailed
      ) {
        rememberEventCursor(page.next_cursor);
        setEventError("");
      }
    };

    const connect = (): void => {
      if (stopped || typeof EventSource === "undefined") {
        startPolling();
        return;
      }
      if (pollInFlight || eventPageInFlight) {
        if (reconnectTimer === null) {
          reconnectTimer = window.setTimeout(() => {
            reconnectTimer = null;
            connect();
          }, 250);
        }
        return;
      }
      streamConnecting = true;
      clearHandshakeTimer();
      polling = false;
      if (pollTimer !== null) {
        window.clearTimeout(pollTimer);
        pollTimer = null;
      }
      streamPageFailed = false;
      const generation = streamGeneration + 1;
      streamGeneration = generation;
      if (!polling) setConnectionMode("connecting");
      let nextSource: EventSource;
      try {
        nextSource = new EventSource(c19MomentEventStreamUrl(eventCursorRef.current), {
          withCredentials: true,
        });
      } catch {
        source = null;
        streamConnecting = false;
        startPolling();
        scheduleReconnect();
        return;
      }
      source = nextSource;
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
        polling = false;
        if (pollTimer !== null) {
          window.clearTimeout(pollTimer);
          pollTimer = null;
        }
        setConnectionMode("live");
        cycleTimer = window.setTimeout(() => {
          if (
            stopped ||
            generation !== streamGeneration ||
            source !== nextSource
          ) {
            return;
          }
          streamPageFailed = true;
          nextSource.close();
          source = null;
          streamConnecting = false;
          polling = false;
          startPolling();
          if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
          reconnectTimer = window.setTimeout(() => {
            reconnectTimer = null;
            connect();
          }, 250);
        }, SSE_STREAM_REFRESH_INTERVAL_MS);
      };
      handshakeTimer = window.setTimeout(() => {
        if (
          stopped ||
          generation !== streamGeneration ||
          source !== nextSource
        ) {
          return;
        }
        clearHandshakeTimer();
        streamPageFailed = true;
        nextSource.close();
        source = null;
        streamConnecting = false;
        polling = false;
        startPolling();
        scheduleReconnect();
      }, SSE_HANDSHAKE_TIMEOUT_MS);
      nextSource.onmessage = (message) => {
        if (
          stopped ||
          streamPageFailed ||
          generation !== streamGeneration ||
          source !== nextSource
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
              eventPageInFlight = true;
              try {
                await acceptEventPage(payload, generation);
              } finally {
                eventPageInFlight = false;
              }
            })
            .catch((error) => {
              if (
                !stopped &&
                generation === streamGeneration &&
                source === nextSource
              ) {
                streamPageFailed = true;
                setEventError(feedErrorMessage(error));
                nextSource.close();
                source = null;
                streamConnecting = false;
                polling = false;
                startPolling();
                scheduleReconnect();
              }
            });
        } catch (error) {
          if (
            generation !== streamGeneration ||
            source !== nextSource
          ) {
            return;
          }
          streamPageFailed = true;
          setEventError(feedErrorMessage(error));
          nextSource.close();
          source = null;
          streamConnecting = false;
          polling = false;
          startPolling();
          scheduleReconnect();
        }
      };
      nextSource.onerror = () => {
        if (
          stopped ||
          generation !== streamGeneration ||
          source !== nextSource
        ) {
          return;
        }
        clearHandshakeTimer();
        if (cycleTimer !== null) window.clearTimeout(cycleTimer);
        streamPageFailed = true;
        nextSource.close();
        source = null;
        streamConnecting = false;
        polling = false;
        startPolling();
        scheduleReconnect();
      };
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible" && polling) void pollEvents();
    };
    const onOnline = () => {
      if (stopped || typeof EventSource === "undefined") return;
      failedReconnectAttempts = 0;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      clearHandshakeTimer();
      streamPageFailed = true;
      source?.close();
      source = null;
      connect();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("online", onOnline);
    connect();
    return () => {
      stopped = true;
      polling = false;
      streamPageFailed = true;
      streamGeneration += 1;
      source?.close();
      source = null;
      clearHandshakeTimer();
      if (pollTimer !== null) window.clearTimeout(pollTimer);
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      if (cycleTimer !== null) window.clearTimeout(cycleTimer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("online", onOnline);
    };
  }, [drainEventPages, eventsReady, processEvents, rememberEventCursor, resetEventFenceAndFeed]);

  const connectionLabel =
    connectionMode === "live"
      ? "朋友圈实时连接"
      : connectionMode === "polling"
        ? "备用连接"
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
              moment={
                String(moment.author.user_id) === String(userId)
                  ? {
                      ...moment,
                      author: {
                        ...moment.author,
                        avatar_ref: profile.avatar_ref,
                        display_name: profile.display_name,
                      },
                    }
                  : moment
              }
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

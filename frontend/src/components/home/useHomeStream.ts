"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { isApiAbortError } from "@/lib/api";
import { c19SseReconnectDelay } from "@/modules/c19/C19EventStreamRecovery";

import {
  getHomeBootstrap,
  getHomeCard,
  HOME_STREAM_PROXY_PATH,
  type HomeBootstrapRead,
  type HomeCardRead,
} from "./home-api";

export type HomeStreamStatus =
  | "connecting"
  | "live"
  | "reconnecting"
  | "polling"
  | "paused";

/** 连续失败到这个次数就退到轮询兜底；期间仍每 30 秒试着重开流。 */
const POLL_AFTER_FAILURES = 3;
const POLL_INTERVAL_MS = 10_000;
const STREAM_RETRY_WHILE_POLLING_MS = 30_000;
/** 服务端流寿命 55s；在这个窗口内的断开是正常到期，不计入失败。 */
const EXPECTED_LIFETIME_MS = 60_000;

type CardMap = Map<string, HomeCardRead>;

function toMap(cards: HomeCardRead[]): CardMap {
  return new Map(cards.map((card) => [card.card_id, card]));
}

/**
 * 整个主页只开这一条 SSE。浏览器同域并发连接上限 6 条，一卡一流会把页面卡死。
 *
 * 帧协议（`modules/home/stream.py`）：`event: card` 整卡覆盖，`event: card-removed`
 * 权限被收走，`: keep-alive` 空闲。服务端 55s 到期主动关流，客户端 2s 后重连。
 */
export function useHomeStream(bootstrap: HomeBootstrapRead) {
  const [cards, setCards] = useState<CardMap>(() => toMap(bootstrap.cards));
  const [status, setStatus] = useState<HomeStreamStatus>("connecting");
  const [lastAliveAt, setLastAliveAt] = useState<number | null>(null);

  const sourceRef = useRef<EventSource | null>(null);
  const failedAttemptsRef = useRef(0);
  const openedAtRef = useRef<number | null>(null);
  const timersRef = useRef<number[]>([]);
  const disposedRef = useRef(false);

  const clearTimers = useCallback(() => {
    for (const id of timersRef.current) window.clearTimeout(id);
    timersRef.current = [];
  }, []);

  const closeSource = useCallback(() => {
    const source = sourceRef.current;
    sourceRef.current = null;
    if (source) source.close();
  }, []);

  const applyCard = useCallback((card: HomeCardRead) => {
    setCards((current) => {
      const next = new Map(current);
      next.set(card.card_id, card);
      return next;
    });
  }, []);

  const removeCard = useCallback((cardId: string) => {
    setCards((current) => {
      if (!current.has(cardId)) return current;
      const next = new Map(current);
      next.delete(cardId);
      return next;
    });
  }, []);

  const refreshAll = useCallback(async () => {
    try {
      const next = await getHomeBootstrap();
      if (!disposedRef.current) setCards(toMap(next.cards));
    } catch (error) {
      if (!isApiAbortError(error)) {
        /* 轮询兜底失败就保留上一份，下一轮再试。 */
      }
    }
  }, []);

  const connect = useCallback(() => {
    if (disposedRef.current || document.hidden) return;
    closeSource();
    setStatus((current) => (current === "polling" ? "polling" : "connecting"));
    let source: EventSource;
    try {
      source = new EventSource(HOME_STREAM_PROXY_PATH, { withCredentials: true });
    } catch {
      failedAttemptsRef.current += 1;
      scheduleReconnect();
      return;
    }
    sourceRef.current = source;

    source.onopen = () => {
      openedAtRef.current = Date.now();
      failedAttemptsRef.current = 0;
      setStatus("live");
      setLastAliveAt(Date.now());
    };
    source.addEventListener("card", (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent<string>).data) as HomeCardRead;
        if (payload && typeof payload.card_id === "string") {
          applyCard(payload);
          setLastAliveAt(Date.now());
        }
      } catch {
        /* 坏帧丢掉，下一帧整卡覆盖 */
      }
    });
    source.addEventListener("card-removed", (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent<string>).data) as { card_id?: string };
        if (payload?.card_id) removeCard(payload.card_id);
      } catch {
        /* ignore */
      }
    });
    source.onerror = () => {
      closeSource();
      const openedAt = openedAtRef.current;
      const routineExpiry =
        openedAt !== null && Date.now() - openedAt < EXPECTED_LIFETIME_MS + 5_000;
      if (!routineExpiry) failedAttemptsRef.current += 1;
      openedAtRef.current = null;
      scheduleReconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (disposedRef.current) return;
    clearTimers();
    const failures = failedAttemptsRef.current;
    if (failures >= POLL_AFTER_FAILURES) {
      setStatus("polling");
      void refreshAll();
      timersRef.current.push(window.setTimeout(() => void refreshAll(), POLL_INTERVAL_MS));
      timersRef.current.push(window.setTimeout(connect, STREAM_RETRY_WHILE_POLLING_MS));
      return;
    }
    setStatus(failures === 0 ? "connecting" : "reconnecting");
    timersRef.current.push(window.setTimeout(connect, c19SseReconnectDelay(failures)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    disposedRef.current = false;
    connect();

    const onVisibility = () => {
      if (document.hidden) {
        clearTimers();
        closeSource();
        setStatus("paused");
        return;
      }
      failedAttemptsRef.current = 0;
      void refreshAll();
      connect();
    };
    const onOnline = () => {
      failedAttemptsRef.current = 0;
      connect();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", onOnline);
    window.addEventListener("pagehide", closeSource);
    return () => {
      disposedRef.current = true;
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("pagehide", closeSource);
      clearTimers();
      closeSource();
    };
  }, [clearTimers, closeSource, connect, refreshAll]);

  /** 浮窗里做完简单操作后的乐观更新；下一帧服务端整卡覆盖收敛。 */
  const patchCard = useCallback(
    (cardId: string, updater: (card: HomeCardRead) => HomeCardRead) => {
      setCards((current) => {
        const existing = current.get(cardId);
        if (!existing) return current;
        const next = new Map(current);
        next.set(cardId, updater(existing));
        return next;
      });
    },
    [],
  );

  /** 操作失败或拿不准时拉一次真值。 */
  const refetchCard = useCallback(
    async (cardId: string) => {
      try {
        applyCard(await getHomeCard(cardId));
      } catch (error) {
        if (!isApiAbortError(error)) {
          /* 单卡刷新失败：保留当前，流帧会收敛 */
        }
      }
    },
    [applyCard],
  );

  const ordered = useMemo(() => Array.from(cards.values()), [cards]);

  return { cards, ordered, status, lastAliveAt, patchCard, refetchCard };
}

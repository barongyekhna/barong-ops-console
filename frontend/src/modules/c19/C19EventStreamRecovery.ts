export const C19_SSE_RECONNECT_BASE_MS = 2_000;
export const C19_SSE_RECONNECT_MAX_MS = 30_000;

/**
 * Keep routine server revalidation reconnects fast, while backing off during
 * a real outage so a tab cannot continuously consume the stream rate limit.
 */
export function c19SseReconnectDelay(failedAttempts: number) {
  const exponent = Number.isFinite(failedAttempts)
    ? Math.max(0, Math.min(30, Math.floor(failedAttempts)))
    : 0;
  return Math.min(
    C19_SSE_RECONNECT_BASE_MS * 2 ** exponent,
    C19_SSE_RECONNECT_MAX_MS,
  );
}

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  C19_SSE_RECONNECT_BASE_MS,
  C19_SSE_RECONNECT_MAX_MS,
  c19SseReconnectDelay,
} from "../../frontend/src/modules/c19/C19EventStreamRecovery.ts";

const chatSource = readFileSync(
  "frontend/src/modules/c19/C19ChatPanel.tsx",
  "utf8",
);
const momentsSource = readFileSync(
  "frontend/src/modules/c19/C19MomentsPanel.tsx",
  "utf8",
);

test("C19 event streams reconnect quickly after routine revalidation and back off during outages", () => {
  assert.equal(C19_SSE_RECONNECT_BASE_MS, 2_000);
  assert.equal(C19_SSE_RECONNECT_MAX_MS, 30_000);
  assert.deepEqual(
    [0, 1, 2, 3, 4, 5, 20].map(c19SseReconnectDelay),
    [2_000, 4_000, 8_000, 16_000, 30_000, 30_000, 30_000],
  );
  assert.equal(c19SseReconnectDelay(-3), 2_000);
  assert.equal(c19SseReconnectDelay(Number.NaN), 2_000);
});

test("chat and moments always retry failed SSE handshakes while polling remains the fallback", () => {
  for (const source of [chatSource, momentsSource]) {
    assert.match(source, /c19SseReconnectDelay/);
    assert.match(source, /SSE_HANDSHAKE_TIMEOUT_MS = 12_000/);
    assert.match(source, /clearHandshakeTimer/);
    assert.match(source, /const scheduleReconnect = \(\)(?:: void)? =>/);
    assert.match(source, /failedReconnectAttempts = 0/);
    assert.match(source, /pollInFlight/);
    assert.match(source, /window\.addEventListener\("online", onOnline\)/);
    assert.match(source, /startPolling\(\);\s*scheduleReconnect\(\)/);
  }
  assert.doesNotMatch(chatSource, /const reconnectSse = sseOpened/);
  assert.match(
    momentsSource,
    /if \(eventPageInFlight\) \{\s*schedulePoll\(\);\s*return;/,
  );
  assert.match(
    momentsSource,
    /generation === streamGeneration &&\s*!streamPageFailed/,
  );
  assert.match(momentsSource, /source !== nextSource/);
  assert.match(momentsSource, /bootstrapGenerationRef/);
  assert.match(
    momentsSource,
    /drainEventPages\(cursor, isCurrentBootstrap\)/,
  );
});

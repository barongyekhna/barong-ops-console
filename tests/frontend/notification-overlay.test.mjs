import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const bellSource = readFileSync(
  "frontend/src/modules/notifications/NotificationBell.tsx",
  "utf8",
);
const overlaySource = readFileSync(
  "frontend/src/modules/notifications/NotificationOverlay.tsx",
  "utf8",
);
const inboxSource = readFileSync(
  "frontend/src/modules/notifications/NotificationInbox.tsx",
  "utf8",
);

test("notification bell opens an in-place overlay without navigation", () => {
  assert.match(bellSource, /<NotificationOverlay/);
  assert.match(bellSource, /aria-haspopup="dialog"/);
  assert.match(bellSource, /aria-expanded=\{isOpen\}/);
  assert.doesNotMatch(bellSource, /router\.(?:push|replace)/);
  assert.doesNotMatch(bellSource, /sessionStorage/);
});

test("notification overlay preserves the page and implements modal controls", () => {
  assert.match(overlaySource, /createPortal\(/);
  assert.match(overlaySource, /aria-modal="true"/);
  assert.match(overlaySource, /role="dialog"/);
  assert.match(overlaySource, /event\.key === "Escape"/);
  assert.match(overlaySource, /event\.key !== "Tab"/);
  assert.match(overlaySource, /body\.style\.overflow = "hidden"/);
  assert.match(overlaySource, /body\.style\.overflow = previousBodyOverflow/);
  assert.match(overlaySource, /previouslyFocused\.focus/);
});

test("notification inbox closes locally and keeps the bell count synchronized", () => {
  assert.match(inboxSource, /onClose\?: \(\) => void/);
  assert.match(inboxSource, /onUnreadChange\?: \(unread: number\) => void/);
  assert.match(inboxSource, /onUnreadChange\?\.\(result\.unread\)/);
  assert.match(inboxSource, /if \(onClose\) \{[\s\S]*onClose\(\);[\s\S]*return;/);
  assert.match(inboxSource, /variant === "overlay" \? styles\.inboxOverlay/);
});

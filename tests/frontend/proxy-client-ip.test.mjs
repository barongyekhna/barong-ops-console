import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  applyTrustedClientIp,
  normalizeTrustedClientIp,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

test("the restricted proxy forwards only Nginx's single validated client IP", () => {
  assert.equal(normalizeTrustedClientIp("203.0.113.9"), "203.0.113.9");
  assert.equal(normalizeTrustedClientIp("2001:db8::9"), "2001:db8::9");

  for (const value of [
    null,
    "",
    " 203.0.113.9",
    "203.0.113.9, 10.0.0.1",
    "203.0.113.9:443",
    "example.test",
    "203.0.113.9\nX-Forged: yes",
  ]) {
    assert.equal(normalizeTrustedClientIp(value), null);
  }

  const outbound = new Headers({ "X-Forwarded-For": "198.51.100.200" });
  const inbound = new Headers({
    "X-Forwarded-For": "198.51.100.123",
    "X-Real-IP": "203.0.113.9",
  });
  applyTrustedClientIp(outbound, inbound);
  assert.equal(outbound.get("x-forwarded-for"), "203.0.113.9");

  inbound.set("X-Real-IP", "attacker.invalid");
  applyTrustedClientIp(outbound, inbound);
  assert.equal(outbound.has("x-forwarded-for"), false);
});

test("production Nginx overwrites X-Real-IP on both C19 SSE entries", () => {
  const nginx = readFileSync(
    "deploy/nginx/ops.barongyekhna.com.conf.template",
    "utf8",
  );
  for (const location of [
    "/api/backend/c19/events",
    "/api/backend/c19/moments/events",
  ]) {
    const start = nginx.indexOf(`location = ${location}`);
    assert.ok(start >= 0, `${location} must have an exact Nginx location`);
    const block = nginx.slice(start, nginx.indexOf("    }", start) + 5);
    assert.match(block, /proxy_set_header X-Real-IP \$remote_addr;/);
  }
});

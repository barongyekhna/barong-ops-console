import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  getBackendApiPath,
  isAllowedBackendProxyPath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

test("auth proxy exposes only public session endpoints with exact methods", () => {
  assert.equal(getBackendApiPath("GET", ["auth", "me"]), "/api/public/auth/me");
  assert.equal(
    getBackendApiPath("POST", ["auth", "login"]),
    "/api/public/auth/login",
  );
  assert.equal(
    getBackendApiPath("POST", ["auth", "logout"]),
    "/api/public/auth/logout",
  );

  assert.equal(isAllowedBackendProxyPath("POST", ["auth", "me"]), false);
  assert.equal(isAllowedBackendProxyPath("GET", ["auth", "login"]), false);
  assert.equal(isAllowedBackendProxyPath("GET", ["auth", "logout"]), false);
  assert.equal(isAllowedBackendProxyPath("POST", ["auth", "register"]), false);
});

test("auth success and root entry land on dashboard route without blanking initial HTML", () => {
  const rootPageSource = readFileSync("frontend/src/app/page.tsx", "utf8");
  const loginFormSource = readFileSync(
    "frontend/src/components/login-form.tsx",
    "utf8",
  );
  const publicOnlySource = readFileSync(
    "frontend/src/components/public-only.tsx",
    "utf8",
  );

  assert.match(rootPageSource, /<LoginScreen \/>/);
  assert.match(rootPageSource, /<PublicOnly>/);
  assert.match(loginFormSource, /router\.replace\("\/dashboard"\)/);
  assert.match(publicOnlySource, /router\.replace\("\/dashboard"\)/);
  assert.doesNotMatch(rootPageSource, /\/users/);
  assert.doesNotMatch(loginFormSource, /\/users/);
  assert.doesNotMatch(publicOnlySource, /\/users/);
});

test("auth identity does not carry legacy RBAC permission state", () => {
  const authSource = readFileSync("frontend/src/lib/auth.ts", "utf8");
  const providerSource = readFileSync(
    "frontend/src/components/auth-provider.tsx",
    "utf8",
  );

  assert.match(authSource, /permissions\?: unknown/);
  assert.match(authSource, /const \{ permissions: _permissions, \.\.\.identity \} = user/);
  assert.doesNotMatch(providerSource, /permissions\s*:/);
  assert.match(providerSource, /status: AuthStatus/);
  assert.match(providerSource, /user: AuthenticatedUser \| null/);
});

test("auth guards render without full-page session loading gates", () => {
  const authGuardSource = readFileSync(
    "frontend/src/components/auth-guard.tsx",
    "utf8",
  );
  const publicOnlySource = readFileSync(
    "frontend/src/components/public-only.tsx",
    "utf8",
  );

  assert.doesNotMatch(authGuardSource, /AUTH_LOADING_TIMEOUT_MS/);
  assert.doesNotMatch(publicOnlySource, /AUTH_LOADING_TIMEOUT_MS/);
  assert.doesNotMatch(authGuardSource, /LoaderCircle/);
  assert.doesNotMatch(publicOnlySource, /LoaderCircle/);
  assert.doesNotMatch(publicOnlySource, /return null/);
  assert.match(authGuardSource, /router\.replace\("\/login"\)/);
  assert.match(publicOnlySource, /router\.replace\("\/dashboard"\)/);
});

test("auth initialization failures do not leave session status checking forever", () => {
  const providerSource = readFileSync(
    "frontend/src/components/auth-provider.tsx",
    "utf8",
  );

  assert.match(providerSource, /BACKGROUND_SESSION_CHECK_TIMEOUT_MS = 1_500/);
  assert.match(providerSource, /catch \(error\)[\s\S]*clearSession\(\);/);
});

test("login route renders independently from public-only auth readiness", () => {
  const loginPageSource = readFileSync(
    "frontend/src/app/login/page.tsx",
    "utf8",
  );

  assert.match(loginPageSource, /return <LoginScreen \/>/);
  assert.doesNotMatch(loginPageSource, /PublicOnly/);
});

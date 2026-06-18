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
  assert.equal(
    getBackendApiPath("POST", ["auth", "change-password"]),
    "/api/public/auth/change-password",
  );

  assert.equal(isAllowedBackendProxyPath("POST", ["auth", "me"]), false);
  assert.equal(isAllowedBackendProxyPath("GET", ["auth", "login"]), false);
  assert.equal(isAllowedBackendProxyPath("GET", ["auth", "logout"]), false);
  assert.equal(isAllowedBackendProxyPath("POST", ["auth", "register"]), false);
});

test("root entry routes authenticated users home and unauthenticated users to login", () => {
  const rootPageSource = readFileSync("frontend/src/app/page.tsx", "utf8");
  const loginFormSource = readFileSync(
    "frontend/src/components/login-form.tsx",
    "utf8",
  );
  const publicOnlySource = readFileSync(
    "frontend/src/components/public-only.tsx",
    "utf8",
  );

  assert.match(rootPageSource, /"use client"/);
  assert.match(rootPageSource, /useAuth/);
  assert.match(rootPageSource, /status === "authenticated"/);
  assert.match(rootPageSource, /\/force-password-reset/);
  assert.match(rootPageSource, /\/dashboard/);
  assert.match(rootPageSource, /status === "unauthenticated"/);
  assert.match(rootPageSource, /router\.replace\("\/login"\)/);
  assert.doesNotMatch(rootPageSource, /LoginScreen/);
  assert.doesNotMatch(rootPageSource, /PublicOnly/);
  assert.match(loginFormSource, /\/force-password-reset/);
  assert.match(loginFormSource, /\/dashboard/);
  assert.doesNotMatch(publicOnlySource, /router\.replace\("\/dashboard"\)/);
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
  assert.doesNotMatch(authGuardSource, /LoginScreen/);
  assert.match(authGuardSource, /redirect\("\/login"\)/);
  assert.match(authGuardSource, /redirect\("\/force-password-reset"\)/);
  assert.match(authGuardSource, /status !== "authenticated"[\s\S]*return null/);
  assert.doesNotMatch(publicOnlySource, /\/dashboard/);
});

test("auth initialization and route changes reset transient auth state", () => {
  const providerSource = readFileSync(
    "frontend/src/components/auth-provider.tsx",
    "utf8",
  );

  assert.match(providerSource, /BACKGROUND_SESSION_CHECK_TIMEOUT_MS = 1_500/);
  assert.match(providerSource, /resetAuthState/);
  assert.match(providerSource, /LOGIN_PATHNAME = "\/login"/);
  assert.match(providerSource, /pathname === LOGIN_PATHNAME[\s\S]*resetAuthState\(\)/);
  assert.match(providerSource, /abortSessionCheck/);
  assert.match(providerSource, /sessionCheckRequest\(\{[\s\S]*signal: controller\.signal/);
  assert.match(providerSource, /catch \(error\)[\s\S]*clearSession\(\);/);
});

test("dashboard page has explicit unauthenticated access control", () => {
  const dashboardPageSource = readFileSync(
    "frontend/src/app/(console)/dashboard/page.tsx",
    "utf8",
  );
  const dashboardAccessControlSource = readFileSync(
    "frontend/src/components/dashboard-access-control.tsx",
    "utf8",
  );

  assert.match(dashboardPageSource, /<DashboardAccessControl>/);
  assert.match(dashboardAccessControlSource, /redirect\("\/login"\)/);
  assert.match(
    dashboardAccessControlSource,
    /status !== "authenticated"[\s\S]*return null/,
  );
});

test("login route renders independently from public-only auth readiness", () => {
  const loginPageSource = readFileSync(
    "frontend/src/app/login/page.tsx",
    "utf8",
  );

  assert.match(loginPageSource, /return <LoginScreen \/>/);
  assert.doesNotMatch(loginPageSource, /PublicOnly/);
});

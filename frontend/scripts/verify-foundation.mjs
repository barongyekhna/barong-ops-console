import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

const frontendRoot = resolve(import.meta.dirname, "..");
const repoRoot = resolve(frontendRoot, "..");
const appRoot = join(frontendRoot, "src", "app");
const rootPage = join(appRoot, "page.tsx");
const requiredRoutes = [
  "login",
  "(console)/dashboard",
  "(console)/foundation-demo",
  "(console)/n8n-test",
  "(console)/products",
  "(console)/modules",
  "(console)/agents",
  "(console)/workflows",
  "(console)/jobs",
  "(console)/artifacts",
  "(console)/reviews",
  "(console)/errors",
  "(console)/memory-events",
  "(console)/users",
  "(console)/settings",
];

if (!existsSync(rootPage)) {
  throw new Error("Missing required root route file: page.tsx");
}

for (const route of requiredRoutes) {
  const page = join(appRoot, route, "page.tsx");
  if (!existsSync(page)) {
    throw new Error(`Missing required route file: ${route}/page.tsx`);
  }
}

for (const requiredFile of [
  join(appRoot, "(console)", "layout.tsx"),
  join(frontendRoot, "src", "components", "auth-guard.tsx"),
  join(frontendRoot, "src", "lib", "module-registry.ts"),
  join(frontendRoot, "src", "lib", "module-registry-api.ts"),
  join(frontendRoot, "src", "lib", "module-adapter.ts"),
  join(frontendRoot, "src", "lib", "module-adapter-api.ts"),
  join(frontendRoot, "src", "lib", "execution-provider.ts"),
  join(frontendRoot, "src", "lib", "execution-provider-api.ts"),
  join(frontendRoot, "src", "components", "module-access-provider.tsx"),
  join(frontendRoot, "src", "components", "adapter-access-provider.tsx"),
  join(frontendRoot, "src", "components", "module-adapter-shell.tsx"),
  join(frontendRoot, "src", "components", "execution-provider-status-shell.tsx"),
  join(repoRoot, "tests", "frontend", "module-isolation.test.mjs"),
  join(repoRoot, "tests", "frontend", "module-adapter.test.mjs"),
  join(repoRoot, "tests", "frontend", "execution-provider.test.mjs"),
]) {
  if (!existsSync(requiredFile)) {
    throw new Error(`Missing protected console file: ${requiredFile}`);
  }
}

function walk(directory) {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const sourceFiles = walk(join(frontendRoot, "src")).filter((path) =>
  /\.(?:ts|tsx|js|jsx)$/.test(path),
);
const source = sourceFiles.map((path) => readFileSync(path, "utf8")).join("\n");
const registrationEndpoint = "/auth/" + "register";
const requiredApiPaths = [
  "/modules",
  "/agents",
  "/workflows",
  "/jobs",
  "/artifacts",
  "/reviews",
  "/errors",
  "/memory-events",
];

if (source.includes(registrationEndpoint)) {
  throw new Error("A public registration API reference was found.");
}

if (sourceFiles.some((path) => path.split("/").includes("register"))) {
  throw new Error("A public registration route was found.");
}

if (/console\s*\.\s*(?:log|debug|info)\s*\(/.test(source)) {
  throw new Error("Console output is not allowed in authentication code.");
}

if (/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/.test(source)) {
  throw new Error("A private key block was found.");
}

for (const apiPath of requiredApiPaths) {
  if (!source.includes(`endpoint="${apiPath}"`)) {
    throw new Error(`Missing F10 API page connection: ${apiPath}`);
  }
}

for (const demoPath of ["/foundation-demo/run", "/foundation-demo/latest"]) {
  if (!source.includes(demoPath)) {
    throw new Error(`Missing F11 API connection: ${demoPath}`);
  }
}

for (const testPath of ["/n8n-test/run", "/n8n-test/latest"]) {
  if (!source.includes(testPath)) {
    throw new Error(`Missing F12 API connection: ${testPath}`);
  }
}

for (const usersPath of [
  "/users",
  "/users/roles",
  "/disable",
  "/enable",
  "/reset-password",
]) {
  if (!source.includes(usersPath)) {
    throw new Error(`Missing C03C user management API connection: ${usersPath}`);
  }
}

if (
  !source.includes("User Management") ||
  !source.includes("not a public registration flow") ||
  !source.includes("Current assignable roles") ||
  !source.includes("Reserved roles, not assignable in C04") ||
  !source.includes("Full RBAC is planned for C05.")
) {
  throw new Error("The C03C user management page is incomplete.");
}

const backendProxyRoute = join(
  appRoot,
  "api",
  "backend",
  "[...path]",
  "route.ts",
);
const backendProxySource = readFileSync(backendProxyRoute, "utf8");
const navigationSource = readFileSync(
  join(frontendRoot, "src", "lib", "navigation.ts"),
  "utf8",
);
const moduleRegistrySource = readFileSync(
  join(frontendRoot, "src", "lib", "module-registry.ts"),
  "utf8",
);
const moduleAdapterSource = readFileSync(
  join(frontendRoot, "src", "lib", "module-adapter.ts"),
  "utf8",
);
const moduleAdapterApiSource = readFileSync(
  join(frontendRoot, "src", "lib", "module-adapter-api.ts"),
  "utf8",
);
const executionProviderSource = readFileSync(
  join(frontendRoot, "src", "lib", "execution-provider.ts"),
  "utf8",
);
const executionProviderApiSource = readFileSync(
  join(frontendRoot, "src", "lib", "execution-provider-api.ts"),
  "utf8",
);
const adapterAccessProviderSource = readFileSync(
  join(frontendRoot, "src", "components", "adapter-access-provider.tsx"),
  "utf8",
);
const moduleAdapterShellSource = readFileSync(
  join(frontendRoot, "src", "components", "module-adapter-shell.tsx"),
  "utf8",
);
const executionProviderStatusShellSource = readFileSync(
  join(frontendRoot, "src", "components", "execution-provider-status-shell.tsx"),
  "utf8",
);

if (!backendProxySource.includes("export function PATCH")) {
  throw new Error("The backend API proxy must support PATCH for user updates.");
}

if (!backendProxySource.includes('path[1] === "roles"')) {
  throw new Error("The backend API proxy must allow GET /users/roles.");
}

for (const permissionsPath of ["permissions/me", "permissions/registry"]) {
  if (!backendProxySource.includes(permissionsPath)) {
    throw new Error(
      `The backend API proxy must allow GET /${permissionsPath}.`,
    );
  }
}

for (const modulesPath of ["modules/registry", "modules/me"]) {
  if (!backendProxySource.includes(modulesPath)) {
    throw new Error(
      `The backend API proxy must allow GET /${modulesPath}.`,
    );
  }
}

for (const adapterPath of [
  "module-adapters/registry",
  "module-adapters/me",
]) {
  if (!backendProxySource.includes(adapterPath)) {
    throw new Error(
      `The backend API proxy must allow GET /${adapterPath}.`,
    );
  }
}

for (const executionProviderPath of [
  "execution-providers/registry",
  "execution-providers/me",
]) {
  if (!backendProxySource.includes(executionProviderPath)) {
    throw new Error(
      `The backend API proxy must allow GET /${executionProviderPath}.`,
    );
  }
}

if (!backendProxySource.includes("ALLOWED_MODULE_REGISTRY_PATHS")) {
  throw new Error(
    "The backend API proxy must keep C07 module registry paths explicitly allowlisted.",
  );
}

if (!backendProxySource.includes("ALLOWED_MODULE_ADAPTER_REGISTRY_PATHS")) {
  throw new Error(
    "The backend API proxy must keep C08 module adapter registry paths explicitly allowlisted.",
  );
}

if (!backendProxySource.includes("ALLOWED_EXECUTION_PROVIDER_REGISTRY_PATHS")) {
  throw new Error(
    "The backend API proxy must keep C09 execution provider paths explicitly allowlisted.",
  );
}

const moduleRegistryAllowlistMatch = backendProxySource.match(
  /const ALLOWED_MODULE_REGISTRY_PATHS = new Set\(\[([\s\S]*?)\]\);/,
);
if (!moduleRegistryAllowlistMatch) {
  throw new Error("The C07 module registry proxy allowlist was not found.");
}
const moduleRegistryAllowlist = new Set(
  Array.from(moduleRegistryAllowlistMatch[1].matchAll(/["']([^"']+)["']/g)).map(
    (match) => match[1],
  ),
);
if (
  moduleRegistryAllowlist.size !== 2 ||
  !moduleRegistryAllowlist.has("modules/registry") ||
  !moduleRegistryAllowlist.has("modules/me")
) {
  throw new Error(
    "The C07 module registry proxy allowlist must contain only exact GET /modules/registry and GET /modules/me.",
  );
}
if (
  /modules\/\*/.test(backendProxySource) ||
  /path\[0\]\s*===\s*["']modules["'][\s\S]{0,120}path\.length\s*[!<>]=/.test(
    backendProxySource,
  ) ||
  /requestedPath\.startsWith\(["']modules\//.test(backendProxySource)
) {
  throw new Error("The backend API proxy must not allow a broad /modules/* wildcard.");
}
if (!backendProxySource.includes('method === "GET" && ALLOWED_MODULE_REGISTRY_PATHS.has(requestedPath)')) {
  throw new Error("The C07 module registry proxy paths must be GET-only.");
}

const moduleAdapterAllowlistMatch = backendProxySource.match(
  /const ALLOWED_MODULE_ADAPTER_REGISTRY_PATHS = new Set\(\[([\s\S]*?)\]\);/,
);
if (!moduleAdapterAllowlistMatch) {
  throw new Error("The C08 module adapter proxy allowlist was not found.");
}
const moduleAdapterAllowlist = new Set(
  Array.from(
    moduleAdapterAllowlistMatch[1].matchAll(/["']([^"']+)["']/g),
  ).map((match) => match[1]),
);
if (
  moduleAdapterAllowlist.size !== 2 ||
  !moduleAdapterAllowlist.has("module-adapters/registry") ||
  !moduleAdapterAllowlist.has("module-adapters/me")
) {
  throw new Error(
    "The C08 module adapter proxy allowlist must contain only exact GET /module-adapters/registry and GET /module-adapters/me.",
  );
}
if (
  /module-adapters\/\*/.test(backendProxySource) ||
  /path\[0\]\s*===\s*["']module-adapters["'][\s\S]{0,120}path\.length\s*[!<>]=/.test(
    backendProxySource,
  ) ||
  /requestedPath\.startsWith\(["']module-adapters\//.test(backendProxySource)
) {
  throw new Error(
    "The backend API proxy must not allow a broad /module-adapters/* wildcard.",
  );
}
if (
  !backendProxySource.includes(
    'method === "GET" &&\n      ALLOWED_MODULE_ADAPTER_REGISTRY_PATHS.has(requestedPath)',
  ) &&
  !backendProxySource.includes(
    'method === "GET" && ALLOWED_MODULE_ADAPTER_REGISTRY_PATHS.has(requestedPath)',
  )
) {
  throw new Error("The C08 module adapter proxy paths must be GET-only.");
}

const executionProviderAllowlistMatch = backendProxySource.match(
  /const ALLOWED_EXECUTION_PROVIDER_REGISTRY_PATHS = new Set\(\[([\s\S]*?)\]\);/,
);
if (!executionProviderAllowlistMatch) {
  throw new Error("The C09 execution provider proxy allowlist was not found.");
}
const executionProviderAllowlist = new Set(
  Array.from(
    executionProviderAllowlistMatch[1].matchAll(/["']([^"']+)["']/g),
  ).map((match) => match[1]),
);
if (
  executionProviderAllowlist.size !== 2 ||
  !executionProviderAllowlist.has("execution-providers/registry") ||
  !executionProviderAllowlist.has("execution-providers/me")
) {
  throw new Error(
    "The C09 execution provider proxy allowlist must contain only exact GET registry and me paths.",
  );
}
if (
  /execution-providers\/\*/.test(backendProxySource) ||
  /path\[0\]\s*===\s*["']execution-providers["'][\s\S]{0,120}path\.length\s*[!<>]=/.test(
    backendProxySource,
  ) ||
  /requestedPath\.startsWith\(["']execution-providers\//.test(
    backendProxySource,
  ) ||
  /requestedPath\.startsWith\(["']executions?\//.test(backendProxySource)
) {
  throw new Error(
    "The backend API proxy must not allow broad execution provider paths.",
  );
}
if (
  !backendProxySource.includes(
    'method === "GET" &&\n      ALLOWED_EXECUTION_PROVIDER_REGISTRY_PATHS.has(requestedPath)',
  ) &&
  !backendProxySource.includes(
    'method === "GET" && ALLOWED_EXECUTION_PROVIDER_REGISTRY_PATHS.has(requestedPath)',
  )
) {
  throw new Error("The C09 execution provider proxy paths must be GET-only.");
}
for (const deniedExecutionPath of [
  ["execution-providers", "not-allowed"],
  ["executions"],
  ["executions", "run"],
  ["execution", "submit"],
]) {
  if (
    backendProxySource.includes(`"${deniedExecutionPath.join("/")}"`) ||
    backendProxySource.includes(`'${deniedExecutionPath.join("/")}'`)
  ) {
    throw new Error("A denied execution path was added to the proxy allowlist.");
  }
}

for (const assignmentProxyCheck of [
  'path[1] !== "users"',
  'path[3] === "assignments"',
  'method === "GET" || method === "POST"',
  'method === "PATCH" || method === "DELETE"',
  "isUuidPathSegment",
  "export function DELETE",
]) {
  if (!backendProxySource.includes(assignmentProxyCheck)) {
    throw new Error(
      "The backend API proxy must precisely allow C06B permission assignment APIs.",
    );
  }
}

if (
  !backendProxySource.includes('requestedPath === "health"') ||
  !backendProxySource.includes('new URL(`/${requestedPath}`, getApiBaseUrl())')
) {
  throw new Error("The backend API proxy health path is not safely routed.");
}

if (/headers\.set\(["']Host["']/i.test(backendProxySource)) {
  throw new Error("The backend API proxy must not forward the browser Host header.");
}

if (!navigationSource.includes("module_key: string")) {
  throw new Error("Navigation items must require a module_key field.");
}

for (const navigationModuleKey of [
  "core.dashboard",
  "experimental.foundation_demo",
  "integration.n8n_test_bridge",
  "business.products",
  "admin.modules",
  "admin.agents",
  "admin.workflows",
  "business.jobs",
  "business.artifacts",
  "business.reviews",
  "system.errors",
  "system.memory_events",
  "admin.users",
  "admin.permissions",
  "admin.settings",
]) {
  if (!navigationSource.includes(`module_key: "${navigationModuleKey}"`)) {
    throw new Error(`Missing C07 navigation module_key: ${navigationModuleKey}`);
  }
}

if (
  !/label:\s*"User Management"[\s\S]{0,260}module_key:\s*"admin\.users"/.test(
    navigationSource,
  )
) {
  throw new Error("User Management must map to module_key admin.users.");
}
if (
  !/label:\s*"Permission Management"[\s\S]{0,260}module_key:\s*"admin\.permissions"/.test(
    navigationSource,
  )
) {
  throw new Error(
    "Permission Management must map to module_key admin.permissions.",
  );
}
if (
  !moduleRegistrySource.includes("assertNavigationModulesRegistered") ||
  !moduleRegistrySource.includes("moduleAccessUnknown") ||
  !moduleRegistrySource.includes("hide_when_denied") ||
  !moduleRegistrySource.includes("show_locked")
) {
  throw new Error("The C07C module registry helper is missing isolation checks.");
}

if (
  !source.includes("AdapterAccessProvider") ||
  !source.includes("useAdapterAccess") ||
  !source.includes("module-adapters/registry") ||
  !source.includes("module-adapters/me") ||
  !source.includes("Execution Provider not connected") ||
  !source.includes("waiting for C09 Execution Provider") ||
  !source.includes("waiting for C12 Approval Gate")
) {
  throw new Error("The C08C adapter frontend shell markers are incomplete.");
}

if (
  !source.includes("ExecutionProviderStatusShell") ||
  !source.includes("getExecutionProviderRegistry") ||
  !source.includes("getMyExecutionProviders") ||
  !source.includes("execution-providers/registry") ||
  !source.includes("execution-providers/me") ||
  !source.includes("waiting for C14 Secret Rules") ||
  !source.includes("waiting for C18 Scope Adapter") ||
  !source.includes("provider_pending")
) {
  throw new Error("The C09C execution provider frontend shell markers are incomplete.");
}

if (
  !moduleAdapterSource.includes("export function isAdapterExecutable") ||
  !/export function isAdapterExecutable[\s\S]{0,160}return false;/.test(
    moduleAdapterSource,
  ) ||
  !moduleAdapterSource.includes("available_actions: []") ||
  !moduleAdapterSource.includes("unavailable_actions: uniqueStrings")
) {
  throw new Error(
    "The C08D adapter helper must force no-execute action state.",
  );
}

if (
  !executionProviderSource.includes("export type ExecutionProviderContract") ||
  !executionProviderSource.includes("export type ExecutionProviderAccessState") ||
  !executionProviderSource.includes("safe_status_message") ||
  !executionProviderSource.includes("no_execute_reason") ||
  !executionProviderSource.includes("can_request_execution: false") ||
  !executionProviderSource.includes("executable: false") ||
  !/export function isExecutionProviderExecutable[\s\S]{0,180}return false;/.test(
    executionProviderSource,
  ) ||
  !/export function canRequestExecution[\s\S]{0,180}return false;/.test(
    executionProviderSource,
  )
) {
  throw new Error(
    "The C09C execution provider model must keep safe no-execute state.",
  );
}

if (
  !adapterAccessProviderSource.includes("canExposeAdapterMetadata") ||
  !adapterAccessProviderSource.includes("adapterAccessUnknown") ||
  !adapterAccessProviderSource.includes("isOwnerFullAccess")
) {
  throw new Error(
    "The C08D adapter access provider must keep safe metadata fallback checks.",
  );
}

if (
  !executionProviderStatusShellSource.includes('<button disabled type="button">') ||
  !moduleAdapterShellSource.includes("ExecutionProviderStatusShell") ||
  /apiRequest|fetch\(|method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/.test(
    moduleAdapterShellSource,
  )
) {
  throw new Error(
    "The C08D adapter shell must display disabled action contracts only.",
  );
}

if (
  /method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/.test(
    moduleAdapterApiSource,
  ) ||
  /\/module-adapters\/[^"']*(?:actions?|execute|execution|run)/i.test(
    moduleAdapterApiSource,
  )
) {
  throw new Error(
    "The C08D adapter API client must not create action execution calls.",
  );
}

if (
  /method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/.test(
    executionProviderApiSource,
  ) ||
  /["']\/execution-providers\/[^"']*(?:actions?|execute|execution|run|submit|cancel|retry)/i.test(
    executionProviderApiSource,
  ) ||
  /["']\/executions?\/[^"']*/i.test(executionProviderApiSource)
) {
  throw new Error(
    "The C09C execution provider API client must remain read-only.",
  );
}

const adapterRuntimeSource = [
  moduleAdapterSource,
  moduleAdapterApiSource,
  executionProviderSource,
  executionProviderApiSource,
  adapterAccessProviderSource,
  moduleAdapterShellSource,
  executionProviderStatusShellSource,
].join("\n");

if (
  /live_connection_allowed\s*:\s*true/i.test(adapterRuntimeSource) ||
  /live_provider_connected\s*:\s*true/i.test(adapterRuntimeSource) ||
  /live_check_allowed\s*:\s*true/i.test(adapterRuntimeSource) ||
  /provider_status\s*:\s*["'](?:connected|live_connected)["']/i.test(
    adapterRuntimeSource,
  ) ||
  /["']\/module-adapters\/[^"']*(?:actions?|execute|execution|run)/i.test(
    adapterRuntimeSource,
  ) ||
  /["']\/execution-providers\/[^"']*(?:actions?|execute|execution|run|submit|cancel|retry)/i.test(
    adapterRuntimeSource,
  ) ||
  /["']\/executions?\/[^"']*/i.test(
    adapterRuntimeSource,
  )
) {
  throw new Error(
    "The C08D adapter frontend must not expose live connected providers or executable action routes.",
  );
}

if (
  /Authorization|Bearer|password|credential=|api[_ -]?key|provider_url|https?:\/\/|webhook_url|token=/i.test(
    executionProviderStatusShellSource,
  )
) {
  throw new Error(
    "The C09C execution provider status shell must not render sensitive runtime values.",
  );
}

if (
  !source.includes("Run Foundation Demo") ||
  !source.includes("without triggering real n8n") ||
  !source.includes("P-series tasks")
) {
  throw new Error("The Foundation Demo safety panel is incomplete.");
}

if (
  !source.includes("Run n8n Test") ||
  !source.includes(
    "Test bridge only. Does not run real n8n production workflows.",
  ) ||
  !source.includes("triggers no downstream business work")
) {
  throw new Error("The n8n Test Bridge safety panel is incomplete.");
}

if (
  /module_key:\s*["'](?:k01|k_series|p0[1-8]\b|p_series|product_knowledge)/i.test(
    navigationSource,
  ) ||
  /label:\s*["'][^"']*(?:K01|P0[1-8]|WooCommerce|MinIO|Filebrowser)/i.test(
    navigationSource,
  )
) {
  throw new Error("K01 or P-series menus must not be enabled in navigation.");
}

for (const liveActionPattern of [
  /["']\/(?:woocommerce|minio|filebrowser)\/(?:run|sync|upload|download|callback|webhook|publish|connect)["']/i,
  /["']\/n8n\/(?:run|sync|callback|webhook|publish|connect)["']/i,
  /["']\/n8n-test\/callback["']/i,
  /real\s+(?:n8n|woocommerce|minio|filebrowser)\s+(?:connect|sync|upload|publish|webhook)/i,
]) {
  if (liveActionPattern.test(source)) {
    throw new Error(
      "A live n8n/WooCommerce/MinIO/Filebrowser action marker was found.",
    );
  }
}

const hasProhibitedExternalIntegration = sourceFiles.some((path) => {
  const fileSource = readFileSync(path, "utf8");
  return (
    /https?:\/\/[^"']*(?:n8n|woocommerce|filebrowser|minio)/i.test(fileSource) ||
    /https?:\/\/[^"']+\/(?:webhook|hook)/i.test(fileSource) ||
    /from\s+["'](?!(?:@\/|\.{1,2}\/))[^"']*(?:woocommerce|minio|filebrowser|n8n)[^"']*["']/i.test(
      fileSource,
    )
  );
});

if (hasProhibitedExternalIntegration) {
  throw new Error("A prohibited external integration reference was found.");
}

process.stdout.write("Frontend foundation checks passed.\n");

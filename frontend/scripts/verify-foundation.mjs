import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

const frontendRoot = resolve(import.meta.dirname, "..");
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

const backendProxyRoute = join(
  appRoot,
  "api",
  "backend",
  "[...path]",
  "route.ts",
);
const backendProxySource = readFileSync(backendProxyRoute, "utf8");

if (
  !backendProxySource.includes('requestedPath === "health"') ||
  !backendProxySource.includes('new URL(`/${requestedPath}`, getApiBaseUrl())')
) {
  throw new Error("The backend API proxy health path is not safely routed.");
}

if (/headers\.set\(["']Host["']/i.test(backendProxySource)) {
  throw new Error("The backend API proxy must not forward the browser Host header.");
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

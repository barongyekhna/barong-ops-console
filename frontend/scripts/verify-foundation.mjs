import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

const frontendRoot = resolve(import.meta.dirname, "..");
const appRoot = join(frontendRoot, "src", "app");
const requiredRoutes = [
  "login",
  "(console)/dashboard",
  "(console)/foundation-demo",
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

for (const route of requiredRoutes) {
  const page = join(appRoot, route, "page.tsx");
  if (!existsSync(page)) {
    throw new Error(`Missing required route file: ${route}/page.tsx`);
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

if (
  !source.includes("Run Foundation Demo") ||
  !source.includes("without triggering real n8n") ||
  !source.includes("P-series tasks")
) {
  throw new Error("The Foundation Demo safety panel is incomplete.");
}

if (
  /https?:\/\/[^"']*(?:n8n|woocommerce|filebrowser|minio)/i.test(source) ||
  /https?:\/\/[^"']+\/(?:webhook|hook)/i.test(source) ||
  /from\s+["'][^"']*(?:woocommerce|minio|filebrowser|n8n)[^"']*["']/i.test(
    source,
  )
) {
  throw new Error("A prohibited external integration reference was found.");
}

process.stdout.write("Frontend foundation checks passed.\n");

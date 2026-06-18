import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

const frontendRoot = resolve(import.meta.dirname, "..");
const nextRoot = join(frontendRoot, ".next");
const standaloneRoot = join(nextRoot, "standalone");

function copyTree(source, target) {
  if (!existsSync(source)) {
    return;
  }

  rmSync(target, { force: true, recursive: true });
  mkdirSync(dirname(target), { recursive: true });
  cpSync(source, target, { recursive: true });
}

if (!existsSync(standaloneRoot)) {
  throw new Error("Missing .next/standalone after Next.js build.");
}

copyTree(join(nextRoot, "static"), join(standaloneRoot, ".next", "static"));
copyTree(join(frontendRoot, "public"), join(standaloneRoot, "public"));

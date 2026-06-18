import { rmSync } from "node:fs";
import { join, resolve } from "node:path";

const frontendRoot = resolve(import.meta.dirname, "..");

rmSync(join(frontendRoot, ".next", "dev", "types"), {
  force: true,
  recursive: true,
});

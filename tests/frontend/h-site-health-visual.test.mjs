import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("H series reuses the existing fire-phoenix cockpit shell", () => {
  const layoutSource = readFileSync(
    "frontend/src/app/(console)/h-site-health/layout.tsx",
    "utf8",
  );

  assert.match(layoutSource, /className="ra-command"/);
  assert.match(layoutSource, /className="ra-command-space"/);
  assert.match(layoutSource, /className="ra-command-nebula"/);
  assert.match(layoutSource, /className="ra-command-phoenix"/);
  assert.match(
    layoutSource,
    /className="ra-command-content">\{children\}<\/div>/,
  );
  assert.doesNotMatch(layoutSource, /import\s+["'][^"']+\.css["']/);
  assert.doesNotMatch(layoutSource, /style=\{/);
});

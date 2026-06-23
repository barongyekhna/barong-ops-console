import test from "node:test";
import assert from "node:assert/strict";

import {
  optimisticModuleControlState,
  replaceModuleControlCenterItem,
  updateModuleControlCenterItem,
} from "../../frontend/src/lib/module-control-state.ts";

function moduleState(raw = {}) {
  return {
    category: "admin",
    display_name: raw.module_id ?? "admin.modules",
    enabled: true,
    last_error_at: null,
    module_id: "admin.modules",
    org_id: "org-a",
    runtime_error_code: null,
    runtime_error_message: null,
    runtime_status: "active",
    updated_at: "2026-01-01T00:00:00Z",
    ...raw,
  };
}

function center(modules) {
  return {
    auto_registered_count: modules.length,
    module_count: modules.length,
    organization_count: 1,
    organizations: [
      {
        modules,
        org_id: "org-a",
        org_name: "Org A",
      },
    ],
  };
}

test("module control optimistic state flips on immediately", () => {
  const disabledModule = moduleState({
    enabled: false,
    last_error_at: "2026-01-01T00:00:00Z",
    runtime_error_code: "MODULE_DISABLED",
    runtime_error_message: "Disabled by owner",
    runtime_status: "disabled",
  });

  assert.deepEqual(
    optimisticModuleControlState(disabledModule, true),
    {
      ...disabledModule,
      enabled: true,
      last_error_at: null,
      runtime_error_code: null,
      runtime_error_message: null,
      runtime_status: "active",
    },
  );
});

test("module control optimistic state flips off immediately", () => {
  const activeModule = moduleState();

  assert.deepEqual(
    optimisticModuleControlState(activeModule, false),
    {
      ...activeModule,
      enabled: false,
      last_error_at: null,
      runtime_error_code: null,
      runtime_error_message: null,
      runtime_status: "disabled",
    },
  );
});

test("module control response calibration only replaces the targeted module", () => {
  const first = moduleState({ module_id: "admin.modules" });
  const second = moduleState({ module_id: "admin.users" });
  const responseItem = moduleState({
    display_name: "Modules",
    enabled: false,
    module_id: "admin.modules",
    runtime_status: "disabled",
    updated_at: "2026-01-02T00:00:00Z",
  });

  const updated = replaceModuleControlCenterItem(
    center([first, second]),
    responseItem,
  );

  assert.equal(updated.organizations[0].modules[0], responseItem);
  assert.equal(updated.organizations[0].modules[1], second);
});

test("module control item rollback does not clobber another pending module", () => {
  const originalFirst = moduleState({ module_id: "admin.modules" });
  const originalSecond = moduleState({ module_id: "admin.users" });
  const afterTwoOptimisticUpdates = center([
    optimisticModuleControlState(originalFirst, false),
    optimisticModuleControlState(originalSecond, false),
  ]);

  const rolledBackFirst = updateModuleControlCenterItem(
    afterTwoOptimisticUpdates,
    originalFirst.org_id,
    originalFirst.module_id,
    () => originalFirst,
  );

  assert.equal(rolledBackFirst.organizations[0].modules[0], originalFirst);
  assert.equal(rolledBackFirst.organizations[0].modules[1].enabled, false);
  assert.equal(
    rolledBackFirst.organizations[0].modules[1].runtime_status,
    "disabled",
  );
});

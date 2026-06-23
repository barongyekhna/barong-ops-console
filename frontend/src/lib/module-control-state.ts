import type {
  ModuleControlCenterResponse,
  ModuleControlState,
} from "@/lib/module-control-api";

export function moduleControlToggleKey(
  module: Pick<ModuleControlState, "module_id" | "org_id">,
) {
  return `${module.org_id}:${module.module_id}`;
}

export function optimisticModuleControlState(
  module: ModuleControlState,
  enabled: boolean,
): ModuleControlState {
  return {
    ...module,
    enabled,
    last_error_at: null,
    runtime_error_code: null,
    runtime_error_message: null,
    runtime_status: enabled ? "active" : "disabled",
  };
}

export function updateModuleControlCenterItem(
  center: ModuleControlCenterResponse | null,
  orgId: string,
  moduleId: string,
  updater: (module: ModuleControlState) => ModuleControlState,
): ModuleControlCenterResponse | null {
  if (!center) {
    return center;
  }

  let didUpdate = false;
  const organizations = center.organizations.map((group) => {
    if (group.org_id !== orgId) {
      return group;
    }

    let didUpdateGroup = false;
    const modules = group.modules.map((module) => {
      if (module.module_id !== moduleId) {
        return module;
      }

      didUpdate = true;
      didUpdateGroup = true;
      return updater(module);
    });

    return didUpdateGroup ? { ...group, modules } : group;
  });

  return didUpdate ? { ...center, organizations } : center;
}

export function replaceModuleControlCenterItem(
  center: ModuleControlCenterResponse | null,
  module: ModuleControlState,
): ModuleControlCenterResponse | null {
  return updateModuleControlCenterItem(
    center,
    module.org_id,
    module.module_id,
    () => module,
  );
}

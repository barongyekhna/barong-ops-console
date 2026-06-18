import type { ReactNode } from "react";

import { AdapterAccessProvider } from "@/components/adapter-access-provider";
import { AuthGuard } from "@/components/auth-guard";
import { CapabilityStateProvider } from "@/components/capability-state-provider";
import { ConsoleShell } from "@/components/console-shell";
import { ModuleAccessProvider } from "@/components/module-access-provider";
import { PermissionRouteGuard } from "@/components/permission-route-guard";

export default function ProtectedLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <CapabilityStateProvider>
        <ModuleAccessProvider>
          <AdapterAccessProvider>
            <ConsoleShell>
              <PermissionRouteGuard>{children}</PermissionRouteGuard>
            </ConsoleShell>
          </AdapterAccessProvider>
        </ModuleAccessProvider>
      </CapabilityStateProvider>
    </AuthGuard>
  );
}

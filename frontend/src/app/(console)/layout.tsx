import type { ReactNode } from "react";

import { AdapterAccessProvider } from "@/components/adapter-access-provider";
import { AuthGuard } from "@/components/auth-guard";
import { CapabilitySidebarProvider } from "@/components/capability-sidebar-provider";
import { ConsoleShell } from "@/components/console-shell";
import { ModuleAccessProvider } from "@/components/module-access-provider";
import { PermissionRouteGuard } from "@/components/permission-route-guard";

export default function ProtectedLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <ModuleAccessProvider>
        <AdapterAccessProvider>
          <CapabilitySidebarProvider>
            <ConsoleShell>
              <PermissionRouteGuard>{children}</PermissionRouteGuard>
            </ConsoleShell>
          </CapabilitySidebarProvider>
        </AdapterAccessProvider>
      </ModuleAccessProvider>
    </AuthGuard>
  );
}

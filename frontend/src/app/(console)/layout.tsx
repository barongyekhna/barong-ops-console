import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { ConsoleShell } from "@/components/console-shell";
import { ModuleAccessProvider } from "@/components/module-access-provider";
import { PermissionRouteGuard } from "@/components/permission-route-guard";

export default function ProtectedLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <ModuleAccessProvider>
        <ConsoleShell>
          <PermissionRouteGuard>{children}</PermissionRouteGuard>
        </ConsoleShell>
      </ModuleAccessProvider>
    </AuthGuard>
  );
}

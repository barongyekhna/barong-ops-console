import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { ConsoleShell } from "@/components/console-shell";
import { PermissionRouteGuard } from "@/components/permission-route-guard";

export default function ProtectedLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <ConsoleShell>
        <PermissionRouteGuard>{children}</PermissionRouteGuard>
      </ConsoleShell>
    </AuthGuard>
  );
}

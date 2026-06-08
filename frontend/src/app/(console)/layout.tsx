import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { ConsoleShell } from "@/components/console-shell";

export default function ProtectedLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <ConsoleShell>{children}</ConsoleShell>
    </AuthGuard>
  );
}

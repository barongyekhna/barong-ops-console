"use client";

import { useAuth } from "@/components/auth-provider";
import { ModuleRegistryProductView } from "@/components/module-registry-product-view";
import { isOwnerRole } from "@/lib/roles";

export default function ApiKeyManagementPage() {
  const { user } = useAuth();
  const isOwner = isOwnerRole(user?.role);

  return isOwner ? <ModuleRegistryProductView /> : null;
}

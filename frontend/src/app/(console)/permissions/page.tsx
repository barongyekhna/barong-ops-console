import type { Metadata } from "next";

import { PermissionsProductView } from "@/components/permissions-product-view";

export const metadata: Metadata = {
  title: "权限管理",
};

export default function PermissionsPage() {
  return <PermissionsProductView />;
}

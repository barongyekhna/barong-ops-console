import type { Metadata } from "next";

import { PermissionsProductView } from "@/components/permissions-product-view";

export const metadata: Metadata = {
  title: "Permissions",
};

export default function PermissionsPage() {
  return <PermissionsProductView />;
}

import type { Metadata } from "next";

import { OrganizationProductView } from "@/components/organization-product-view";

export const metadata: Metadata = {
  title: "组织管理",
};

export default function OrganizationsPage() {
  return <OrganizationProductView />;
}

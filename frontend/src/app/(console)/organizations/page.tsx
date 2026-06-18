import type { Metadata } from "next";

import { OrganizationProductView } from "@/components/organization-product-view";

export const metadata: Metadata = {
  title: "Organizations",
};

export default function OrganizationsPage() {
  return <OrganizationProductView />;
}

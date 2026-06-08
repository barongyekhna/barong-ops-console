import { Package } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = {
  title: "Products",
};

export default function ProductsPage() {
  return (
    <EmptyState
      description="Product records will appear here when a product foundation is added."
      icon={Package}
      title="No products created yet."
    />
  );
}

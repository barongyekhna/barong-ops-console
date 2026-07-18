import type { Metadata } from "next";

import { CategoryTemplateManager } from "@/modules/k/product-knowledge/CategoryTemplateManager";

export const metadata: Metadata = {
  title: "K 类目规格模板",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function ProductCategoriesPage() {
  return <CategoryTemplateManager />;
}

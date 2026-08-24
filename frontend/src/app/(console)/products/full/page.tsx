import { redirect } from "next/navigation";

// M7 (QA 2026-08-22): /products/full rendered the identical ProductListFull as
// /products. Consolidated on /products; redirect keeps old links working.
export default function FullProductsPage() {
  redirect("/products");
}

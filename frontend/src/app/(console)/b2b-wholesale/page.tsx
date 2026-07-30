import type { Metadata } from "next";

import { B2BWorkspace } from "@/modules/b2b/B2BWorkspace";

export const metadata: Metadata = {
  title: "B2B 业务",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function B2BWholesalePage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">B2B</span>
        <div>
          <h1>B2B 业务</h1>
        </div>
      </section>
      <B2BWorkspace />
    </div>
  );
}

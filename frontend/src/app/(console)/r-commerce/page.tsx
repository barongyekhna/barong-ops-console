import type { Metadata } from "next";

import { RCommerceWorkspace } from "@/modules/r/commerce/RCommerceWorkspace";

export const metadata: Metadata = {
  title: "R系列自动化选品系统",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RCommercePage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">R</span>
        <h1>R系列自动化选品系统</h1>
        <p>V3 商业级选品闭环，当前全部走 mock provider。</p>
      </section>

      <RCommerceWorkspace />
    </div>
  );
}

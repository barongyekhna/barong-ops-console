import type { Metadata } from "next";

import { SmWorkspace } from "@/modules/sm/SmWorkspace";

export const metadata: Metadata = {
  title: "社媒运营",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function SmSocialPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">SM</span>
        <div>
          <h1>社媒运营</h1>
          <p>
            四周日历由排期器从 K 产品、GEO 指南、工艺事实推出来；每一格写成帖子后进内容台审。
            mock 期渠道全是手动，一条都不外发。
          </p>
        </div>
      </section>
      <SmWorkspace />
    </div>
  );
}

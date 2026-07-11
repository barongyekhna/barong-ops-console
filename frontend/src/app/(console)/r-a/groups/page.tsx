import type { Metadata } from "next";

import { GroupsBoard } from "@/modules/r/analysis/GroupsBoard";
import { RaSubnav } from "@/modules/r/analysis/RaSubnav";

export const metadata: Metadata = {
  title: "R-A 选品分组",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RaGroupsPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">R-A</span>
        <div>
          <h1>选品分组</h1>
          <p>
            终审通过的产品按渠道自动落入三个池子：亚马逊可售、独立站广告、独立站
            SEO。从这里一键搬进 K 系列，关键词自动带入。
          </p>
        </div>
      </section>
      <RaSubnav />
      <GroupsBoard />
    </div>
  );
}

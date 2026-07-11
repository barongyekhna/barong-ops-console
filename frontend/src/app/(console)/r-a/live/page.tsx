import type { Metadata } from "next";

import { LiveDeck } from "@/modules/r/analysis/LiveDeck";
import { RaSubnav } from "@/modules/r/analysis/RaSubnav";

export const metadata: Metadata = {
  title: "R-A 选品直播间",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RaLivePage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">R-A</span>
        <div>
          <h1>选品直播间</h1>
          <p>
            产品卡逐一进场，初筛、图搜、利润门、竞争富化、GPT 终审逐行跳出；
            合格右滑入组，不合格左滑出局，拿不准的落进待滑堆等你亲手滑。
          </p>
        </div>
      </section>
      <RaSubnav />
      <LiveDeck />
    </div>
  );
}

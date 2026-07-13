import type { Metadata } from "next";

import { EnrichmentDeck } from "@/modules/f/enrichment/EnrichmentDeck";

export const metadata: Metadata = {
  title: "F 类目富化",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function FEnrichmentPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">F</span>
        <div>
          <h1>F 类目富化</h1>
          <p>
            铺类目，不选爆款：在谷歌类目树上圈定要做的板块 → Serper
            逐类目收割关键词 → 1688 找货建候选池（红线只标记不毙掉）→
            你人工放行 → 一键进 K，走文案 / 作图 / 上架的现成链。
          </p>
        </div>
      </section>
      <EnrichmentDeck />
    </div>
  );
}

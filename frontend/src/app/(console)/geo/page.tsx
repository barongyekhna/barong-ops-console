import type { Metadata } from "next";

import { GeoContentDeck } from "@/modules/geo/content/GeoContentDeck";

export const metadata: Metadata = {
  title: "GEO 内容引擎",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function GeoContentPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">GEO</span>
        <div>
          <h1>GEO 内容引擎</h1>
          <p>
            沿 K 的类目树，把产品的真实事实自动重组成 AI 答案引擎会引用的导购内容
            （问答块 / 对比 / 场景）。每篇点名产品并内链到产品页——内容被引用时，
            产品和链接一起进入 AI 的答案。这里生成、审阅；发布是下一步。
          </p>
        </div>
      </section>
      <GeoContentDeck />
    </div>
  );
}

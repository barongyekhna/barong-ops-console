import type { Metadata } from "next";

import { CraftFactDeck } from "@/modules/seo/facts/CraftFactDeck";

export const metadata: Metadata = {
  title: "SEO 内容引擎",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function SeoContentPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">SEO</span>
        <div>
          <h1>SEO 内容引擎 · 工艺事实库</h1>
          <p>
            GEO 写的是接地在产品规格上的买家问句；SEO 负责 GEO 够不到的部分——
            工艺、制造、品牌。这些内容不靠产品数量，靠这里的事实厚度。
            每条事实带依据与版本：工艺一改就升版，引用旧版的内容立刻进「需复核」。
          </p>
        </div>
      </section>
      <CraftFactDeck />
    </div>
  );
}

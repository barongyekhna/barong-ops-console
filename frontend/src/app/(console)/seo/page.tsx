import type { Metadata } from "next";

import { SeoDeck } from "@/modules/seo/SeoDeck";

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
          <h1>SEO 内容引擎</h1>
          <p>
            GEO 写的是接地在产品规格上的买家问句，卡在产品数量上；SEO 负责 GEO
            够不到的部分——工艺、制造、品牌、B 端采购。这条线不靠产品数量，
            靠工艺事实的厚度。选题、生成、审阅、发布、监测都在这里，
            AI 的每个数字都要有据，写不出来就如实说缺什么。
          </p>
        </div>
      </section>
      <SeoDeck />
    </div>
  );
}

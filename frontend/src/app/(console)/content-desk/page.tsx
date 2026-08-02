import type { Metadata } from "next";

import { ContentDesk } from "@/modules/content/desk/ContentDesk";

export const metadata: Metadata = {
  title: "内容台",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function ContentDeskPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">内容台</span>
        <div>
          <h1>内容台</h1>
          <p>
            GEO 和 SEO 合成一页。你不用记自己在哪一步——这页会告诉你现在卡在哪儿。
            四步里只有「审」需要你；选题、生成、发布之后的内链和入口都是机器在跑。
            要调细节，去 GEO / SEO 两个引擎页面。
          </p>
        </div>
      </section>
      <ContentDesk />
    </div>
  );
}

import type { Metadata } from "next";

import { UploadDeck } from "@/modules/p/upload/UploadDeck";

export const metadata: Metadata = {
  title: "P系列自动化上传",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function PUploadPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">P</span>
        <div>
          <h1>P系列自动化上传</h1>
          <p>
            产品过门禁后一键派单：控制台打包文案 + 成品图 + SEO → n8n
            搬图进 WordPress 媒体库 → WooCommerce 建品/更新 → 回报落账。
            这里是全链路的驾驶舱台账。
          </p>
        </div>
      </section>
      <UploadDeck />
    </div>
  );
}

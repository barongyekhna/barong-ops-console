import type { Metadata } from "next";

import { ShippingDeck } from "@/modules/w/siteops/ShippingDeck";

export const metadata: Metadata = {
  title: "W-S 物流网络中枢",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function WSiteOpsPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">W</span>
        <div>
          <h1>W-S 物流网络中枢</h1>
          <p>
            运费模板在这里创建、经 n8n 同步进 WooCommerce；订单与物流单号在这里管理，17TRACK 轨迹自动回流。发货永远是人工决定——这里只做看得清、传得快。
          </p>
        </div>
      </section>
      <ShippingDeck />
    </div>
  );
}

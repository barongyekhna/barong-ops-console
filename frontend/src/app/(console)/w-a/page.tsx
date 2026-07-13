import type { Metadata } from "next";

import { ShippingDeck } from "@/modules/w/siteops/ShippingDeck";

export const metadata: Metadata = {
  title: "W-A 网站运营中枢",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function WSiteOpsPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">W</span>
        <div>
          <h1>W-A 网站运营中枢</h1>
          <p>
            运费中枢：确定性规则表给独立站产品分配 Woo
            运费模板——重量段位查表、带电与美国仓单独走线、缺数据不放行。
            每个产品都能看到它为什么在这个模板里。
          </p>
        </div>
      </section>
      <ShippingDeck />
    </div>
  );
}

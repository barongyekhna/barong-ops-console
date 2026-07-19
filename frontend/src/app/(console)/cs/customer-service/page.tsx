import type { Metadata } from "next";
import { Suspense } from "react";

import { CustomerServiceDeck } from "@/modules/cs/customer-service/CustomerServiceDeck";

export const metadata: Metadata = {
  title: "客服中心",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

function CustomerServiceFallback() {
  return (
    <div className="cs-page-fallback" role="status">
      正在加载客服中心…
    </div>
  );
}

export default function CustomerServicePage() {
  return (
    <div className="page-stack cs-customer-service-page">
      <section className="page-heading">
        <span className="section-index">CS</span>
        <div>
          <h1>客服中心</h1>
          <p>站点咨询直达客服工作台，零售与批发分队独立处理。</p>
        </div>
      </section>
      <Suspense fallback={<CustomerServiceFallback />}>
        <CustomerServiceDeck />
      </Suspense>
    </div>
  );
}

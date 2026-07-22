import type { Metadata } from "next";

import { SiteHealthWorkspace } from "@/modules/h/sitehealth/SiteHealthWorkspace";

export const metadata: Metadata = {
  title: "H 站点健康",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function HSiteHealthPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">H</span>
        <div>
          <h1>H 站点健康</h1>
        </div>
      </section>
      <SiteHealthWorkspace />
    </div>
  );
}

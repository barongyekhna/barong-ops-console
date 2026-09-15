import type { Metadata } from "next";

import { AmzWorkspace } from "@/modules/amz/AmzWorkspace";

export const metadata: Metadata = {
  title: "亚马逊运营",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function AmzOpsPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">A</span>
        <div>
          <h1>亚马逊运营</h1>
          <p>
            四家公司、五个店铺,一张表看。数据主键是店铺,授权也按店铺给;
            与 K/I/M 零交集。上线后至少一个月全影子:四名员工只提建议,不碰亚马逊。
          </p>
        </div>
      </section>
      <AmzWorkspace />
    </div>
  );
}

"use client";

import { CircleSlash2 } from "lucide-react";

export function ControlPlaneSettingsView() {
  return (
    <section className="product-console" aria-label="设置">
      <div className="ops-empty-state" role="status">
        <CircleSlash2 aria-hidden="true" size={24} />
        <strong>暂不可用</strong>
        <span>设置功能尚未开放，当前不会展示或保存任何配置。</span>
      </div>
    </section>
  );
}

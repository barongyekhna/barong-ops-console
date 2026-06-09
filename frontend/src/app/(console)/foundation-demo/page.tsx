import type { Metadata } from "next";

import { FoundationDemoPanel } from "@/components/foundation-demo-panel";

export const metadata: Metadata = {
  title: "Foundation Demo",
};

export default function FoundationDemoPage() {
  return (
    <div className="page-stack">
      <div className="page-heading">
        <span className="section-index">F11</span>
        <div>
          <h2>Foundation Demo</h2>
          <p>Record a safe internal exercise of the foundation data loop.</p>
        </div>
      </div>
      <FoundationDemoPanel />
    </div>
  );
}

import type { Metadata } from "next";

import { N8nTestPanel } from "@/components/n8n-test-panel";

export const metadata: Metadata = {
  title: "n8n Test Bridge",
};

export default function N8nTestPage() {
  return (
    <div className="page-stack">
      <div className="page-heading">
        <span className="section-index">F12</span>
        <div>
          <h2>n8n Test Bridge</h2>
          <p>Verify the safe Console to n8n test callback loop.</p>
        </div>
      </div>
      <N8nTestPanel />
    </div>
  );
}

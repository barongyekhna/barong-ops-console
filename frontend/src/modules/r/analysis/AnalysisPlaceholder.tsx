import { LockKeyhole } from "lucide-react";

import styles from "./AnalysisPlaceholder.module.css";

const ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司";

export function AnalysisPlaceholder({ view }: { view: "dashboard" | "analysis" }) {
  return (
    <div className={styles.placeholder}>
      <section className={styles.panel}>
        <div className={styles.panelHeader}>
          <div>
            <h2>{view === "dashboard" ? "Analysis Dashboard" : "Product Analysis"}</h2>
            <p>{ORGANIZATION_NAME}</p>
          </div>
          <span className={styles.badge}>
            <LockKeyhole aria-hidden="true" size={15} />
            inactive
          </span>
        </div>

        <div className={styles.facts}>
          <div className={styles.fact}>
            <span>Runtime</span>
            <strong>not started</strong>
          </div>
          <div className={styles.fact}>
            <span>Dependency</span>
            <strong>locked_until_rw_ready</strong>
          </div>
          <div className={styles.fact}>
            <span>Data Layer</span>
            <strong>awaiting key-bound R-W data</strong>
          </div>
        </div>
      </section>
    </div>
  );
}


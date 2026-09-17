"use client";

import { useEffect, useState } from "react";

import styles from "./AmzWorkspace.module.css";
import { getExperience, type AmzExperienceEntry } from "./api";

const KIND_LABEL: Record<string, string> = { precision: "命中率", param: "门槛漂移", rejection: "驳回规律", image: "换图回看" };
const EMPLOYEE_NAME: Record<string, string> = { A: "殷笑笑", B: "殷熊", C: "殷长辰", D: "殷素素" };

/** 经验库:建议 28 天后对不对、老板驳回的规律、门槛怎么漂的、换图前后。每周自动刷新,规则生成建议前会先查这里。 */
export function ExperiencePanel() {
  const [items, setItems] = useState<AmzExperienceEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getExperience()
      .then((payload) => setItems(payload.items))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  return (
    <section className={styles.panel} aria-label="经验库">
      <div className={styles.panelHead}>
        <h2>经验库</h2>
        <span className={styles.muted}>每周自动刷新 · 样本不满 6 条不下结论 · 门槛一次只动一档</span>
      </div>
      <div className={styles.sheetForm} style={{ padding: "14px 16px 16px" }}>
        {error ? <div className={styles.bad}>{error}</div> : null}
        {items.length === 0 && !error ? <div className={styles.muted}>还没有经验条目。每周跑一次回测和结果判定,攒够样本才会出现。</div> : null}
        {items.map((item) => (
          <div className={styles.verdictRow} key={item.id}>
            <b>
              {KIND_LABEL[item.kind] ?? item.kind}
              {item.employee ? ` · ${EMPLOYEE_NAME[item.employee] ?? item.employee}` : ""}
            </b>
            <span>{item.statement}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

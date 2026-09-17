"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import styles from "./AmzWorkspace.module.css";
import { completeAdsOauth, type AdsOauthResult } from "./api";

/** 亚马逊授权回跳页:拿 URL 里的 code/state 交给后端收尾。授权码只活五分钟,所以一进页就换,不等人点。 */
export function AdsCallback() {
  const params = useSearchParams();
  const [status, setStatus] = useState<"working" | "done" | "error">("working");
  const [message, setMessage] = useState<string>("正在换令牌…");
  const [result, setResult] = useState<AdsOauthResult | null>(null);
  const fired = useRef(false);

  useEffect(() => {
    if (fired.current) return;
    fired.current = true;
    const code = params.get("code") ?? "";
    const state = params.get("state") ?? "";
    const error = params.get("error") ?? "";
    if (error) {
      setStatus("error");
      setMessage(`亚马逊拒绝了授权:${error} ${params.get("error_description") ?? ""}`.trim());
      return;
    }
    if (!code || !state) {
      setStatus("error");
      setMessage("链接里没有授权码。请回到管理页重新点「开始授权」。");
      return;
    }
    completeAdsOauth({ code, state })
      .then((payload) => {
        setResult(payload);
        setStatus("done");
        setMessage("接通了。");
      })
      .catch((err) => {
        setStatus("error");
        setMessage(err instanceof Error ? err.message : String(err));
      });
  }, [params]);

  return (
    <section className={styles.panel} aria-label="广告授权结果">
      <div className={styles.panelHead}>
        <h2>{status === "done" ? "已接通" : status === "error" ? "没接通" : "处理中"}</h2>
        <span className={styles.muted}>{message}</span>
      </div>
      <div className={styles.sheetForm} style={{ padding: "14px 16px 16px" }}>
        {result ? (
          <div className={styles.verdict}>
            <div className={styles.verdictRow}>
              <b>店铺</b>
              <span>{result.store_code}</span>
            </div>
            <div className={styles.verdictRow}>
              <b>广告 profile</b>
              <span>
                {result.profiles.map((p) => `${p.profileId}(${p.countryCode} · ${p.currencyCode})`).join("、")} · 账号下共 {result.all_profiles} 个
              </span>
            </div>
            <div className={styles.verdictRow}>
              <b>存放</b>
              <span className={styles.muted}>密钥管理 · {result.alias} · 密钥健康页会自动核一遍</span>
            </div>
          </div>
        ) : null}
        <div className={styles.sheetActions}>
          <Link className={styles.linkButton} href="/amz?tab=manage">
            回到管理页
          </Link>
        </div>
      </div>
    </section>
  );
}

"use client";

import { useState } from "react";

import styles from "./AmzWorkspace.module.css";
import { startAdsOauth, type AmzStore } from "./api";

/**
 * 广告 API 授权:填这家公司的 LWA 钥匙对 → 跳去亚马逊点一下授权 → 回跳页自动换令牌、拉 profile、存密钥。
 * 钥匙对只经过这一次提交(加密暂存在店铺记录里,成功后进密钥管理并清掉),不进聊天、不进日志。
 */
export function AdsAuthPanel({ stores }: { stores: AmzStore[] }) {
  const [storeCode, setStoreCode] = useState(stores[0]?.store_code ?? "");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function go() {
    if (!clientId.trim() || !clientSecret.trim()) {
      setStatus("两样都要:客户端编码(amzn1.application-oa2-client.…)和客户端密钥(amzn1.oa2-cs.…)。");
      return;
    }
    setBusy(true);
    try {
      const payload = await startAdsOauth({ store_code: storeCode, client_id: clientId.trim(), client_secret: clientSecret.trim() });
      setClientSecret("");
      setStatus("正在跳去亚马逊,用这家公司的广告后台账号登录并点「允许」。");
      window.location.href = payload.authorize_url;
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <section className={styles.panel} aria-label="广告 API 授权">
      <div className={styles.panelHead}>
        <h2>广告 API 授权</h2>
        <span className={styles.muted}>一家公司一套钥匙 · 点一下授权 · 令牌和 profile 自动进密钥管理</span>
      </div>
      <div className={styles.sheetForm} style={{ padding: "14px 16px 16px" }}>
        <div className={styles.sheetRow}>
          <label>
            店铺
            <select onChange={(e) => setStoreCode(e.target.value)} value={storeCode}>
              {stores.map((store) => (
                <option key={store.store_code} value={store.store_code}>
                  {store.display_name} · {store.store_code}
                </option>
              ))}
            </select>
          </label>
          <label>
            客户端编码(Client ID)
            <input autoComplete="off" onChange={(e) => setClientId(e.target.value)} placeholder="amzn1.application-oa2-client.…" value={clientId} />
          </label>
          <label>
            客户端密钥(Client Secret)
            <input autoComplete="off" onChange={(e) => setClientSecret(e.target.value)} placeholder="amzn1.oa2-cs.v1.…" type="password" value={clientSecret} />
          </label>
        </div>
        <div className={styles.sheetActions}>
          <button className={styles.button} disabled={busy || !storeCode} onClick={() => void go()} type="button">
            开始授权(跳去亚马逊)
          </button>
          <span className={styles.muted}>
            {status ?? "回调地址已在 LWA 应用里登记:https://ops.barongyekhna.com/amz/ads-callback"}
          </span>
        </div>
      </div>
    </section>
  );
}

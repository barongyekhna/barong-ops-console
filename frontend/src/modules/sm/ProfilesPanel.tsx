"use client";

import { useEffect, useState } from "react";

import styles from "./SmWorkspace.module.css";
import {
  type Channel,
  type Platform,
  type ProfilesResponse,
  PLATFORM_LABEL,
  createChannel,
  getProfiles,
  patchChannel,
} from "./api";

const PLATFORMS: Platform[] = ["pinterest", "instagram", "facebook"];

export function ProfilesPanel({ channels, onChanged }: { channels: Channel[]; onChanged: () => void }) {
  const [data, setData] = useState<ProfilesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [handles, setHandles] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getProfiles()
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const byPlatform = new Map(channels.map((c) => [c.platform, c]));

  const register = async (platform: Platform) => {
    setBusy(platform);
    try {
      await createChannel({ platform, handle: handles[platform] || null });
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const toggle = async (channel: Channel) => {
    setBusy(channel.platform);
    try {
      await patchChannel(channel.id, { status: channel.status === "active" ? "paused" : "active" });
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={styles.workspace}>
      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <h2 className={styles.panelTitle}>渠道登记</h2>
          <span className={styles.muted}>mock 期 mode 只有 manual；登记日期就是账号阶段（14 天铺货期）的起点</span>
        </div>
        {error ? <div className={styles.error}>{error}</div> : null}
        <table className={styles.table}>
          <thead>
            <tr><th>平台</th><th>账号</th><th>模式</th><th>状态</th><th>登记于</th><th></th></tr>
          </thead>
          <tbody>
            {PLATFORMS.map((platform) => {
              const channel = byPlatform.get(platform);
              return (
                <tr key={platform}>
                  <td>{PLATFORM_LABEL[platform]}</td>
                  <td>
                    {channel ? (channel.handle || "—") : (
                      <input className={styles.input} onChange={(e) => setHandles({ ...handles, [platform]: e.target.value })} placeholder="账号名（可空）" value={handles[platform] ?? ""} />
                    )}
                  </td>
                  <td>{channel?.mode ?? "manual"}</td>
                  <td>{channel ? <span className={styles.status} data-status={channel.status === "active" ? "approved" : "pending"}>{channel.status}</span> : <span className={styles.muted}>未登记</span>}</td>
                  <td className={styles.muted}>{channel?.created_at?.slice(0, 10) ?? "—"}</td>
                  <td>
                    {channel ? (
                      <button className={styles.btnGhost} disabled={busy === platform} onClick={() => toggle(channel)} type="button">{channel.status === "active" ? "暂停" : "启用"}</button>
                    ) : (
                      <button className={styles.btnPrimary} disabled={busy === platform} onClick={() => register(platform)} type="button">登记</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <h2 className={styles.panelTitle}>渠道档案 {data ? `· ${data.version}` : ""}</h2>
          <span className={styles.muted}>档案是硬约束，改动走版本号；指标只能在配比 ±10 点内微调</span>
        </div>
        {data ? (
          <table className={styles.table}>
            <thead>
              <tr><th>平台</th><th>调性</th><th>配比</th><th>节奏</th><th>图</th><th>标签</th><th>链接</th><th>备注</th></tr>
            </thead>
            <tbody>
              {data.profiles.map((p) => (
                <tr key={p.platform}>
                  <td>{PLATFORM_LABEL[p.platform]}</td>
                  <td>{p.voice}</td>
                  <td>{Object.entries(p.pillar_mix).filter(([, v]) => v > 0).map(([k, v]) => `${k} ${v}`).join(" · ")}</td>
                  <td>{p.per_day[1] > 0 ? `每天 ${p.per_day[0]}–${p.per_day[1]}` : Object.entries(p.weekly_template).map(([d, v]) => `周${["一", "二", "三", "四", "五", "六", "日"][Number(d)]} ${v}`).join(" · ")}<br /><span className={styles.muted}>{p.windows_pt.join(" / ")} PT</span></td>
                  <td>{p.image.ratio} · {p.image.min_px.join("×")}</td>
                  <td>≤{p.hashtags.max}</td>
                  <td>{p.link.mode}</td>
                  <td className={styles.muted}>{p.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className={styles.muted}>加载中…</p>
        )}
      </section>

      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <h2 className={styles.panelTitle}>图片需求单（支柱 × 平台）</h2>
        </div>
        {data ? (
          <table className={styles.table}>
            <thead>
              <tr><th>支柱</th><th>平台</th><th>允许角色</th><th>比例</th><th>张数</th><th>叠字</th><th>必须真照片</th><th>字卡兜底</th><th>形态</th></tr>
            </thead>
            <tbody>
              {data.image_requirements.map((r) => (
                <tr key={`${r.pillar}-${r.platform}`}>
                  <td><span className={styles.pillar} data-pillar={r.pillar}>{r.pillar}</span></td>
                  <td>{PLATFORM_LABEL[r.platform]}</td>
                  <td>{r.roles.join(", ")}</td>
                  <td>{r.ratio}</td>
                  <td>{r.count_min === r.count_max ? r.count_min : `${r.count_min}–${r.count_max}`}</td>
                  <td>{r.overlay ? "是" : "否"}</td>
                  <td>{r.must_be_real ? "是" : "否"}</td>
                  <td>{r.text_card_ok ? "可" : "—"}</td>
                  <td className={styles.muted}>{r.post_kind}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>
    </div>
  );
}

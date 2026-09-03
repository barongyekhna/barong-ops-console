"use client";

import { useCallback, useEffect, useState } from "react";

import { exportLineSheet } from "../wholesale/api";
import styles from "./StoreTypes.module.css";
import {
  type StoreType,
  type StoreTypeList,
  addStoreTypeCategory,
  createStoreType,
  getStoreTypes,
  patchStoreType,
  removeStoreTypeCategory,
} from "./api";

const STATUS_LABELS: Record<string, string> = {
  idle: "未开跑",
  active: "正在跑",
  paused: "已暂停",
  retired: "已退役",
};

export function StoreTypeWorkspace() {
  const [data, setData] = useState<StoreTypeList | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [newKey, setNewKey] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [categoryDrafts, setCategoryDrafts] = useState<Record<string, string>>(
    {},
  );
  // 店型是上架时自动建出来的，没货的先不显示——否则界面上一堆空壳。
  const [showEmpty, setShowEmpty] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getStoreTypes());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const withBusy = async (fn: () => Promise<string>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setNotice(await fn());
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const doCreate = () =>
    withBusy(async () => {
      await createStoreType({ key: newKey.trim(), label: newLabel.trim() });
      setNewKey("");
      setNewLabel("");
      return `已新建店型：${newLabel}`;
    });

  const doToggleRun = (entry: StoreType) =>
    withBusy(async () => {
      const next = entry.outreach_status === "active" ? "paused" : "active";
      await patchStoreType(entry.key, { outreach_status: next });
      return next === "active"
        ? `「${entry.label}」开跑了。现在抓客户只会抓这一类店。`
        : `「${entry.label}」已停跑，位置空出来了。`;
    });

  const doAddCategory = (entry: StoreType) =>
    withBusy(async () => {
      const raw = (categoryDrafts[entry.key] ?? "").trim();
      if (!raw) {
        throw new Error("先填类目前缀，比如 Toys & Games");
      }
      const prefix = raw
        .split(">")
        .map((part) => part.trim())
        .filter(Boolean);
      await addStoreTypeCategory(entry.key, prefix);
      setCategoryDrafts((prev) => ({ ...prev, [entry.key]: "" }));
      return `「${entry.label}」挂上了类目：${prefix.join(" > ")}`;
    });

  const doRemoveCategory = (entry: StoreType, categoryId: string) =>
    withBusy(async () => {
      await removeStoreTypeCategory(entry.key, categoryId);
      return `已摘掉一个类目`;
    });

  // 图册按店型出：这家礼品店该看到的是"所有我能卖给礼品店的货"，
  // 横跨几个类目也一本给全，而不是切成几本薄册子。
  const doExport = (entry: StoreType) =>
    withBusy(async () => {
      const { blob, filename } = await exportLineSheet({
        fmt: "pdf",
        store_type: entry.key,
        edition_label: new Date().toISOString().slice(0, 7),
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      return `已导出 ${filename}`;
    });

  const minReady = data?.min_ready_items ?? 30;
  const all = data?.store_types ?? [];
  // 没货就先折叠——但有待审候选客户的店型绝不折叠(否则 40 个待处理线索被
  // 「没货」标签盖住,人根本看不到)。判据 = 有货 或 有待审线索。
  const visible = showEmpty
    ? all
    : all.filter((entry) => entry.total_items > 0 || entry.prospects_new > 0);
  const hiddenCount = all.length - visible.length;

  return (
    <div className={styles.workspace}>
      <section className={styles.explainer}>
        <h2>为什么是店型，不是类目</h2>
        <p>
          一家礼品店同时买你的捏捏球和家居小件——他是<strong>一个买家买了两样</strong>，
          不是两个买家。产品从 10 个涨到 300 个，店型还是这四五种，
          变的是<strong>每种店型的图册变厚</strong>，同一个买家客单价往上走。
        </p>
        <p>
          <strong>你不用判断哪个类目该配哪种店。</strong>「谷歌类目 → 店型」的
          对照表写死在系统里（武器、情趣用品这类已排除）。K/P 上架一款产品，
          它该进的店型就自动出现在这里，带<span className={styles.newTag}>新</span>
          标记的就是这次上架带出来的。
        </p>
        <p className={styles.gate}>
          ⚠ <strong>一次只允许 {data?.max_active ?? 1} 个店型在跑。</strong>
          这不是技术限制，是保护你——同时开几条线，回复你一个人接不住。
          要开新的，先把在跑的停掉。
        </p>
      </section>

      {error ? <p className={styles.error}>{error}</p> : null}
      {notice ? <p className={styles.notice}>{notice}</p> : null}

      {loading ? (
        <p className={styles.empty}>加载中…</p>
      ) : !visible.length ? (
        <p className={styles.empty}>
          还没有店型有货。上架一款产品，它该进的店型会自动出现在这里。
          {hiddenCount > 0 ? (
            <button
              className={styles.linkButton}
              onClick={() => setShowEmpty(true)}
              type="button"
            >
              先看看 {hiddenCount} 个还没货的店型
            </button>
          ) : null}
        </p>
      ) : (
        <ul className={styles.cardList}>
          {visible.map((entry) => {
            const running = entry.outreach_status === "active";
            const percent = Math.min(
              100,
              (entry.ready_items / Math.max(1, minReady)) * 100,
            );
            return (
              <li
                className={styles.card}
                data-running={running}
                key={entry.key}
              >
                <div className={styles.cardHead}>
                  <div>
                    <strong className={styles.label}>{entry.label}</strong>
                    {entry.newly_added ? (
                      <span className={styles.newTag}>新</span>
                    ) : null}
                    <span className={styles.key}>{entry.key}</span>
                  </div>
                  <span
                    className={styles.statusTag}
                    data-status={entry.outreach_status}
                  >
                    {STATUS_LABELS[entry.outreach_status] ??
                      entry.outreach_status}
                  </span>
                </div>

                <div className={styles.progressRow}>
                  <span className={styles.progressLabel}>
                    图册厚度 {entry.ready_items} / {minReady}
                    {entry.prospecting_unlocked ? (
                      <strong className={styles.unlocked}>　可以开跑</strong>
                    ) : (
                      <span className={styles.muted}>
                        　还差 {entry.shortfall} 个品
                      </span>
                    )}
                  </span>
                  <span className={styles.progressBarWrap}>
                    <span
                      className={styles.progressBar}
                      data-full={entry.prospecting_unlocked}
                      style={{ width: `${percent}%` }}
                    />
                  </span>
                </div>

                <div className={styles.categories}>
                  <span className={styles.sectionLabel}>吃这些类目</span>
                  {entry.categories.length === 0 ? (
                    <span className={styles.muted}>
                      还没挂类目——不知道能给这类店看什么货
                    </span>
                  ) : (
                    <ul className={styles.chipList}>
                      {entry.categories.map((category) => (
                        <li className={styles.chip} key={category.id}>
                          {category.category_prefix.join(" > ")}
                          <button
                            className={styles.chipRemove}
                            disabled={busy}
                            onClick={() =>
                              void doRemoveCategory(entry, category.id)
                            }
                            type="button"
                          >
                            ×
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className={styles.inlineForm}>
                    <input
                      className={styles.input}
                      onChange={(event) =>
                        setCategoryDrafts((prev) => ({
                          ...prev,
                          [entry.key]: event.target.value,
                        }))
                      }
                      placeholder="Toys & Games（用 > 分层，只填前缀）"
                      value={categoryDrafts[entry.key] ?? ""}
                    />
                    <button
                      className={styles.ghostButton}
                      disabled={busy}
                      onClick={() => void doAddCategory(entry)}
                      type="button"
                    >
                      挂上
                    </button>
                  </div>
                </div>

                <div className={styles.cardFoot}>
                  <span className={styles.funnel}>
                    候选客户 待审 {entry.prospects_new}／已通过{" "}
                    {entry.prospects_approved}
                  </span>
                  <span className={styles.footActions}>
                    <button
                      className={styles.ghostButton}
                      disabled={busy || entry.ready_items === 0}
                      onClick={() => void doExport(entry)}
                      type="button"
                    >
                      出图册
                    </button>
                    <button
                      className={
                        running ? styles.stopButton : styles.primaryButton
                      }
                      disabled={busy || (!running && !entry.prospecting_unlocked)}
                      onClick={() => void doToggleRun(entry)}
                      type="button"
                    >
                      {running ? "停跑" : "开跑"}
                    </button>
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {hiddenCount > 0 && visible.length > 0 ? (
        <button
          className={styles.linkButton}
          onClick={() => setShowEmpty(true)}
          type="button"
        >
          还有 {hiddenCount} 个店型没货，展开看看
        </button>
      ) : null}
      {showEmpty && all.length > 0 ? (
        <button
          className={styles.linkButton}
          onClick={() => setShowEmpty(false)}
          type="button"
        >
          收起没货的店型
        </button>
      ) : null}

      <section className={styles.panel}>
        <h3>手动新建店型</h3>
        <p className={styles.hint}>
          正常情况下你不用来这里——上架产品会自动带出店型。
          只有内置对照表没覆盖到的特殊档口，才需要手动加一行。
        </p>
        <div className={styles.inlineForm}>
          <input
            className={styles.input}
            onChange={(event) => setNewKey(event.target.value)}
            placeholder="hardware_store（英文小写下划线）"
            value={newKey}
          />
          <input
            className={styles.input}
            onChange={(event) => setNewLabel(event.target.value)}
            placeholder="五金店"
            value={newLabel}
          />
          <button
            className={styles.primaryButton}
            disabled={busy || !newKey.trim() || !newLabel.trim()}
            onClick={() => void doCreate()}
            type="button"
          >
            新建
          </button>
        </div>
      </section>
    </div>
  );
}

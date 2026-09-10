"use client";

/**
 * 把一份成本表快照通过 C19 发给人。
 *
 * 两个口径的差别不是显示层面的:选「仅出厂价」时,后端**生成卡片时就不放成本行**,
 * 那些数字压根不进这条消息——对方转发、复制、截图都漏不出去。所以这个选择在发出去
 * 之前必须想清楚,发完就收不回了。
 */

import { useEffect, useMemo, useState } from "react";

import { listC19Directory } from "@/modules/c19/api";
import type { C19Profile } from "@/modules/c19/types";

import base from "../inventory/Inventory.module.css";
import { Dialog } from "../inventory/Dialog";
import styles from "./Cost.module.css";
import { type ShareMode, getSheet, shareSheet } from "./api";

export function ShareDialog({
  sheetId,
  onClose,
}: {
  sheetId: string;
  onClose: () => void;
}) {
  const [people, setPeople] = useState<C19Profile[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [mode, setMode] = useState<ShareMode>("full");
  const [note, setNote] = useState("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [sheetNo, setSheetNo] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([listC19Directory({ limit: 200 }), getSheet(sheetId)])
      .then(([directory, sheet]) => {
        if (cancelled) return;
        setPeople(directory.items.filter((person) => !person.is_bot));
        setSheetNo(sheet.sheet_no);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "读取联系人失败");
      });
    return () => {
      cancelled = true;
    };
  }, [sheetId]);

  const visible = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return people;
    return people.filter((person) =>
      person.display_name.toLowerCase().includes(keyword),
    );
  }, [people, search]);

  const toggle = (userId: number) => {
    setSelected((current) =>
      current.includes(userId)
        ? current.filter((id) => id !== userId)
        : [...current, userId],
    );
  };

  const submit = async () => {
    if (!selected.length) return;
    setBusy(true);
    setError(null);
    try {
      const result = await shareSheet(sheetId, {
        recipient_user_ids: selected,
        share_mode: mode,
        message: note.trim() || null,
      });
      const okNames = result.delivered.map((row) => row.recipient_name);
      if (result.failed.length) {
        setError(
          `${result.failed.length} 人没发成功：` +
            result.failed.map((row) => row.error).join("；"),
        );
      }
      if (okNames.length) {
        setDone(`已送达并回读确认：${okNames.join("、")}`);
        setSelected([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "分享失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog onClose={onClose} title={`分享 ${sheetNo}`}>
      <div className={base.form}>
        {error ? <p className={base.error}>{error}</p> : null}
        {done ? <p className={styles.ok}>{done}</p> : null}

        <div className={base.field}>
          <span className={base.label}>发什么</span>
          <div className={styles.modeChoice}>
            <label className={styles.modeOption}>
              <input
                checked={mode === "full"}
                name="share-mode"
                onChange={() => setMode("full")}
                type="radio"
              />
              <span>
                <strong>完整明细</strong>
                <small>
                  物料单价、运费、人工、成本、毛利全给。发给自己人（贸易公司）用这个。
                </small>
              </span>
            </label>
            <label className={styles.modeOption}>
              <input
                checked={mode === "price_only"}
                name="share-mode"
                onChange={() => setMode("price_only")}
                type="radio"
              />
              <span>
                <strong>仅出厂价</strong>
                <small>
                  只给出厂价和有效期。成本数字**不会进这条消息**，对方转发也漏不出去。
                  发给外部客户用这个。
                </small>
              </span>
            </label>
          </div>
        </div>

        <div className={base.field}>
          <span className={base.label}>发给谁</span>
          <input
            className={base.input}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜名字"
            value={search}
          />
          <div className={styles.peopleList}>
            {visible.map((person) => (
              <label className={styles.person} key={person.user_id}>
                <input
                  checked={selected.includes(person.user_id)}
                  onChange={() => toggle(person.user_id)}
                  type="checkbox"
                />
                <span>{person.display_name}</span>
                <small className={base.muted}>
                  {person.affiliations
                    ?.map((affiliation) => affiliation.org_name)
                    .filter(Boolean)
                    .join(" / ")}
                </small>
              </label>
            ))}
            {!visible.length ? (
              <p className={base.empty}>没有匹配的人。</p>
            ) : null}
          </div>
        </div>

        <div className={base.field}>
          <span className={base.label}>附一句话（可留空）</span>
          <input
            className={base.input}
            maxLength={200}
            onChange={(event) => setNote(event.target.value)}
            value={note}
          />
        </div>

        <div className={base.footer}>
          <button
            className={base.btnPrimary}
            disabled={busy || !selected.length}
            onClick={submit}
            type="button"
          >
            {busy ? "发送中…" : `发给 ${selected.length} 人`}
          </button>
          <span className={base.hint}>
            发完会回读确认那条消息真的在对方会话里，确认了才记进台账。
          </span>
        </div>
      </div>
    </Dialog>
  );
}

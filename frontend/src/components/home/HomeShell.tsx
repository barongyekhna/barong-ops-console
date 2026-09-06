"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { ConsoleArcade } from "@/components/console-arcade";
import { DashboardScene } from "@/components/dashboard-scene";
import { OverlayModal } from "@/components/overlay-modal";

import { formatClock, type HomeBootstrapRead } from "./home-api";
import type { HomeCardDef } from "./home-types";
import { useHomeStream, type HomeStreamStatus } from "./useHomeStream";

const STATUS_LABEL: Record<HomeStreamStatus, string> = {
  connecting: "连接中",
  live: "推送流已连接 · 3 秒内",
  reconnecting: "重连中",
  polling: "推送不通 · 10 秒轮询",
  paused: "已暂停",
};

export type HomeShellProps = {
  bootstrap: HomeBootstrapRead;
  /** 这类组织的卡片注册表，顺序即显示顺序。 */
  registry: readonly HomeCardDef[];
  cardsById: ReadonlyMap<string, HomeCardDef>;
  /** 定制抽屉里的分组顺序。 */
  groups: readonly string[];
  /** 每类组织各记一份可见卡片。 */
  storageKey: string;
  /** 皮肤差异类；作用域类固定是 `home-store`（浮窗也靠它），不要换。 */
  extraClass?: string;
  eyebrow: string;
  title: string;
};

function readStoredVisible(storageKey: string): string[] | null {
  try {
    const stored = window.localStorage.getItem(storageKey);
    if (!stored) return null;
    const parsed: unknown = JSON.parse(stored);
    if (Array.isArray(parsed) && parsed.every((item) => typeof item === "string")) {
      return parsed as string[];
    }
  } catch {
    /* localStorage 不可用时忽略 */
  }
  return null;
}

/**
 * 主页骨架：一副骨，多张皮。贸易公司和制造公司各传一份注册表进来，
 * 双门可见性、持久化、网格、游戏厅、定制抽屉、浮窗、推送流全在这里，皮只管卡。
 *
 * 星场永远第一个子节点，游戏厅永远在网格之后；两者原样保留是用户的死规矩。
 */
export function HomeShell({
  bootstrap,
  registry,
  cardsById,
  groups,
  storageKey,
  extraClass,
  eyebrow,
  title,
}: HomeShellProps) {
  const capability = useFrontendCapabilityState();
  const { cards, status, lastAliveAt, patchCard, refetchCard } = useHomeStream(bootstrap);
  const defaultVisible = useMemo(
    () => registry.filter((def) => def.defaultVisible).map((def) => def.id),
    [registry],
  );

  const [visible, setVisible] = useState<string[]>(defaultVisible);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [openCardId, setOpenCardId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    const stored = readStoredVisible(storageKey);
    if (stored) setVisible(stored);
  }, [storageKey]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2_200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const persist = useCallback(
    (next: string[]) => {
      setVisible(next);
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        /* 忽略持久化失败 */
      }
    },
    [storageKey],
  );

  const setCardVisible = useCallback(
    (id: string, on: boolean) => {
      persist(on ? (visible.includes(id) ? visible : [...visible, id]) : visible.filter((v) => v !== id));
    },
    [persist, visible],
  );

  // 双门：服务端没给的卡（无权限）不出现；服务端给了但侧边栏认为模块不可进也不出现。
  const activeModules = useMemo(
    () =>
      new Set(
        capability.sidebarItems
          .filter((item) => item.state === "allowed" && item.can_enter)
          .map((item) => item.module_key),
      ),
    [capability.sidebarItems],
  );
  const available = useMemo(
    () =>
      registry.filter(
        (def) => cards.has(def.id) && (def.module_key === null || activeModules.has(def.module_key)),
      ),
    [activeModules, cards, registry],
  );
  const visibleCards = available.filter((def) => visible.includes(def.id));

  const closeDrawer = useCallback(() => setOpenCardId(null), []);
  const notify = useCallback((message: string) => setToast(message), []);
  const openDef = openCardId ? cardsById.get(openCardId) ?? null : null;
  const openCard = openCardId ? cards.get(openCardId) ?? null : null;
  const drawerPatch = useCallback(
    (updater: Parameters<typeof patchCard>[1]) => {
      if (openCardId) patchCard(openCardId, updater);
    },
    [openCardId, patchCard],
  );
  const drawerRefetch = useCallback(async () => {
    if (openCardId) await refetchCard(openCardId);
  }, [openCardId, refetchCard]);

  const rootClass = ["dashboard-page", "cc-dash", "home-store", extraClass].filter(Boolean).join(" ");
  const drawerClass = ["home-store", extraClass, "hs-drawer"].filter(Boolean).join(" ");
  const groupLabel = (def: HomeCardDef) =>
    def.group === "外部" ? "外部数据" : def.group === "模块" ? `模块 · ${def.moduleLabel ?? ""}` : def.group;

  return (
    <div className={rootClass}>
      <DashboardScene />

      <div className="cc-head">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h2>{title}</h2>
        </div>
        <div className="cc-head-right">
          <span
            className={`cc-status hs-live hs-live-${status}`}
            title={lastAliveAt ? `最近一帧 ${formatClock(new Date(lastAliveAt).toISOString())}` : undefined}
          >
            <i aria-hidden="true" />
            {STATUS_LABEL[status]}
          </span>
          <button className="cc-customize" onClick={() => setLibraryOpen(true)} type="button">
            ⚙ 定制
          </button>
        </div>
      </div>

      {visibleCards.length === 0 ? (
        <div className="cc-empty">
          <b>工作台是空的 ✨</b>
          <span>点右上「⚙ 定制」把你需要的卡片调出来</span>
          <button className="cc-customize" onClick={() => setLibraryOpen(true)} type="button">
            ⚙ 打开卡片库
          </button>
        </div>
      ) : (
        <div className="cc-grid hs-grid">
          {visibleCards.map((def) => {
            const card = cards.get(def.id);
            if (!card) return null;
            return (
              <div className={def.wide ? "cc-card wide" : "cc-card"} key={def.id}>
                <button
                  aria-label={`收起「${def.title}」`}
                  className="cc-hide"
                  onClick={() => setCardVisible(def.id, false)}
                  type="button"
                >
                  ×
                </button>
                <def.Card card={card} onOpen={() => setOpenCardId(def.id)} />
              </div>
            );
          })}
          <button className="cc-add" onClick={() => setLibraryOpen(true)} type="button">
            <span className="cc-add-plus">＋</span>
            <span>添加卡片</span>
          </button>
        </div>
      )}

      <ConsoleArcade />

      {libraryOpen ? (
        <>
          <button aria-label="关闭卡片库" className="cc-scrim" onClick={() => setLibraryOpen(false)} type="button" />
          <aside aria-label="卡片库" className="cc-drawer">
            <div className="cc-drawer-head">
              <div>
                <h3>卡片库</h3>
                <span>开关任意卡片 · 选择会被记住</span>
              </div>
              <button aria-label="关闭" className="cc-drawer-close" onClick={() => setLibraryOpen(false)} type="button">
                ×
              </button>
            </div>
            <div className="cc-drawer-body">
              {groups.map((group) => {
                const groupCards = available.filter((def) => def.group === group);
                if (groupCards.length === 0) return null;
                return (
                  <div key={group}>
                    <div className="cc-group">{group}</div>
                    {groupCards.map((def) => {
                      const on = visible.includes(def.id);
                      return (
                        <div className="cc-lib" key={def.id}>
                          <div>
                            <div className="cc-lib-name">{def.title}</div>
                            <div className="cc-lib-desc">{def.desc}</div>
                          </div>
                          <button
                            aria-label={on ? `隐藏「${def.title}」` : `显示「${def.title}」`}
                            aria-pressed={on}
                            className={on ? "cc-switch on" : "cc-switch"}
                            onClick={() => setCardVisible(def.id, !on)}
                            type="button"
                          />
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
            <div className="cc-drawer-foot">
              <button onClick={() => persist(defaultVisible)} type="button">
                恢复默认
              </button>
              <button onClick={() => persist([])} type="button">
                全部收起
              </button>
            </div>
          </aside>
        </>
      ) : null}

      {openDef && openCard ? (
        <OverlayModal label={openDef.title} onClose={closeDrawer} placement="drawer" width="min(520px, 100%)">
          {/* OverlayModal 用 portal 挂到 body，根节点必须自带 .home-store 作用域，
              否则所有 .hs-* 样式和 --cc-* 变量都命中不了。关闭钮由 OverlayModal 自带。 */}
          <div className={drawerClass}>
            <header className="hs-drawer-head">
              <div className="hs-drawer-title">
                <span className="eyebrow">{groupLabel(openDef)}</span>
                <h3>{openDef.title}</h3>
                <span className="hs-muted">
                  数据截至 {formatClock(openCard.freshness)}
                  {openCard.count !== null && openDef.module_key !== null ? ` · 待处理 ${openCard.count}` : ""}
                </span>
              </div>
              <span
                className={`hs-drawer-sev hs-pill hs-pill-${openCard.severity === "ok" ? "ok" : openCard.severity === "warn" ? "warn" : "bad"}`}
              >
                {openCard.severity === "ok" ? "正常" : openCard.severity === "warn" ? "需留意" : "有异常"}
              </span>
            </header>
            <div className="hs-drawer-scroll">
              <openDef.Drawer
                card={openCard}
                notify={notify}
                onClose={closeDrawer}
                patchCard={drawerPatch}
                refetchCard={drawerRefetch}
              />
            </div>
            <footer className="hs-drawer-foot">
              <small className="hs-muted">
                {openDef.moduleHref ? "复杂操作在模块里做，浮窗只放一步能完成的。" : "外部数据只看不改。"}
              </small>
              {openDef.moduleHref ? (
                <Link className="hs-btn hs-btn-primary" href={openDef.moduleHref}>
                  去{openDef.moduleLabel}模块 →
                </Link>
              ) : null}
            </footer>
          </div>
        </OverlayModal>
      ) : null}

      {toast ? (
        <div className="hs-toast" role="status">
          {toast}
        </div>
      ) : null}
    </div>
  );
}

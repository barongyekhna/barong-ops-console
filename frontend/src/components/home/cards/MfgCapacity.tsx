"use client";

import { HomeCardShell } from "../HomeCardShell";
import type { HomeCardProps, HomeDrawerProps } from "../home-types";

type CapacityRow = {
  id: string;
  code: string;
  name: string;
  unit: string;
  max_producible: string;
  blocker_code: string | null;
  blocker_name: string | null;
  blocker_unit: string | null;
  blocker_available: string | null;
};

function products(card: HomeCardProps["card"]): CapacityRow[] {
  const value = card.extra.products;
  return Array.isArray(value) ? (value as CapacityRow[]) : [];
}

function noBom(card: HomeCardProps["card"]): Array<{ id: string; code: string; name: string }> {
  const value = card.extra.no_bom;
  return Array.isArray(value) ? (value as Array<{ id: string; code: string; name: string }>) : [];
}

function CapacityList({ list }: { list: CapacityRow[] }) {
  if (list.length === 0) return <div className="hs-empty">还没有带配件清单的成品。</div>;
  return (
    <div className="hs-capacity">
      {list.map((row) => {
        const zero = Number(row.max_producible) <= 0;
        return (
          <div className="hs-capacity-row" key={row.id}>
            <span>
              <b>{row.name}</b>
              <small>
                {row.blocker_name
                  ? `卡在 ${row.blocker_name} · 现有 ${row.blocker_available} ${row.blocker_unit ?? ""}`
                  : "配件清单为空"}
              </small>
            </span>
            <span className={zero ? "hs-cap hs-cap-zero" : "hs-cap"}>
              最多 {row.max_producible} {row.unit}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function MfgCapacityCard({ card, onOpen }: HomeCardProps) {
  const blocked = typeof card.extra.blocked_count === "number" ? card.extra.blocked_count : 0;
  return (
    <HomeCardShell
      card={card}
      onOpen={onOpen}
      tag={blocked ? `${blocked} 个成品产不了` : "按配件清单现算"}
      title="生产能力 · 缺料"
    >
      <CapacityList list={products(card).slice(0, 4)} />
    </HomeCardShell>
  );
}

export function MfgCapacityDrawer({ card }: HomeDrawerProps) {
  const missing = noBom(card);
  return (
    <div className="hs-drawer-body">
      <section className="hs-block">
        <div className="hs-block-head"><span>每个成品最多还能产多少</span><span className="hs-muted">受最短的那根配件限制</span></div>
        <CapacityList list={products(card)} />
        <p className="hs-muted">
          每件消耗的配件：现有 ÷ 单耗；按箱装的配件：箱数 × 每箱件数。取最小的那个，就是能产多少。
        </p>
      </section>
      {missing.length > 0 ? (
        <section className="hs-block">
          <div className="hs-block-head"><span>没有配件清单的成品</span></div>
          <div className="hs-empty">{missing.map((row) => row.name).join("、")}。去库存模块的成品台填配件清单，才算得出能产多少。</div>
        </section>
      ) : null}
    </div>
  );
}

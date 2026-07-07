"use client";

import {
  Apple,
  ChevronDown,
  ChevronLeft,
  Crosshair,
  Gamepad2,
  Grid3x3,
  Rocket,
  type LucideIcon,
} from "lucide-react";
import { useState, type ComponentType, type CSSProperties } from "react";

import { ShmupGame } from "@/components/arcade-shmup";
import { SnakeGame } from "@/components/arcade-snake";
import { TankGame } from "@/components/arcade-tank";
import { TetrisGame } from "@/components/arcade-tetris";

type GameId = "shmup" | "snake" | "tetris" | "tank";

const GAMES: Array<{
  id: GameId;
  name: string;
  en: string;
  desc: string;
  accent: string;
  Icon: LucideIcon;
  Game: ComponentType<{ onExit: () => void }>;
}> = [
  { id: "shmup", name: "深空空战", en: "SKY RAID", desc: "WASD 飞行 · 自动开火 · 吃道具扫屏", accent: "#39d4ff", Icon: Rocket, Game: ShmupGame },
  { id: "snake", name: "贪吃蛇", en: "SNAKE", desc: "WASD 转向 · 吃光点变长 · 别咬到自己", accent: "#4dffa1", Icon: Apple, Game: SnakeGame },
  { id: "tetris", name: "俄罗斯方块", en: "TETRIS", desc: "A/D 移动 · W 旋转 · 空格瞬降 · 消行", accent: "#a893ff", Icon: Grid3x3, Game: TetrisGame },
  { id: "tank", name: "坦克大战", en: "TANK", desc: "WASD 移动转向 · 空格开火 · 打穿砖墙", accent: "#ffb13b", Icon: Crosshair, Game: TankGame },
];

export function ConsoleArcade() {
  const [active, setActive] = useState<GameId | null>(null);
  const [collapsed, setCollapsed] = useState(true);
  const current = GAMES.find((g) => g.id === active) ?? null;

  return (
    <section className={`cc-arcade${collapsed ? " collapsed" : ""}`} aria-label="控制台游戏厅">
      <div className="cc-arcade-head">
        <div className="cc-arcade-title">
          <Gamepad2 aria-hidden="true" size={16} />
          <div>
            <span className="cc-arcade-eyebrow">忙里偷闲</span>
            <strong>{current ? current.name : "控制台游戏厅 · ARCADE"}</strong>
          </div>
        </div>
        <div className="cc-arcade-head-right">
          {current ? (
            <button className="cc-arcade-exit" onClick={() => setActive(null)} type="button">
              <ChevronLeft aria-hidden="true" size={15} />
              返回游戏厅
            </button>
          ) : null}
          <button
            className="cc-arcade-toggle"
            onClick={() => {
              setActive(null);
              setCollapsed((c) => !c);
            }}
            type="button"
          >
            {collapsed ? "展开游戏厅" : "收起"}
            <ChevronDown
              aria-hidden="true"
              className={collapsed ? "cc-arcade-chev" : "cc-arcade-chev up"}
              size={15}
            />
          </button>
        </div>
      </div>

      {collapsed ? null : current ? (
        <current.Game onExit={() => setActive(null)} />
      ) : (
        <div className="cc-arcade-menu">
          {GAMES.map((g) => (
            <button
              className="cc-game-card"
              key={g.id}
              onClick={() => setActive(g.id)}
              style={{ "--accent": g.accent } as CSSProperties}
              type="button"
            >
              <span className="cc-game-icon">
                <g.Icon aria-hidden="true" size={22} />
              </span>
              <strong>{g.name}</strong>
              <span className="cc-game-en">{g.en}</span>
              <small>{g.desc}</small>
              <span className="cc-game-play">▶ 开始</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

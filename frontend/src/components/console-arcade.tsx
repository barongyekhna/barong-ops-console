"use client";

import {
  Apple,
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
  const current = GAMES.find((g) => g.id === active) ?? null;

  return (
    <section className="cc-arcade" aria-label="控制台游戏厅">
      <div className="cc-arcade-head">
        <div className="cc-arcade-title">
          <Gamepad2 aria-hidden="true" size={16} />
          <div>
            <span className="cc-arcade-eyebrow">忙里偷闲</span>
            <strong>{current ? current.name : "控制台游戏厅 · ARCADE"}</strong>
          </div>
        </div>
        {current ? (
          <button className="cc-arcade-exit" onClick={() => setActive(null)} type="button">
            <ChevronLeft aria-hidden="true" size={15} />
            返回游戏厅
          </button>
        ) : (
          <span className="cc-arcade-hint">选一个游戏放松一下 🎮</span>
        )}
      </div>

      {current ? (
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

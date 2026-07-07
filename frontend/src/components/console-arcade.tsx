"use client";

import {
  Apple,
  Bird,
  Bomb,
  ChevronDown,
  ChevronLeft,
  CircleDot,
  Crosshair,
  Disc,
  Gamepad2,
  Gauge,
  Gem,
  Grid2x2,
  Grid3x3,
  Orbit,
  Rocket,
  type LucideIcon,
} from "lucide-react";
import { useState, type ComponentType, type CSSProperties } from "react";

import { Game2048 } from "@/components/arcade-2048";
import { AsteroidsGame } from "@/components/arcade-asteroids";
import { BreakoutGame } from "@/components/arcade-breakout";
import { FlappyGame } from "@/components/arcade-flappy";
import { Match3Game } from "@/components/arcade-match3";
import { MinesGame } from "@/components/arcade-mines";
import { PongGame } from "@/components/arcade-pong";
import { RunnerGame } from "@/components/arcade-runner";
import { ShmupGame } from "@/components/arcade-shmup";
import { SnakeGame } from "@/components/arcade-snake";
import { TankGame } from "@/components/arcade-tank";
import { TetrisGame } from "@/components/arcade-tetris";

type GameId =
  | "shmup"
  | "snake"
  | "tetris"
  | "tank"
  | "asteroids"
  | "breakout"
  | "2048"
  | "runner"
  | "match3"
  | "mines"
  | "flappy"
  | "pong";

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
  { id: "asteroids", name: "小行星", en: "ASTEROIDS", desc: "A/D 转向 · W 推进 · 空格开火 · 边缘穿越", accent: "#5b8cff", Icon: Orbit, Game: AsteroidsGame },
  { id: "breakout", name: "打砖块", en: "BREAKOUT", desc: "A/D 挡板 · 空格发射 · 接道具砸墙", accent: "#ff6b8a", Icon: CircleDot, Game: BreakoutGame },
  { id: "2048", name: "2048", en: "2048", desc: "WASD 滑动合并数字 · 凑到 2048", accent: "#ffd23b", Icon: Grid2x2, Game: Game2048 },
  { id: "runner", name: "星际跑酷", en: "RUNNER", desc: "W / 空格 起跳 · 躲陨石 · 拼最远距离", accent: "#ff9a5f", Icon: Gauge, Game: RunnerGame },
  { id: "match3", name: "宝石迷阵", en: "MATCH-3", desc: "空格选中 · 方向交换 · 凑三连消除", accent: "#ff8ac0", Icon: Gem, Game: Match3Game },
  { id: "mines", name: "扫雷", en: "MINESWEEPER", desc: "WASD 移动 · 空格挖 · F 插旗", accent: "#6ec7ff", Icon: Bomb, Game: MinesGame },
  { id: "flappy", name: "星舰穿梭", en: "FLAPPY", desc: "W / 空格 上浮 · 穿过能量门缝隙", accent: "#ffd23b", Icon: Bird, Game: FlappyGame },
  { id: "pong", name: "弹球对战", en: "PONG", desc: "W/S 球拍 · 对战 AI · 先到 7 分", accent: "#4dffa1", Icon: Disc, Game: PongGame },
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

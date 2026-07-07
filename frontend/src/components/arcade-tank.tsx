"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

// 坦克大战 —— WASD 移动 + 转向，空格开火；打敌方坦克、躲子弹、砖墙可打穿。

const W = 760;
const H = 460;
const TILE = 32;
const S = 26; // 坦克尺寸
const DIRS = [
  [0, -1],
  [1, 0],
  [0, 1],
  [-1, 0],
];

type Tank = { x: number; y: number; dir: number; cd: number; moveT: number };
type Bullet = { x: number; y: number; dir: number; owner: "p" | "e" };
type Particle = { x: number; y: number; vx: number; vy: number; life: number; color: string };
type State = {
  player: Tank;
  enemies: Tank[];
  bullets: Bullet[];
  bricks: Map<string, number>;
  parts: Particle[];
  lives: number;
  score: number;
  invuln: number;
  spawnT: number;
};

function makeBricks(): Map<string, number> {
  const m = new Map<string, number>();
  const cols = Math.floor(W / TILE);
  const rows = Math.floor(H / TILE);
  for (let i = 0; i < 46; i += 1) {
    const cx = 1 + Math.floor(Math.random() * (cols - 2));
    const cy = 3 + Math.floor(Math.random() * (rows - 6));
    m.set(`${cx},${cy}`, 1);
  }
  return m;
}
function makeState(): State {
  return {
    player: { x: W / 2, y: H - 44, dir: 0, cd: 0, moveT: 0 },
    enemies: [],
    bullets: [],
    bricks: makeBricks(),
    parts: [],
    lives: 3,
    score: 0,
    invuln: 1200,
    spawnT: 400,
  };
}
function boom(s: State, x: number, y: number, color: string, n: number) {
  for (let i = 0; i < n; i += 1) {
    const a = Math.random() * Math.PI * 2;
    const sp = 0.5 + Math.random() * 2.4;
    s.parts.push({ x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 1, color });
  }
}
function brickAt(s: State, x: number, y: number): string | null {
  const cx = Math.floor(x / TILE), cy = Math.floor(y / TILE);
  const key = `${cx},${cy}`;
  return s.bricks.has(key) ? key : null;
}
function canMove(s: State, x: number, y: number): boolean {
  if (x - S / 2 < 2 || x + S / 2 > W - 2 || y - S / 2 < 2 || y + S / 2 > H - 2) return false;
  const c0 = Math.floor((x - S / 2) / TILE), c1 = Math.floor((x + S / 2) / TILE);
  const r0 = Math.floor((y - S / 2) / TILE), r1 = Math.floor((y + S / 2) / TILE);
  for (let cx = c0; cx <= c1; cx += 1) for (let cy = r0; cy <= r1; cy += 1) if (s.bricks.has(`${cx},${cy}`)) return false;
  return true;
}

export function TankGame({ onExit }: { onExit: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stRef = useRef<State>(makeState());
  const keysRef = useRef<Set<string>>(new Set());
  const rafRef = useRef<number | null>(null);
  const lastRef = useRef(0);
  const runningRef = useRef(false);
  const [over, setOver] = useState(false);
  const [hud, setHud] = useState({ score: 0, lives: 3 });

  const fire = useCallback((s: State, t: Tank, owner: "p" | "e") => {
    const [dx, dy] = DIRS[t.dir];
    s.bullets.push({ x: t.x + dx * (S / 2 + 2), y: t.y + dy * (S / 2 + 2), dir: t.dir, owner });
  }, []);

  const step = useCallback((ts: number) => {
    if (!runningRef.current) return;
    const s = stRef.current;
    const ctx = canvasRef.current?.getContext("2d");
    const dtMs = Math.min(48, ts - (lastRef.current || ts));
    lastRef.current = ts;
    const dt = dtMs / 16.6667;
    const k = keysRef.current;

    // 玩家移动 / 转向
    let mvDir = -1;
    if (k.has("w") || k.has("arrowup")) mvDir = 0;
    else if (k.has("d") || k.has("arrowright")) mvDir = 1;
    else if (k.has("s") || k.has("arrowdown")) mvDir = 2;
    else if (k.has("a") || k.has("arrowleft")) mvDir = 3;
    if (mvDir >= 0) {
      s.player.dir = mvDir;
      const [dx, dy] = DIRS[mvDir];
      const nx = s.player.x + dx * 2.1 * dt, ny = s.player.y + dy * 2.1 * dt;
      if (canMove(s, nx, ny)) { s.player.x = nx; s.player.y = ny; }
    }
    s.player.cd -= dtMs;
    if (k.has(" ") && s.player.cd <= 0) { fire(s, s.player, "p"); s.player.cd = 340; }

    // 敌人生成
    s.spawnT -= dtMs;
    if (s.spawnT <= 0 && s.enemies.length < 4) {
      s.spawnT = 2200;
      const spots = [60, W / 2, W - 60];
      s.enemies.push({ x: spots[Math.floor(Math.random() * spots.length)], y: 40, dir: 2, cd: 800 + Math.random() * 800, moveT: 0 });
    }

    // 敌人 AI
    for (const e of s.enemies) {
      e.moveT -= dtMs;
      if (e.moveT <= 0) {
        e.moveT = 500 + Math.random() * 900;
        // 偏向朝玩家
        if (Math.random() < 0.5) e.dir = Math.abs(s.player.x - e.x) > Math.abs(s.player.y - e.y) ? (s.player.x > e.x ? 1 : 3) : (s.player.y > e.y ? 2 : 0);
        else e.dir = Math.floor(Math.random() * 4);
      }
      const [dx, dy] = DIRS[e.dir];
      const nx = e.x + dx * 1.4 * dt, ny = e.y + dy * 1.4 * dt;
      if (canMove(s, nx, ny)) { e.x = nx; e.y = ny; } else e.moveT = 0;
      e.cd -= dtMs;
      if (e.cd <= 0) { e.cd = 1200 + Math.random() * 900; fire(s, e, "e"); }
    }

    // 子弹
    s.bullets = s.bullets.filter((b) => {
      const [dx, dy] = DIRS[b.dir];
      b.x += dx * 6 * dt; b.y += dy * 6 * dt;
      if (b.x < 0 || b.x > W || b.y < 0 || b.y > H) return false;
      const bk = brickAt(s, b.x, b.y);
      if (bk) { s.bricks.delete(bk); boom(s, b.x, b.y, "#c79a5b", 5); return false; }
      return true;
    });

    if (s.invuln > 0) s.invuln -= dtMs;
    const hitPlayer = () => {
      if (s.invuln > 0) return;
      s.lives -= 1; s.invuln = 1500; boom(s, s.player.x, s.player.y, "#ff6b8a", 20);
      if (s.lives <= 0) { runningRef.current = false; setOver(true); }
    };

    // 碰撞
    s.bullets = s.bullets.filter((b) => {
      if (b.owner === "p") {
        for (const e of s.enemies) if (Math.abs(b.x - e.x) < S / 2 && Math.abs(b.y - e.y) < S / 2) {
          e.cd = -99999; e.moveT = -1; e.dir = -1; boom(s, e.x, e.y, "#ffb13b", 14); s.score += 20; s.enemies = s.enemies.filter((x) => x !== e); setHud({ score: s.score, lives: s.lives }); return false;
        }
      } else if (Math.abs(b.x - s.player.x) < S / 2 && Math.abs(b.y - s.player.y) < S / 2) { hitPlayer(); return false; }
      return true;
    });
    for (const e of s.enemies) if (Math.abs(e.x - s.player.x) < S && Math.abs(e.y - s.player.y) < S) { boom(s, e.x, e.y, "#ffb13b", 10); s.enemies = s.enemies.filter((x) => x !== e); hitPlayer(); }

    s.parts = s.parts.filter((p) => { p.x += p.vx * dt; p.y += p.vy * dt; p.vx *= 0.92; p.vy *= 0.92; p.life -= dt * 0.05; return p.life > 0; });

    // 绘制
    if (ctx) {
      ctx.fillStyle = "#06090f"; ctx.fillRect(0, 0, W, H);
      ctx.strokeStyle = "rgb(120 200 255 / 4%)"; ctx.lineWidth = 1;
      for (let x = 0; x <= W; x += TILE) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
      for (let y = 0; y <= H; y += TILE) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
      s.bricks.forEach((_v, key) => {
        const [cx, cy] = key.split(",").map(Number);
        ctx.fillStyle = "#7a5a34"; ctx.fillRect(cx * TILE + 2, cy * TILE + 2, TILE - 4, TILE - 4);
        ctx.fillStyle = "rgb(0 0 0 / 25%)";
        ctx.fillRect(cx * TILE + 2, cy * TILE + TILE / 2 - 1, TILE - 4, 2);
        ctx.fillRect(cx * TILE + TILE / 2 - 1, cy * TILE + 2, 2, TILE - 4);
      });
      const drawTank = (t: Tank, color: string) => {
        ctx.save(); ctx.translate(t.x, t.y);
        ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 8;
        ctx.fillRect(-S / 2, -S / 2, S, S);
        ctx.shadowBlur = 0;
        ctx.fillStyle = "#04070e"; ctx.fillRect(-S / 2 + 3, -S / 2 + 3, S - 6, S - 6);
        ctx.fillStyle = color; ctx.beginPath(); ctx.arc(0, 0, 6, 0, Math.PI * 2); ctx.fill();
        const [dx, dy] = DIRS[t.dir < 0 ? 0 : t.dir];
        ctx.fillRect(dx * 4 - 2 + dx * 8, dy * 4 - 2 + dy * 8, dx !== 0 ? 12 : 4, dy !== 0 ? 12 : 4);
        ctx.restore();
      };
      const blink = s.invuln > 0 && Math.floor(ts / 90) % 2 === 0;
      for (const e of s.enemies) drawTank(e, "#ffb13b");
      if (!blink) drawTank(s.player, "#39d4ff");
      for (const b of s.bullets) { ctx.fillStyle = b.owner === "p" ? "#8ef0ff" : "#ff9a5f"; ctx.beginPath(); ctx.arc(b.x, b.y, 3.4, 0, Math.PI * 2); ctx.fill(); }
      for (const p of s.parts) { ctx.globalAlpha = Math.max(0, p.life); ctx.fillStyle = p.color; ctx.fillRect(p.x - 1.5, p.y - 1.5, 3, 3); }
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#7d95ae"; ctx.font = "700 12px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.textBaseline = "top";
      ctx.fillText(`SCORE ${s.score}`, 12, 10);
      ctx.textAlign = "right"; ctx.fillStyle = "#39d4ff";
      ctx.fillText("◆ ".repeat(Math.max(0, s.lives)).trim(), W - 12, 10);
    }
    rafRef.current = requestAnimationFrame(step);
  }, [fire]);

  const start = useCallback(() => {
    stRef.current = makeState();
    setHud({ score: 0, lives: 3 }); setOver(false);
    runningRef.current = true; lastRef.current = 0;
    rafRef.current = requestAnimationFrame(step);
  }, [step]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (!runningRef.current) return;
      const key = e.key.toLowerCase();
      if (["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright", " "].includes(key)) {
        keysRef.current.add(key);
        if (key.startsWith("arrow") || key === " ") e.preventDefault();
      }
    };
    const up = (e: KeyboardEvent) => keysRef.current.delete(e.key.toLowerCase());
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    start();
    return () => {
      runningRef.current = false;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [start]);

  return (
    <div className="cc-arcade-stage">
      <canvas className="cc-arcade-canvas" height={H} ref={canvasRef} width={W} />
      <div className="cc-arcade-hudbar">
        <span>得分 {hud.score}</span>
        <span>生命 {hud.lives}</span>
        <span>空格开火</span>
      </div>
      {over ? (
        <div className="cc-arcade-overlay">
          <strong className="cc-arcade-big">阵亡</strong>
          <span>本局得分 {hud.score}</span>
          <div className="cc-arcade-actions">
            <button className="cc-arcade-btn" onClick={start} type="button"><RotateCcw aria-hidden="true" size={16} />再来一局</button>
            <button className="cc-arcade-btn ghost" onClick={onExit} type="button"><LogOut aria-hidden="true" size={16} />返回游戏厅</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

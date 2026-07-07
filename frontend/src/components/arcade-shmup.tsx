"use client";

import { RotateCcw, LogOut } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

// 深空空战 —— 纵版飞行射击（雷电风格）。WASD 控制、自动开火、吃道具。

const W = 800;
const H = 460;

type Bullet = { x: number; y: number; vx: number; vy: number };
type Enemy = { x: number; y: number; vx: number; vy: number; hp: number; r: number; cd: number; kind: 0 | 1 };
type Power = { x: number; y: number; vy: number; kind: "lane" | "rapid" | "heal" };
type Particle = { x: number; y: number; vx: number; vy: number; life: number; color: string };
type Game = {
  px: number; py: number; lives: number; score: number; lanes: number;
  fireGap: number; fireTimer: number; spawnTimer: number; spawnGap: number; invuln: number;
  bullets: Bullet[]; ebullets: Bullet[]; enemies: Enemy[]; powers: Power[]; parts: Particle[];
  stars: { x: number; y: number; z: number }[]; elapsed: number;
};

const POWER_LABEL: Record<Power["kind"], string> = { lane: "≡", rapid: "»", heal: "+" };
const POWER_COLOR: Record<Power["kind"], string> = { lane: "#39d4ff", rapid: "#4dffa1", heal: "#ff6b8a" };

function makeGame(): Game {
  return {
    px: W / 2, py: H - 60, lives: 3, score: 0, lanes: 1,
    fireGap: 260, fireTimer: 0, spawnTimer: 600, spawnGap: 1100, invuln: 1200,
    bullets: [], ebullets: [], enemies: [], powers: [], parts: [],
    stars: Array.from({ length: 70 }, () => ({ x: Math.random() * W, y: Math.random() * H, z: 0.3 + Math.random() * 1.4 })),
    elapsed: 0,
  };
}

function boom(g: Game, x: number, y: number, color: string, n: number) {
  for (let i = 0; i < n; i += 1) {
    const a = Math.random() * Math.PI * 2;
    const s = 0.4 + Math.random() * 2.6;
    g.parts.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s, life: 1, color });
  }
}

export function ShmupGame({ onExit }: { onExit: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const gameRef = useRef<Game>(makeGame());
  const keysRef = useRef<Set<string>>(new Set());
  const rafRef = useRef<number | null>(null);
  const lastRef = useRef(0);
  const runningRef = useRef(false);
  const [over, setOver] = useState(false);
  const [hud, setHud] = useState({ score: 0, lives: 3, lanes: 1 });

  const step = useCallback((ts: number) => {
    if (!runningRef.current) return;
    const g = gameRef.current;
    const ctx = canvasRef.current?.getContext("2d");
    const dtMs = Math.min(48, ts - (lastRef.current || ts));
    lastRef.current = ts;
    const dt = dtMs / 16.6667;
    g.elapsed += dtMs;
    const diff = 1 + g.elapsed / 42000;
    const k = keysRef.current;
    const spd = 4.6 * dt;
    if (k.has("a") || k.has("arrowleft")) g.px -= spd;
    if (k.has("d") || k.has("arrowright")) g.px += spd;
    if (k.has("w") || k.has("arrowup")) g.py -= spd;
    if (k.has("s") || k.has("arrowdown")) g.py += spd;
    g.px = Math.max(18, Math.min(W - 18, g.px));
    g.py = Math.max(40, Math.min(H - 24, g.py));

    g.fireTimer -= dtMs;
    if (g.fireTimer <= 0) {
      g.fireTimer = g.fireGap;
      for (let i = 0; i < g.lanes; i += 1) {
        const spread = (i - (g.lanes - 1) / 2) * 0.16;
        g.bullets.push({ x: g.px, y: g.py - 18, vx: spread * 6, vy: -8.4 });
      }
    }
    g.spawnTimer -= dtMs;
    if (g.spawnTimer <= 0) {
      g.spawnTimer = Math.max(320, g.spawnGap / diff);
      const elite = Math.random() < 0.22 + g.elapsed / 240000;
      g.enemies.push({ x: 30 + Math.random() * (W - 60), y: -24, vx: (Math.random() - 0.5) * 1.2, vy: (1.1 + Math.random() * 0.9) * diff, hp: elite ? 3 : 1, r: elite ? 18 : 14, cd: 900 + Math.random() * 900, kind: elite ? 1 : 0 });
    }
    g.bullets = g.bullets.filter((b) => { b.x += b.vx * dt; b.y += b.vy * dt; return b.y > -12 && b.x > -12 && b.x < W + 12; });
    g.enemies = g.enemies.filter((e) => {
      e.x += e.vx * dt; e.y += e.vy * dt;
      if (e.x < 20 || e.x > W - 20) e.vx *= -1;
      if (e.kind === 1 && e.y > 0 && e.y < H - 120) {
        e.cd -= dtMs;
        if (e.cd <= 0) {
          e.cd = 1100 + Math.random() * 700;
          const dx = g.px - e.x, dy = g.py - e.y, d = Math.hypot(dx, dy) || 1;
          g.ebullets.push({ x: e.x, y: e.y + 10, vx: (dx / d) * 3.4, vy: (dy / d) * 3.4 });
        }
      }
      return e.y < H + 30;
    });
    g.ebullets = g.ebullets.filter((b) => { b.x += b.vx * dt; b.y += b.vy * dt; return b.y < H + 12 && b.y > -12 && b.x > -12 && b.x < W + 12; });
    g.powers = g.powers.filter((p) => { p.y += p.vy * dt; return p.y < H + 20; });

    for (const b of g.bullets) {
      for (const e of g.enemies) {
        if (e.hp > 0 && Math.hypot(b.x - e.x, b.y - e.y) < e.r) {
          e.hp -= 1; b.y = -999; boom(g, b.x, b.y, "#39d4ff", 3);
          if (e.hp <= 0) {
            g.score += e.kind === 1 ? 30 : 10;
            boom(g, e.x, e.y, e.kind === 1 ? "#ffb13b" : "#ff8a5f", 14);
            if (Math.random() < (e.kind === 1 ? 0.55 : 0.16)) {
              const roll = Math.random();
              const kind: Power["kind"] = roll < 0.5 ? "lane" : roll < 0.82 ? "rapid" : "heal";
              g.powers.push({ x: e.x, y: e.y, vy: 1.8, kind });
            }
          }
          break;
        }
      }
    }
    g.bullets = g.bullets.filter((b) => b.y > -900);
    g.enemies = g.enemies.filter((e) => e.hp > 0);
    if (g.invuln > 0) g.invuln -= dtMs;
    const hit = () => {
      if (g.invuln > 0) return;
      g.lives -= 1; g.invuln = 1500; boom(g, g.px, g.py, "#ff6b8a", 22);
      if (g.lives <= 0) { runningRef.current = false; setOver(true); }
    };
    for (const e of g.enemies) if (Math.hypot(g.px - e.x, g.py - e.y) < e.r + 12) { boom(g, e.x, e.y, "#ffb13b", 12); e.hp = 0; hit(); }
    g.enemies = g.enemies.filter((e) => e.hp > 0);
    for (const b of g.ebullets) if (Math.hypot(g.px - b.x, g.py - b.y) < 12) { b.y = H + 999; hit(); }
    g.ebullets = g.ebullets.filter((b) => b.y < H + 100);
    g.powers = g.powers.filter((p) => {
      if (Math.hypot(g.px - p.x, g.py - p.y) < 20) {
        if (p.kind === "lane") g.lanes = Math.min(6, g.lanes + 1);
        else if (p.kind === "rapid") g.fireGap = Math.max(90, g.fireGap - 34);
        else g.lives = Math.min(6, g.lives + 1);
        boom(g, p.x, p.y, POWER_COLOR[p.kind], 10);
        return false;
      }
      return true;
    });
    g.parts = g.parts.filter((p) => { p.x += p.vx * dt; p.y += p.vy * dt; p.vx *= 0.94; p.vy *= 0.94; p.life -= dt * 0.05; return p.life > 0; });
    for (const s of g.stars) { s.y += s.z * 1.4 * dt; if (s.y > H) { s.y = 0; s.x = Math.random() * W; } }

    if (ctx) {
      const grad = ctx.createLinearGradient(0, 0, 0, H);
      grad.addColorStop(0, "#070f1a"); grad.addColorStop(1, "#04070e");
      ctx.fillStyle = grad; ctx.fillRect(0, 0, W, H);
      for (const s of g.stars) { ctx.globalAlpha = 0.3 + s.z * 0.35; ctx.fillStyle = "#9fd6ff"; ctx.fillRect(s.x, s.y, s.z, s.z * 2.2); }
      ctx.globalAlpha = 1;
      for (const e of g.enemies) {
        ctx.save(); ctx.translate(e.x, e.y);
        ctx.fillStyle = e.kind === 1 ? "#ffb13b" : "#ff8a5f"; ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 10;
        ctx.beginPath(); ctx.moveTo(0, e.r); ctx.lineTo(-e.r, -e.r * 0.7); ctx.lineTo(0, -e.r * 0.3); ctx.lineTo(e.r, -e.r * 0.7); ctx.closePath(); ctx.fill();
        ctx.restore();
      }
      ctx.shadowBlur = 0;
      ctx.fillStyle = "#8ef0ff"; ctx.shadowColor = "#39d4ff"; ctx.shadowBlur = 8;
      for (const b of g.bullets) ctx.fillRect(b.x - 1.6, b.y - 8, 3.2, 12);
      ctx.shadowBlur = 0;
      ctx.fillStyle = "#ff7d9a"; ctx.shadowColor = "#ff6b8a"; ctx.shadowBlur = 8;
      for (const b of g.ebullets) { ctx.beginPath(); ctx.arc(b.x, b.y, 3.4, 0, Math.PI * 2); ctx.fill(); }
      ctx.shadowBlur = 0;
      for (const p of g.powers) {
        ctx.save(); ctx.translate(p.x, p.y);
        ctx.fillStyle = POWER_COLOR[p.kind]; ctx.globalAlpha = 0.18; ctx.beginPath(); ctx.arc(0, 0, 13, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1;
        ctx.strokeStyle = POWER_COLOR[p.kind]; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(0, 0, 11, 0, Math.PI * 2); ctx.stroke();
        ctx.fillStyle = POWER_COLOR[p.kind]; ctx.font = "bold 15px ui-monospace, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(POWER_LABEL[p.kind], 0, 1);
        ctx.restore();
      }
      const blink = g.invuln > 0 && Math.floor(g.elapsed / 90) % 2 === 0;
      if (!blink) {
        ctx.save(); ctx.translate(g.px, g.py);
        ctx.fillStyle = "#39d4ff"; ctx.shadowColor = "#39d4ff"; ctx.shadowBlur = 14;
        ctx.beginPath(); ctx.moveTo(0, -18); ctx.lineTo(-13, 14); ctx.lineTo(0, 7); ctx.lineTo(13, 14); ctx.closePath(); ctx.fill();
        ctx.shadowBlur = 0; ctx.fillStyle = "#ffb13b"; ctx.globalAlpha = 0.6 + Math.random() * 0.4;
        ctx.beginPath(); ctx.moveTo(-5, 12); ctx.lineTo(0, 12 + 8 + Math.random() * 6); ctx.lineTo(5, 12); ctx.closePath(); ctx.fill();
        ctx.restore(); ctx.globalAlpha = 1;
      }
      for (const p of g.parts) { ctx.globalAlpha = Math.max(0, p.life); ctx.fillStyle = p.color; ctx.fillRect(p.x - 1.5, p.y - 1.5, 3, 3); }
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#7d95ae"; ctx.font = "700 12px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.textBaseline = "top";
      ctx.fillText(`SCORE ${g.score}`, 14, 12); ctx.fillText(`弹道 x${g.lanes}`, 14, 30);
      ctx.textAlign = "right"; ctx.fillStyle = "#39d4ff";
      ctx.fillText("▲ ".repeat(Math.max(0, g.lives)).trim(), W - 14, 12);
    }
    if (Math.floor(g.elapsed / 120) % 2 === 0) {
      setHud((prev) => (prev.score === g.score && prev.lives === g.lives && prev.lanes === g.lanes ? prev : { score: g.score, lives: g.lives, lanes: g.lanes }));
    }
    rafRef.current = requestAnimationFrame(step);
  }, []);

  const start = useCallback(() => {
    gameRef.current = makeGame();
    setHud({ score: 0, lives: 3, lanes: 1 });
    setOver(false);
    runningRef.current = true;
    lastRef.current = 0;
    rafRef.current = requestAnimationFrame(step);
  }, [step]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const key = e.key.toLowerCase();
      if (!runningRef.current) return;
      if (["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright"].includes(key)) {
        keysRef.current.add(key);
        if (key.startsWith("arrow")) e.preventDefault();
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
        <span>弹道 x{hud.lanes}</span>
        <span>生命 {hud.lives}</span>
      </div>
      {over ? (
        <div className="cc-arcade-overlay">
          <strong className="cc-arcade-big">任务结束</strong>
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

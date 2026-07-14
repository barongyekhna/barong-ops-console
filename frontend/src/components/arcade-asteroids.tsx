"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

// 小行星 —— A/D 转向，W 推进，空格开火。击碎陨石会裂开，屏幕边缘穿越。

const W = 760;
const H = 460;

type Ship = { x: number; y: number; vx: number; vy: number; a: number; inv: number; cd: number };
type Bullet = { x: number; y: number; vx: number; vy: number; life: number };
type Rock = { x: number; y: number; vx: number; vy: number; r: number; size: number; a: number; spin: number; verts: number[] };
type Particle = { x: number; y: number; vx: number; vy: number; life: number; color: string };
type State = { ship: Ship; bullets: Bullet[]; rocks: Rock[]; parts: Particle[]; lives: number; score: number; wave: number };

function makeRock(x: number, y: number, size: number): Rock {
  const n = 9;
  const verts: number[] = [];
  for (let i = 0; i < n; i += 1) verts.push(0.7 + Math.random() * 0.5);
  const sp = (0.4 + Math.random() * 0.8) * (4 - size) * 0.5;
  const dir = Math.random() * Math.PI * 2;
  return { x, y, vx: Math.cos(dir) * sp, vy: Math.sin(dir) * sp, r: size * 16, size, a: 0, spin: (Math.random() - 0.5) * 0.05, verts };
}
function spawnWave(s: State) {
  const n = 3 + s.wave;
  for (let i = 0; i < n; i += 1) {
    const edge = Math.random();
    const x = edge < 0.5 ? Math.random() * W : Math.random() < 0.5 ? 0 : W;
    const y = edge < 0.5 ? (Math.random() < 0.5 ? 0 : H) : Math.random() * H;
    s.rocks.push(makeRock(x, y, 3));
  }
}
function makeState(): State {
  const s: State = { ship: { x: W / 2, y: H / 2, vx: 0, vy: 0, a: -Math.PI / 2, inv: 1500, cd: 0 }, bullets: [], rocks: [], parts: [], lives: 3, score: 0, wave: 1 };
  spawnWave(s);
  return s;
}
function wrap(p: { x: number; y: number }) {
  if (p.x < 0) p.x += W; else if (p.x > W) p.x -= W;
  if (p.y < 0) p.y += H; else if (p.y > H) p.y -= H;
}
function boom(s: State, x: number, y: number, color: string, n: number) {
  for (let i = 0; i < n; i += 1) { const a = Math.random() * Math.PI * 2; const sp = 0.5 + Math.random() * 2.4; s.parts.push({ x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 1, color }); }
}

export function AsteroidsGame({
  onExit,
  onScoreChange,
}: {
  onExit: () => void;
  onScoreChange?: (score: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stRef = useRef<State>(makeState());
  const keysRef = useRef<Set<string>>(new Set());
  const rafRef = useRef<number | null>(null);
  const lastRef = useRef(0);
  const runningRef = useRef(false);
  const [over, setOver] = useState(false);
  const [hud, setHud] = useState({ score: 0, lives: 3 });

  const step = useCallback((ts: number) => {
    if (!runningRef.current) return;
    const s = stRef.current;
    const ctx = canvasRef.current?.getContext("2d");
    const dtMs = Math.min(48, ts - (lastRef.current || ts));
    lastRef.current = ts;
    const dt = dtMs / 16.6667;
    const k = keysRef.current;
    const sh = s.ship;
    if (k.has("a") || k.has("arrowleft")) sh.a -= 0.075 * dt;
    if (k.has("d") || k.has("arrowright")) sh.a += 0.075 * dt;
    if (k.has("w") || k.has("arrowup")) { sh.vx += Math.cos(sh.a) * 0.16 * dt; sh.vy += Math.sin(sh.a) * 0.16 * dt; boom(s, sh.x - Math.cos(sh.a) * 12, sh.y - Math.sin(sh.a) * 12, "#ffb13b", 1); }
    sh.vx *= 0.992; sh.vy *= 0.992;
    sh.x += sh.vx * dt; sh.y += sh.vy * dt; wrap(sh);
    if (sh.inv > 0) sh.inv -= dtMs;
    sh.cd -= dtMs;
    if (k.has(" ") && sh.cd <= 0) { sh.cd = 220; s.bullets.push({ x: sh.x + Math.cos(sh.a) * 14, y: sh.y + Math.sin(sh.a) * 14, vx: Math.cos(sh.a) * 9 + sh.vx, vy: Math.sin(sh.a) * 9 + sh.vy, life: 55 }); }

    s.bullets = s.bullets.filter((b) => { b.x += b.vx * dt; b.y += b.vy * dt; wrap(b); b.life -= dt; return b.life > 0; });
    for (const r of s.rocks) { r.x += r.vx * dt; r.y += r.vy * dt; r.a += r.spin * dt; wrap(r); }

    // 子弹 vs 陨石
    for (const b of s.bullets) {
      for (const r of s.rocks) {
        if (r.size > 0 && Math.hypot(b.x - r.x, b.y - r.y) < r.r) {
          b.life = -1; r.size = -1;
          s.score += r.r > 40 ? 20 : r.r > 24 ? 50 : 100;
          setHud({ score: s.score, lives: s.lives });
          boom(s, r.x, r.y, "#ffb13b", 12);
          if (r.r > 20) { for (let i = 0; i < 2; i += 1) { const nr = makeRock(r.x, r.y, Math.max(1, Math.round(r.r / 16) - 1)); s.rocks.push(nr); } }
          break;
        }
      }
    }
    s.bullets = s.bullets.filter((b) => b.life > 0);
    s.rocks = s.rocks.filter((r) => r.size > 0);
    if (s.rocks.length === 0) { s.wave += 1; s.ship.inv = 1200; spawnWave(s); }

    // 飞船 vs 陨石
    if (sh.inv <= 0) {
      for (const r of s.rocks) {
        if (Math.hypot(sh.x - r.x, sh.y - r.y) < r.r + 10) {
          s.lives -= 1; sh.inv = 1800; boom(s, sh.x, sh.y, "#ff6b8a", 26);
          sh.x = W / 2; sh.y = H / 2; sh.vx = 0; sh.vy = 0;
          setHud({ score: s.score, lives: s.lives });
          if (s.lives <= 0) { runningRef.current = false; setOver(true); }
          break;
        }
      }
    }
    s.parts = s.parts.filter((p) => { p.x += p.vx * dt; p.y += p.vy * dt; p.life -= dt * 0.05; return p.life > 0; });

    if (ctx) {
      ctx.fillStyle = "#04070e"; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#9fd6ff"; for (let i = 0; i < 46; i += 1) { const sx = (i * 137) % W; const sy = (i * 251) % H; ctx.globalAlpha = 0.3 + ((i * 53) % 40) / 80; ctx.fillRect(sx, sy, 1.4, 1.4); } ctx.globalAlpha = 1;
      ctx.strokeStyle = "#cfe6ff"; ctx.lineWidth = 1.5;
      for (const r of s.rocks) {
        ctx.save(); ctx.translate(r.x, r.y); ctx.rotate(r.a); ctx.beginPath();
        r.verts.forEach((rv, i) => { const ang = (i / r.verts.length) * Math.PI * 2; const px = Math.cos(ang) * r.r * rv; const py = Math.sin(ang) * r.r * rv; if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py); });
        ctx.closePath(); ctx.stroke(); ctx.restore();
      }
      ctx.fillStyle = "#8ef0ff"; ctx.shadowColor = "#39d4ff"; ctx.shadowBlur = 8;
      for (const b of s.bullets) { ctx.beginPath(); ctx.arc(b.x, b.y, 2.6, 0, Math.PI * 2); ctx.fill(); }
      ctx.shadowBlur = 0;
      const blink = sh.inv > 0 && Math.floor(ts / 90) % 2 === 0;
      if (!blink) {
        ctx.save(); ctx.translate(sh.x, sh.y); ctx.rotate(sh.a);
        ctx.strokeStyle = "#39d4ff"; ctx.fillStyle = "rgb(57 212 255 / 18%)"; ctx.lineWidth = 2; ctx.shadowColor = "#39d4ff"; ctx.shadowBlur = 10;
        ctx.beginPath(); ctx.moveTo(15, 0); ctx.lineTo(-10, -9); ctx.lineTo(-5, 0); ctx.lineTo(-10, 9); ctx.closePath(); ctx.fill(); ctx.stroke();
        ctx.shadowBlur = 0; ctx.restore();
      }
      for (const p of s.parts) { ctx.globalAlpha = Math.max(0, p.life); ctx.fillStyle = p.color; ctx.fillRect(p.x - 1.5, p.y - 1.5, 3, 3); } ctx.globalAlpha = 1;
      ctx.fillStyle = "#7d95ae"; ctx.font = "700 12px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.textBaseline = "top";
      ctx.fillText(`SCORE ${s.score}`, 14, 12); ctx.fillText(`WAVE ${s.wave}`, 14, 30);
      ctx.textAlign = "right"; ctx.fillStyle = "#39d4ff"; ctx.fillText("▲ ".repeat(Math.max(0, s.lives)).trim(), W - 14, 12);
    }
    if (Math.floor(ts / 200) % 2 === 0) setHud((prev) => (prev.score === s.score && prev.lives === s.lives ? prev : { score: s.score, lives: s.lives }));
    rafRef.current = requestAnimationFrame(step);
  }, []);

  const start = useCallback(() => {
    stRef.current = makeState(); setHud({ score: 0, lives: 3 }); setOver(false);
    runningRef.current = true; lastRef.current = 0; rafRef.current = requestAnimationFrame(step);
  }, [step]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => { if (!runningRef.current) return; const key = e.key.toLowerCase(); if (["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright", " "].includes(key)) { keysRef.current.add(key); if (key.startsWith("arrow") || key === " ") e.preventDefault(); } };
    const up = (e: KeyboardEvent) => keysRef.current.delete(e.key.toLowerCase());
    window.addEventListener("keydown", down); window.addEventListener("keyup", up); start();
    return () => { runningRef.current = false; if (rafRef.current !== null) cancelAnimationFrame(rafRef.current); window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [start]);

  useEffect(() => {
    onScoreChange?.(hud.score);
  }, [hud.score, onScoreChange]);

  return (
    <div className="cc-arcade-stage">
      <canvas className="cc-arcade-canvas" height={H} ref={canvasRef} width={W} />
      <div className="cc-arcade-hudbar"><span>得分 {hud.score}</span><span>生命 {hud.lives}</span><span>A/D 转向 · W 推进 · 空格开火</span></div>
      {over ? (
        <div className="cc-arcade-overlay">
          <strong className="cc-arcade-big">飞船损毁</strong>
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

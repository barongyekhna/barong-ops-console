"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

// 打砖块 —— A/D 移动挡板，空格发射能量球；砸碎砖墙、接道具（多球/加宽/减速）。

const W = 760;
const H = 460;
const COLS = 11;
const ROWS = 6;
const MARGIN = 24;
const GAP = 6;
const BW = (W - MARGIN * 2 - GAP * (COLS - 1)) / COLS;
const BH = 20;
const TOP = 52;
const ROW_COLORS = ["#ff6b8a", "#ffb13b", "#ffd23b", "#4dffa1", "#39d4ff", "#a893ff"];

type Ball = { x: number; y: number; vx: number; vy: number };
type Brick = { x: number; y: number; color: string; alive: boolean };
type Power = { x: number; y: number; kind: "multi" | "wide" | "slow" };
type State = { pad: number; padW: number; wideT: number; balls: Ball[]; bricks: Brick[]; powers: Power[]; lives: number; score: number; level: number; launched: boolean };

const PLABEL: Record<Power["kind"], string> = { multi: "●", wide: "↔", slow: "≈" };
const PCOLOR: Record<Power["kind"], string> = { multi: "#39d4ff", wide: "#4dffa1", slow: "#ffb13b" };

function makeBricks(level: number): Brick[] {
  const arr: Brick[] = [];
  const rows = Math.min(ROWS, 3 + level);
  for (let r = 0; r < rows; r += 1) for (let c = 0; c < COLS; c += 1) {
    arr.push({ x: MARGIN + c * (BW + GAP), y: TOP + r * (BH + GAP), color: ROW_COLORS[r % ROW_COLORS.length], alive: true });
  }
  return arr;
}
function newBall(pad: number, spd: number): Ball { return { x: pad, y: H - 40, vx: (Math.random() - 0.5) * 3, vy: -spd }; }
function makeState(level = 1): State {
  const pad = W / 2;
  return { pad, padW: 96, wideT: 0, balls: [newBall(pad, 5 + level * 0.4)], bricks: makeBricks(level), powers: [], lives: 3, score: 0, level, launched: false };
}

export function BreakoutGame({ onExit }: { onExit: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stRef = useRef<State>(makeState());
  const keysRef = useRef<Set<string>>(new Set());
  const rafRef = useRef<number | null>(null);
  const lastRef = useRef(0);
  const runningRef = useRef(false);
  const [over, setOver] = useState(false);
  const [hud, setHud] = useState({ score: 0, lives: 3, level: 1 });

  const step = useCallback((ts: number) => {
    if (!runningRef.current) return;
    const s = stRef.current;
    const ctx = canvasRef.current?.getContext("2d");
    const dtMs = Math.min(48, ts - (lastRef.current || ts));
    lastRef.current = ts;
    const dt = dtMs / 16.6667;
    const k = keysRef.current;
    const R = 7;

    if (k.has("a") || k.has("arrowleft")) s.pad -= 8 * dt;
    if (k.has("d") || k.has("arrowright")) s.pad += 8 * dt;
    s.pad = Math.max(s.padW / 2, Math.min(W - s.padW / 2, s.pad));
    if (s.wideT > 0) { s.wideT -= dtMs; if (s.wideT <= 0) s.padW = 96; }
    if (!s.launched) { s.balls[0].x = s.pad; s.balls[0].y = H - 40; if (k.has(" ")) s.launched = true; }

    if (s.launched) {
      for (const b of s.balls) {
        b.x += b.vx * dt; b.y += b.vy * dt;
        if (b.x < R) { b.x = R; b.vx = Math.abs(b.vx); }
        if (b.x > W - R) { b.x = W - R; b.vx = -Math.abs(b.vx); }
        if (b.y < R) { b.y = R; b.vy = Math.abs(b.vy); }
        // 挡板
        const padY = H - 26;
        if (b.vy > 0 && b.y + R >= padY && b.y < padY + 12 && b.x > s.pad - s.padW / 2 - R && b.x < s.pad + s.padW / 2 + R) {
          const rel = Math.max(-1, Math.min(1, (b.x - s.pad) / (s.padW / 2)));
          const spd = Math.min(9.5, Math.hypot(b.vx, b.vy) + 0.03);
          const ang = rel * 1.05;
          b.vx = Math.sin(ang) * spd; b.vy = -Math.cos(ang) * spd; b.y = padY - R;
        }
        // 砖块
        for (const br of s.bricks) {
          if (!br.alive) continue;
          if (b.x > br.x - R && b.x < br.x + BW + R && b.y > br.y - R && b.y < br.y + BH + R) {
            const ox = Math.min(b.x - (br.x - R), br.x + BW + R - b.x);
            const oy = Math.min(b.y - (br.y - R), br.y + BH + R - b.y);
            if (ox < oy) b.vx = -b.vx; else b.vy = -b.vy;
            br.alive = false; s.score += 10;
            if (Math.random() < 0.13) { const roll = Math.random(); const kind: Power["kind"] = roll < 0.4 ? "multi" : roll < 0.72 ? "wide" : "slow"; s.powers.push({ x: br.x + BW / 2, y: br.y + BH, kind }); }
            break;
          }
        }
      }
      s.balls = s.balls.filter((b) => b.y < H + 20);
      if (s.balls.length === 0) {
        s.lives -= 1; setHud({ score: s.score, lives: s.lives, level: s.level });
        if (s.lives <= 0) { runningRef.current = false; setOver(true); }
        else { s.balls = [newBall(s.pad, 5 + s.level * 0.4)]; s.launched = false; }
      }
      if (s.bricks.every((br) => !br.alive)) { s.level += 1; s.bricks = makeBricks(s.level); s.balls = [newBall(s.pad, 5 + s.level * 0.4)]; s.launched = false; s.powers = []; setHud({ score: s.score, lives: s.lives, level: s.level }); }
    }

    // 道具下落 + 拾取
    s.powers = s.powers.filter((p) => {
      p.y += 2.4 * dt;
      if (p.y > H - 30 && Math.abs(p.x - s.pad) < s.padW / 2 + 8) {
        if (p.kind === "multi") { const cur = [...s.balls]; for (const b of cur) { s.balls.push({ x: b.x, y: b.y, vx: b.vx + 2, vy: b.vy }); s.balls.push({ x: b.x, y: b.y, vx: b.vx - 2, vy: b.vy }); } }
        else if (p.kind === "wide") { s.padW = 150; s.wideT = 9000; }
        else for (const b of s.balls) { b.vx *= 0.72; b.vy *= 0.72; }
        s.score += 5;
        return false;
      }
      return p.y < H + 10;
    });

    if (ctx) {
      ctx.fillStyle = "#05090f"; ctx.fillRect(0, 0, W, H);
      for (const br of s.bricks) { if (!br.alive) continue; ctx.fillStyle = br.color; ctx.fillRect(br.x, br.y, BW, BH); ctx.fillStyle = "rgb(255 255 255 / 16%)"; ctx.fillRect(br.x, br.y, BW, 3); }
      // 挡板
      ctx.fillStyle = "#39d4ff"; ctx.shadowColor = "#39d4ff"; ctx.shadowBlur = 12;
      ctx.fillRect(s.pad - s.padW / 2, H - 26, s.padW, 10); ctx.shadowBlur = 0;
      // 球
      ctx.fillStyle = "#eafaff"; ctx.shadowColor = "#8ef0ff"; ctx.shadowBlur = 10;
      for (const b of s.balls) { ctx.beginPath(); ctx.arc(b.x, b.y, R, 0, Math.PI * 2); ctx.fill(); } ctx.shadowBlur = 0;
      // 道具
      for (const p of s.powers) { ctx.fillStyle = PCOLOR[p.kind]; ctx.globalAlpha = 0.2; ctx.beginPath(); ctx.arc(p.x, p.y, 11, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1; ctx.strokeStyle = PCOLOR[p.kind]; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(p.x, p.y, 10, 0, Math.PI * 2); ctx.stroke(); ctx.fillStyle = PCOLOR[p.kind]; ctx.font = "bold 13px ui-monospace, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(PLABEL[p.kind], p.x, p.y + 1); }
      if (!s.launched) { ctx.fillStyle = "#7d95ae"; ctx.font = "600 13px ui-monospace, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("空格发射", s.pad, H - 52); }
      ctx.fillStyle = "#7d95ae"; ctx.font = "700 12px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.textBaseline = "top";
      ctx.fillText(`SCORE ${s.score}`, 14, 12); ctx.fillText(`LV ${s.level}`, 14, 30);
      ctx.textAlign = "right"; ctx.fillStyle = "#39d4ff"; ctx.fillText("● ".repeat(Math.max(0, s.lives)).trim(), W - 14, 12);
    }
    rafRef.current = requestAnimationFrame(step);
  }, []);

  const start = useCallback(() => { stRef.current = makeState(); setHud({ score: 0, lives: 3, level: 1 }); setOver(false); runningRef.current = true; lastRef.current = 0; rafRef.current = requestAnimationFrame(step); }, [step]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => { if (!runningRef.current) return; const key = e.key.toLowerCase(); if (["a", "d", "arrowleft", "arrowright", " "].includes(key)) { keysRef.current.add(key); if (key === " " || key.startsWith("arrow")) e.preventDefault(); } };
    const up = (e: KeyboardEvent) => keysRef.current.delete(e.key.toLowerCase());
    window.addEventListener("keydown", down); window.addEventListener("keyup", up); start();
    return () => { runningRef.current = false; if (rafRef.current !== null) cancelAnimationFrame(rafRef.current); window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [start]);

  return (
    <div className="cc-arcade-stage">
      <canvas className="cc-arcade-canvas" height={H} ref={canvasRef} width={W} />
      <div className="cc-arcade-hudbar"><span>得分 {hud.score}</span><span>等级 {hud.level}</span><span>生命 {hud.lives}</span><span>A/D + 空格</span></div>
      {over ? (
        <div className="cc-arcade-overlay">
          <strong className="cc-arcade-big">游戏结束</strong>
          <span>得分 {hud.score} · 等级 {hud.level}</span>
          <div className="cc-arcade-actions">
            <button className="cc-arcade-btn" onClick={start} type="button"><RotateCcw aria-hidden="true" size={16} />再来一局</button>
            <button className="cc-arcade-btn ghost" onClick={onExit} type="button"><LogOut aria-hidden="true" size={16} />返回游戏厅</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

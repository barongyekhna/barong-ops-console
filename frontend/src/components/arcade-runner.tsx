"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

// 星际跑酷 —— W / 空格 起跳，躲开迎面而来的陨石，速度越来越快，拼最远距离。

const W = 760;
const H = 460;
const GROUND = H - 64;
const SHIP_W = 30;
const SHIP_H = 26;
const SHIP_X = 120;

type Rock = { x: number; y: number; w: number; h: number };
type State = { y: number; vy: number; onGround: boolean; rocks: Rock[]; stars: { x: number; y: number; z: number }[]; dist: number; speed: number; nextGap: number };

function makeState(): State {
  return {
    y: GROUND - SHIP_H, vy: 0, onGround: true,
    rocks: [], stars: Array.from({ length: 50 }, () => ({ x: Math.random() * W, y: Math.random() * (GROUND - 20), z: 0.4 + Math.random() * 1.6 })),
    dist: 0, speed: 5, nextGap: 320,
  };
}

export function RunnerGame({ onExit }: { onExit: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stRef = useRef<State>(makeState());
  const rafRef = useRef<number | null>(null);
  const lastRef = useRef(0);
  const runningRef = useRef(false);
  const [over, setOver] = useState(false);
  const [score, setScore] = useState(0);
  const [best, setBest] = useState(0);

  const jump = useCallback(() => { const s = stRef.current; if (runningRef.current && s.onGround) { s.vy = -15; s.onGround = false; } }, []);

  const step = useCallback((ts: number) => {
    if (!runningRef.current) return;
    const s = stRef.current;
    const ctx = canvasRef.current?.getContext("2d");
    const dtMs = Math.min(48, ts - (lastRef.current || ts));
    lastRef.current = ts;
    const dt = dtMs / 16.6667;

    s.speed = 5 + s.dist / 900;
    s.dist += s.speed * dt;
    // 物理
    s.vy += 1.0 * dt;
    s.y += s.vy * dt;
    const groundedY = GROUND - SHIP_H;
    if (s.y >= groundedY) { s.y = groundedY; s.vy = 0; s.onGround = true; }
    // 障碍
    s.nextGap -= s.speed * dt;
    if (s.nextGap <= 0) {
      s.nextGap = 240 + Math.random() * 260;
      const h = 26 + Math.random() * 34;
      s.rocks.push({ x: W + 20, y: GROUND - h, w: 20 + Math.random() * 22, h });
    }
    s.rocks = s.rocks.filter((r) => { r.x -= s.speed * dt; return r.x + r.w > -10; });
    for (const st of s.stars) { st.x -= st.z * s.speed * 0.35 * dt; if (st.x < 0) { st.x = W; st.y = Math.random() * (GROUND - 20); } }
    // 碰撞
    for (const r of s.rocks) {
      if (SHIP_X + SHIP_W - 5 > r.x + 3 && SHIP_X + 5 < r.x + r.w - 3 && s.y + SHIP_H - 3 > r.y + 3) {
        runningRef.current = false; setOver(true); setBest((b) => Math.max(b, Math.floor(s.dist / 10)));
        break;
      }
    }

    if (ctx) {
      const grad = ctx.createLinearGradient(0, 0, 0, H); grad.addColorStop(0, "#070f1a"); grad.addColorStop(1, "#04070e");
      ctx.fillStyle = grad; ctx.fillRect(0, 0, W, H);
      for (const st of s.stars) { ctx.globalAlpha = 0.3 + st.z * 0.3; ctx.fillStyle = "#9fd6ff"; ctx.fillRect(st.x, st.y, st.z, st.z * 1.6); } ctx.globalAlpha = 1;
      // 地面
      ctx.strokeStyle = "rgb(57 212 255 / 45%)"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(0, GROUND); ctx.lineTo(W, GROUND); ctx.stroke();
      ctx.fillStyle = "rgb(57 212 255 / 5%)"; ctx.fillRect(0, GROUND, W, H - GROUND);
      // 障碍
      ctx.fillStyle = "#ffb13b"; ctx.shadowColor = "#ffb13b"; ctx.shadowBlur = 8;
      for (const r of s.rocks) { ctx.beginPath(); ctx.moveTo(r.x, r.y + r.h); ctx.lineTo(r.x + r.w * 0.5, r.y); ctx.lineTo(r.x + r.w, r.y + r.h); ctx.closePath(); ctx.fill(); }
      ctx.shadowBlur = 0;
      // 战机
      ctx.save(); ctx.translate(SHIP_X, s.y);
      ctx.fillStyle = "#39d4ff"; ctx.shadowColor = "#39d4ff"; ctx.shadowBlur = 12;
      ctx.beginPath(); ctx.moveTo(SHIP_W, SHIP_H / 2); ctx.lineTo(0, 0); ctx.lineTo(6, SHIP_H / 2); ctx.lineTo(0, SHIP_H); ctx.closePath(); ctx.fill();
      ctx.shadowBlur = 0;
      if (!s.onGround) { ctx.fillStyle = "#ffb13b"; ctx.globalAlpha = 0.7; ctx.beginPath(); ctx.moveTo(0, SHIP_H / 2 - 4); ctx.lineTo(-8 - Math.random() * 6, SHIP_H / 2); ctx.lineTo(0, SHIP_H / 2 + 4); ctx.closePath(); ctx.fill(); ctx.globalAlpha = 1; }
      ctx.restore();
      // HUD
      ctx.fillStyle = "#7d95ae"; ctx.font = "700 12px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.textBaseline = "top";
      ctx.fillText(`距离 ${Math.floor(s.dist / 10)}`, 14, 12);
      ctx.textAlign = "right"; ctx.fillText(`最远 ${best}`, W - 14, 12);
    }
    if (Math.floor(ts / 120) % 2 === 0) { const sc = Math.floor(s.dist / 10); setScore((prev) => (prev === sc ? prev : sc)); }
    rafRef.current = requestAnimationFrame(step);
  }, [best]);

  const start = useCallback(() => { stRef.current = makeState(); setScore(0); setOver(false); runningRef.current = true; lastRef.current = 0; rafRef.current = requestAnimationFrame(step); }, [step]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => { const key = e.key.toLowerCase(); if (key === "w" || key === " " || key === "arrowup") { e.preventDefault(); jump(); } };
    window.addEventListener("keydown", down); start();
    return () => { runningRef.current = false; if (rafRef.current !== null) cancelAnimationFrame(rafRef.current); window.removeEventListener("keydown", down); };
  }, [start, jump]);

  return (
    <div className="cc-arcade-stage">
      <canvas className="cc-arcade-canvas" height={H} ref={canvasRef} width={W} />
      <div className="cc-arcade-hudbar"><span>距离 {score}</span><span>最远 {best}</span><span>W / 空格 起跳</span></div>
      {over ? (
        <div className="cc-arcade-overlay">
          <strong className="cc-arcade-big">撞毁</strong>
          <span>本局距离 {score} · 最远 {best}</span>
          <div className="cc-arcade-actions">
            <button className="cc-arcade-btn" onClick={start} type="button"><RotateCcw aria-hidden="true" size={16} />再来一局</button>
            <button className="cc-arcade-btn ghost" onClick={onExit} type="button"><LogOut aria-hidden="true" size={16} />返回游戏厅</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

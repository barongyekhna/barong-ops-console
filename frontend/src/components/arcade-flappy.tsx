"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

// 星舰穿梭 —— W / 空格 上浮，穿过一道道能量门缝隙，别撞门也别飞出界。

const W = 760;
const H = 460;
const SHIP_X = 190;
const R = 13;
const GW = 54;
const GAP = 156;

type Gate = { x: number; gapY: number; passed: boolean };
type State = { y: number; vy: number; gates: Gate[]; stars: { x: number; y: number; z: number }[]; next: number; score: number; started: boolean };

function makeState(): State {
  return { y: H / 2, vy: 0, gates: [], stars: Array.from({ length: 46 }, () => ({ x: Math.random() * W, y: Math.random() * H, z: 0.4 + Math.random() * 1.5 })), next: 260, score: 0, started: false };
}

export function FlappyGame({
  onExit,
  onScoreChange,
}: {
  onExit: () => void;
  onScoreChange?: (score: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stRef = useRef<State>(makeState());
  const rafRef = useRef<number | null>(null);
  const lastRef = useRef(0);
  const runningRef = useRef(false);
  const [over, setOver] = useState(false);
  const [score, setScore] = useState(0);
  const [best, setBest] = useState(0);

  const flap = useCallback(() => { const s = stRef.current; if (!runningRef.current) return; s.started = true; s.vy = -7.4; }, []);

  const step = useCallback((ts: number) => {
    if (!runningRef.current) return;
    const s = stRef.current;
    const ctx = canvasRef.current?.getContext("2d");
    const dtMs = Math.min(48, ts - (lastRef.current || ts));
    lastRef.current = ts;
    const dt = dtMs / 16.6667;
    const speed = 3.4;

    if (s.started) {
      s.vy += 0.46 * dt; s.y += s.vy * dt;
      s.next -= speed * dt;
      if (s.next <= 0) { s.next = 300; s.gates.push({ x: W + 10, gapY: 90 + Math.random() * (H - 180), passed: false }); }
      s.gates = s.gates.filter((g) => { g.x -= speed * dt; if (!g.passed && g.x + GW < SHIP_X) { g.passed = true; s.score += 1; setScore(s.score); } return g.x + GW > -10; });
      // 碰撞
      if (s.y - R < 0 || s.y + R > H) { runningRef.current = false; setOver(true); setBest((bpv) => Math.max(bpv, s.score)); }
      for (const g of s.gates) {
        if (SHIP_X + R > g.x && SHIP_X - R < g.x + GW && (s.y - R < g.gapY - GAP / 2 || s.y + R > g.gapY + GAP / 2)) {
          runningRef.current = false; setOver(true); setBest((bpv) => Math.max(bpv, s.score)); break;
        }
      }
    }
    for (const st of s.stars) { st.x -= st.z * speed * 0.35 * dt; if (st.x < 0) { st.x = W; st.y = Math.random() * H; } }

    if (ctx) {
      const grad = ctx.createLinearGradient(0, 0, 0, H); grad.addColorStop(0, "#070f1a"); grad.addColorStop(1, "#04070e");
      ctx.fillStyle = grad; ctx.fillRect(0, 0, W, H);
      for (const st of s.stars) { ctx.globalAlpha = 0.3 + st.z * 0.3; ctx.fillStyle = "#9fd6ff"; ctx.fillRect(st.x, st.y, st.z, st.z * 1.6); } ctx.globalAlpha = 1;
      for (const g of s.gates) {
        ctx.fillStyle = "rgb(255 177 59 / 18%)"; ctx.strokeStyle = "#ffb13b"; ctx.lineWidth = 2;
        ctx.fillRect(g.x, 0, GW, g.gapY - GAP / 2); ctx.strokeRect(g.x, 0, GW, g.gapY - GAP / 2);
        ctx.fillRect(g.x, g.gapY + GAP / 2, GW, H - (g.gapY + GAP / 2)); ctx.strokeRect(g.x, g.gapY + GAP / 2, GW, H - (g.gapY + GAP / 2));
      }
      ctx.save(); ctx.translate(SHIP_X, s.y); ctx.rotate(Math.max(-0.5, Math.min(0.9, s.vy / 12)));
      ctx.fillStyle = "#39d4ff"; ctx.shadowColor = "#39d4ff"; ctx.shadowBlur = 12;
      ctx.beginPath(); ctx.moveTo(16, 0); ctx.lineTo(-11, -9); ctx.lineTo(-5, 0); ctx.lineTo(-11, 9); ctx.closePath(); ctx.fill();
      ctx.shadowBlur = 0; ctx.fillStyle = "#ffb13b"; ctx.globalAlpha = 0.7; ctx.beginPath(); ctx.moveTo(-5, -3); ctx.lineTo(-13 - Math.random() * 6, 0); ctx.lineTo(-5, 3); ctx.closePath(); ctx.fill(); ctx.globalAlpha = 1;
      ctx.restore();
      ctx.fillStyle = "#eafaff"; ctx.font = "800 34px ui-monospace, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.fillText(String(s.score), W / 2, 24);
      if (!s.started) { ctx.fillStyle = "#7d95ae"; ctx.font = "600 15px ui-monospace, monospace"; ctx.fillText("按 W / 空格 起飞", W / 2, H / 2 + 40); }
    }
    rafRef.current = requestAnimationFrame(step);
  }, []);

  const start = useCallback(() => { stRef.current = makeState(); setScore(0); setOver(false); runningRef.current = true; lastRef.current = 0; rafRef.current = requestAnimationFrame(step); }, [step]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => { const key = e.key.toLowerCase(); if (key === "w" || key === " " || key === "arrowup") { e.preventDefault(); flap(); } };
    window.addEventListener("keydown", down); start();
    return () => { runningRef.current = false; if (rafRef.current !== null) cancelAnimationFrame(rafRef.current); window.removeEventListener("keydown", down); };
  }, [start, flap]);

  useEffect(() => {
    onScoreChange?.(score);
  }, [onScoreChange, score]);

  return (
    <div className="cc-arcade-stage">
      <canvas className="cc-arcade-canvas" height={H} ref={canvasRef} width={W} />
      <div className="cc-arcade-hudbar"><span>穿过 {score}</span><span>最佳 {best}</span><span>W / 空格 上浮</span></div>
      {over ? (
        <div className="cc-arcade-overlay">
          <strong className="cc-arcade-big">撞门了</strong>
          <span>本局穿过 {score} 道 · 最佳 {best}</span>
          <div className="cc-arcade-actions">
            <button className="cc-arcade-btn" onClick={start} type="button"><RotateCcw aria-hidden="true" size={16} />再来一局</button>
            <button className="cc-arcade-btn ghost" onClick={onExit} type="button"><LogOut aria-hidden="true" size={16} />返回游戏厅</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

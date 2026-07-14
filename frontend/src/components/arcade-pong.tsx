"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

// 弹球 Pong —— W/S 控制左侧球拍，和舰载 AI 对打，先到 7 分获胜。

const W = 760;
const H = 460;
const PW = 12;
const PH = 82;
const WIN = 7;

type State = { py: number; ay: number; bx: number; by: number; bvx: number; bvy: number; ps: number; as: number; serve: number };

function makeState(): State {
  return { py: H / 2 - PH / 2, ay: H / 2 - PH / 2, bx: W / 2, by: H / 2, bvx: Math.random() < 0.5 ? -5.5 : 5.5, bvy: (Math.random() - 0.5) * 5, ps: 0, as: 0, serve: 0 };
}

export function PongGame({
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
  const [result, setResult] = useState<"win" | "lose" | null>(null);
  const [hud, setHud] = useState({ ps: 0, as: 0 });

  const step = useCallback((ts: number) => {
    if (!runningRef.current) return;
    const s = stRef.current;
    const ctx = canvasRef.current?.getContext("2d");
    const dtMs = Math.min(48, ts - (lastRef.current || ts));
    lastRef.current = ts;
    const dt = dtMs / 16.6667;
    const k = keysRef.current;

    if (k.has("w") || k.has("arrowup")) s.py -= 7 * dt;
    if (k.has("s") || k.has("arrowdown")) s.py += 7 * dt;
    s.py = Math.max(0, Math.min(H - PH, s.py));
    // AI 追球（略慢、可赢）
    if (s.bvx > 0) { const target = s.by - PH / 2; s.ay += Math.max(-5.2 * dt, Math.min(5.2 * dt, (target - s.ay) * 0.12 * dt)); }
    s.ay = Math.max(0, Math.min(H - PH, s.ay));

    if (s.serve > 0) { s.serve -= dtMs; }
    else {
      s.bx += s.bvx * dt; s.by += s.bvy * dt;
      if (s.by < 8) { s.by = 8; s.bvy = Math.abs(s.bvy); }
      if (s.by > H - 8) { s.by = H - 8; s.bvy = -Math.abs(s.bvy); }
      // 左拍
      if (s.bvx < 0 && s.bx - 8 < 30 + PW && s.bx > 30 && s.by > s.py && s.by < s.py + PH) {
        s.bx = 30 + PW + 8; const rel = (s.by - (s.py + PH / 2)) / (PH / 2); const spd = Math.min(10, Math.hypot(s.bvx, s.bvy) + 0.4); const ang = rel * 0.9; s.bvx = Math.cos(ang) * spd; s.bvy = Math.sin(ang) * spd;
      }
      // 右拍（AI）
      if (s.bvx > 0 && s.bx + 8 > W - 30 - PW && s.bx < W - 30 && s.by > s.ay && s.by < s.ay + PH) {
        s.bx = W - 30 - PW - 8; const rel = (s.by - (s.ay + PH / 2)) / (PH / 2); const spd = Math.min(10, Math.hypot(s.bvx, s.bvy) + 0.4); const ang = rel * 0.9; s.bvx = -Math.cos(ang) * spd; s.bvy = Math.sin(ang) * spd;
      }
      // 得分
      if (s.bx < -10) { s.as += 1; setHud({ ps: s.ps, as: s.as }); resetBall(s, 1); }
      else if (s.bx > W + 10) { s.ps += 1; setHud({ ps: s.ps, as: s.as }); resetBall(s, -1); }
      if (s.ps >= WIN || s.as >= WIN) { runningRef.current = false; setResult(s.ps >= WIN ? "win" : "lose"); setOver(true); }
    }

    if (ctx) {
      ctx.fillStyle = "#05090f"; ctx.fillRect(0, 0, W, H);
      ctx.strokeStyle = "rgb(120 200 255 / 18%)"; ctx.lineWidth = 2; ctx.setLineDash([8, 12]); ctx.beginPath(); ctx.moveTo(W / 2, 0); ctx.lineTo(W / 2, H); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = "#39d4ff"; ctx.shadowColor = "#39d4ff"; ctx.shadowBlur = 10; ctx.fillRect(30, s.py, PW, PH);
      ctx.fillStyle = "#ffb13b"; ctx.shadowColor = "#ffb13b"; ctx.fillRect(W - 30 - PW, s.ay, PW, PH);
      ctx.fillStyle = "#eafaff"; ctx.shadowColor = "#8ef0ff"; ctx.beginPath(); ctx.arc(s.bx, s.by, 8, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
      ctx.fillStyle = "#eafaff"; ctx.font = "800 44px ui-monospace, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.fillText(String(s.ps), W / 2 - 60, 22); ctx.fillStyle = "#ffd8a8"; ctx.fillText(String(s.as), W / 2 + 60, 22);
      ctx.fillStyle = "#7d95ae"; ctx.font = "600 11px ui-monospace, monospace"; ctx.fillText("你", W / 2 - 60, 70); ctx.fillText("AI", W / 2 + 60, 70);
    }
    rafRef.current = requestAnimationFrame(step);
  }, []);

  const start = useCallback(() => { stRef.current = makeState(); setHud({ ps: 0, as: 0 }); setResult(null); setOver(false); runningRef.current = true; lastRef.current = 0; rafRef.current = requestAnimationFrame(step); }, [step]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => { if (!runningRef.current) return; const key = e.key.toLowerCase(); if (["w", "s", "arrowup", "arrowdown"].includes(key)) { keysRef.current.add(key); if (key.startsWith("arrow")) e.preventDefault(); } };
    const up = (e: KeyboardEvent) => keysRef.current.delete(e.key.toLowerCase());
    window.addEventListener("keydown", down); window.addEventListener("keyup", up); start();
    return () => { runningRef.current = false; if (rafRef.current !== null) cancelAnimationFrame(rafRef.current); window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [start]);

  useEffect(() => {
    onScoreChange?.(hud.ps);
  }, [hud.ps, onScoreChange]);

  return (
    <div className="cc-arcade-stage">
      <canvas className="cc-arcade-canvas" height={H} ref={canvasRef} width={W} />
      <div className="cc-arcade-hudbar"><span>你 {hud.ps}</span><span>AI {hud.as}</span><span>W/S 控制球拍 · 先到 7 分</span></div>
      {over ? (
        <div className="cc-arcade-overlay">
          <strong className="cc-arcade-big">{result === "win" ? "你赢了 🏆" : "你输了"}</strong>
          <span>比分 {hud.ps} : {hud.as}</span>
          <div className="cc-arcade-actions">
            <button className="cc-arcade-btn" onClick={start} type="button"><RotateCcw aria-hidden="true" size={16} />再来一局</button>
            <button className="cc-arcade-btn ghost" onClick={onExit} type="button"><LogOut aria-hidden="true" size={16} />返回游戏厅</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function resetBall(s: State, dir: number) {
  s.bx = W / 2; s.by = H / 2; s.bvx = dir * 5.5; s.bvy = (Math.random() - 0.5) * 5; s.serve = 700;
}

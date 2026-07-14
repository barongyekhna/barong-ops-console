"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

// 扫雷 —— WASD / 方向键移动光标，空格挖开，F 插旗。挖到雷就炸，挖完所有安全格获胜。

const W = 760;
const H = 460;
const COLS = 20;
const ROWS = 13;
const MINES = 40;
const CELL = 28;
const BX = (W - COLS * CELL) / 2;
const BY = (H - ROWS * CELL) / 2;
const NUM_COLORS = ["", "#39d4ff", "#4dffa1", "#ffd23b", "#ff9a5f", "#ff6b8a", "#a893ff", "#ff8ac0", "#cfe6ff"];

type Cell = { mine: boolean; count: number; revealed: boolean; flagged: boolean };
function initBoard(): Cell[][] { return Array.from({ length: ROWS }, () => Array.from({ length: COLS }, () => ({ mine: false, count: 0, revealed: false, flagged: false }))); }

export function MinesGame({
  onExit,
  onScoreChange,
}: {
  onExit: () => void;
  onScoreChange?: (score: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const boardRef = useRef<Cell[][]>(initBoard());
  const curRef = useRef({ r: Math.floor(ROWS / 2), c: Math.floor(COLS / 2) });
  const placedRef = useRef(false);
  const revealedRef = useRef(0);
  const overRef = useRef<null | "win" | "lose">(null);
  const [tick, setTick] = useState(0);
  const [over, setOver] = useState<null | "win" | "lose">(null);
  const [flags, setFlags] = useState(0);
  const [score, setScore] = useState(0);

  const place = useCallback((sr: number, sc: number) => {
    const b = boardRef.current;
    let placed = 0;
    while (placed < MINES) {
      const r = Math.floor(Math.random() * ROWS), c = Math.floor(Math.random() * COLS);
      if (b[r][c].mine || (Math.abs(r - sr) <= 1 && Math.abs(c - sc) <= 1)) continue;
      b[r][c].mine = true; placed += 1;
    }
    for (let r = 0; r < ROWS; r += 1) for (let c = 0; c < COLS; c += 1) {
      if (b[r][c].mine) continue;
      let n = 0;
      for (let dr = -1; dr <= 1; dr += 1) for (let dc = -1; dc <= 1; dc += 1) { const nr = r + dr, nc = c + dc; if (nr >= 0 && nr < ROWS && nc >= 0 && nc < COLS && b[nr][nc].mine) n += 1; }
      b[r][c].count = n;
    }
    placedRef.current = true;
  }, []);

  const reveal = useCallback((r: number, c: number) => {
    const b = boardRef.current;
    if (!placedRef.current) place(r, c);
    const stack: [number, number][] = [[r, c]];
    while (stack.length) {
      const [cr, cc] = stack.pop()!;
      const cell = b[cr][cc];
      if (cell.revealed || cell.flagged) continue;
      cell.revealed = true;
      if (cell.mine) { overRef.current = "lose"; setOver("lose"); for (const row of b) for (const cl of row) if (cl.mine) cl.revealed = true; return; }
      revealedRef.current += 1;
      if (cell.count === 0) for (let dr = -1; dr <= 1; dr += 1) for (let dc = -1; dc <= 1; dc += 1) { const nr = cr + dr, nc = cc + dc; if (nr >= 0 && nr < ROWS && nc >= 0 && nc < COLS && !b[nr][nc].revealed) stack.push([nr, nc]); }
    }
    setScore(revealedRef.current);
    if (revealedRef.current >= ROWS * COLS - MINES) { overRef.current = "win"; setOver("win"); }
  }, [place]);

  const restart = useCallback(() => { boardRef.current = initBoard(); curRef.current = { r: Math.floor(ROWS / 2), c: Math.floor(COLS / 2) }; placedRef.current = false; revealedRef.current = 0; overRef.current = null; setOver(null); setFlags(0); setScore(0); setTick((t) => t + 1); }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const key = e.key.toLowerCase();
      const cur = curRef.current;
      if (key === "w" || key === "arrowup") { cur.r = Math.max(0, cur.r - 1); e.preventDefault(); }
      else if (key === "s" || key === "arrowdown") { cur.r = Math.min(ROWS - 1, cur.r + 1); e.preventDefault(); }
      else if (key === "a" || key === "arrowleft") { cur.c = Math.max(0, cur.c - 1); e.preventDefault(); }
      else if (key === "d" || key === "arrowright") { cur.c = Math.min(COLS - 1, cur.c + 1); e.preventDefault(); }
      else if (key === " ") { e.preventDefault(); if (!overRef.current) { const cl = boardRef.current[cur.r][cur.c]; if (!cl.flagged) reveal(cur.r, cur.c); } }
      else if (key === "f") { if (!overRef.current) { const cl = boardRef.current[cur.r][cur.c]; if (!cl.revealed) { cl.flagged = !cl.flagged; setFlags((f) => f + (cl.flagged ? 1 : -1)); } } }
      else return;
      setTick((t) => t + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [reveal]);

  useEffect(() => {
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx) return;
    const b = boardRef.current;
    ctx.fillStyle = "#05090f"; ctx.fillRect(0, 0, W, H);
    for (let r = 0; r < ROWS; r += 1) for (let c = 0; c < COLS; c += 1) {
      const x = BX + c * CELL, y = BY + r * CELL, cell = b[r][c];
      if (cell.revealed) {
        ctx.fillStyle = cell.mine ? "rgb(255 107 138 / 30%)" : "rgb(8 15 26 / 70%)";
        ctx.fillRect(x + 1, y + 1, CELL - 2, CELL - 2);
        if (cell.mine) { ctx.fillStyle = "#ff6b8a"; ctx.beginPath(); ctx.arc(x + CELL / 2, y + CELL / 2, 6, 0, Math.PI * 2); ctx.fill(); }
        else if (cell.count > 0) { ctx.fillStyle = NUM_COLORS[cell.count]; ctx.font = "800 15px ui-monospace, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(String(cell.count), x + CELL / 2, y + CELL / 2 + 1); }
      } else {
        ctx.fillStyle = "rgb(28 46 70 / 85%)"; ctx.fillRect(x + 1, y + 1, CELL - 2, CELL - 2);
        ctx.fillStyle = "rgb(255 255 255 / 8%)"; ctx.fillRect(x + 1, y + 1, CELL - 2, 3);
        if (cell.flagged) { ctx.fillStyle = "#ffb13b"; ctx.font = "800 14px ui-monospace, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("⚑", x + CELL / 2, y + CELL / 2 + 1); }
      }
    }
    // 光标
    const cur = curRef.current;
    ctx.strokeStyle = "#39d4ff"; ctx.lineWidth = 2.5; ctx.strokeRect(BX + cur.c * CELL + 1, BY + cur.r * CELL + 1, CELL - 2, CELL - 2);
    // HUD
    ctx.fillStyle = "#7d95ae"; ctx.font = "700 12px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText(`剩余雷 ${MINES - flags}`, BX, 14); ctx.fillText(`已排除 ${score}`, BX + 140, 14); ctx.fillText("空格 挖 · F 旗", BX + 270, 14);
  }, [tick, flags, score]);

  useEffect(() => {
    onScoreChange?.(score);
  }, [onScoreChange, score]);

  return (
    <div className="cc-arcade-stage">
      <canvas className="cc-arcade-canvas" height={H} ref={canvasRef} width={W} />
      <div className="cc-arcade-hudbar"><span>已排除 {score}</span><span>剩余雷 {MINES - flags}</span><span>WASD 移动 · 空格挖 · F 旗</span></div>
      {over ? (
        <div className="cc-arcade-overlay">
          <strong className="cc-arcade-big">{over === "win" ? "全部排除 🎉" : "踩雷了 💥"}</strong>
          <span>{over === "win" ? "扫雷成功！" : "再接再厉"}</span>
          <div className="cc-arcade-actions">
            <button className="cc-arcade-btn" onClick={restart} type="button"><RotateCcw aria-hidden="true" size={16} />再来一局</button>
            <button className="cc-arcade-btn ghost" onClick={onExit} type="button"><LogOut aria-hidden="true" size={16} />返回游戏厅</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

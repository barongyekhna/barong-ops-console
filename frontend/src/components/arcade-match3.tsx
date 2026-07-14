"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

// 三消 宝石迷阵 —— WASD 移光标，空格选中一颗，再按方向和相邻宝石交换，凑三连消除。限 25 步。

const W = 760;
const H = 460;
const N = 8;
const CELL = 44;
const BX = (W - N * CELL) / 2;
const BY = (H - N * CELL) / 2;
const COLORS = 6;
const GEM = ["#39d4ff", "#ffb13b", "#4dffa1", "#ff6b8a", "#a893ff", "#ffd23b"];
const MOVES = 25;

type Board = number[][];
function randGem() { return Math.floor(Math.random() * COLORS); }
function makeBoard(): Board {
  const b: Board = [];
  for (let r = 0; r < N; r += 1) { b[r] = []; for (let c = 0; c < N; c += 1) { let g = randGem(); while ((c >= 2 && b[r][c - 1] === g && b[r][c - 2] === g) || (r >= 2 && b[r - 1][c] === g && b[r - 2][c] === g)) g = randGem(); b[r][c] = g; } }
  return b;
}
function findMatched(b: Board): boolean[][] {
  const m = Array.from({ length: N }, () => Array<boolean>(N).fill(false));
  for (let r = 0; r < N; r += 1) for (let c = 0; c < N - 2; c += 1) { const g = b[r][c]; if (g >= 0 && b[r][c + 1] === g && b[r][c + 2] === g) { let cc = c; while (cc < N && b[r][cc] === g) { m[r][cc] = true; cc += 1; } } }
  for (let c = 0; c < N; c += 1) for (let r = 0; r < N - 2; r += 1) { const g = b[r][c]; if (g >= 0 && b[r + 1][c] === g && b[r + 2][c] === g) { let rr = r; while (rr < N && b[rr][c] === g) { m[rr][c] = true; rr += 1; } } }
  return m;
}
function hasMatch(b: Board) { return findMatched(b).some((row) => row.some((v) => v)); }
function resolve(b: Board): number {
  let total = 0, combo = 0;
  for (;;) {
    const m = findMatched(b);
    let cleared = 0;
    for (let r = 0; r < N; r += 1) for (let c = 0; c < N; c += 1) if (m[r][c]) { b[r][c] = -1; cleared += 1; }
    if (cleared === 0) break;
    combo += 1; total += cleared * combo;
    for (let c = 0; c < N; c += 1) {
      const existing: number[] = [];
      for (let r = N - 1; r >= 0; r -= 1) if (b[r][c] >= 0) existing.push(b[r][c]);
      for (let i = 0; i < N; i += 1) b[N - 1 - i][c] = i < existing.length ? existing[i] : randGem();
    }
  }
  return total;
}

export function Match3Game({
  onExit,
  onScoreChange,
}: {
  onExit: () => void;
  onScoreChange?: (score: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const boardRef = useRef<Board>(makeBoard());
  const curRef = useRef({ r: 4, c: 4 });
  const selRef = useRef<{ r: number; c: number } | null>(null);
  const overRef = useRef(false);
  const [tick, setTick] = useState(0);
  const [score, setScore] = useState(0);
  const [moves, setMoves] = useState(MOVES);
  const [over, setOver] = useState(false);

  const restart = useCallback(() => { boardRef.current = makeBoard(); curRef.current = { r: 4, c: 4 }; selRef.current = null; overRef.current = false; setScore(0); setMoves(MOVES); setOver(false); setTick((t) => t + 1); }, []);

  const trySwap = useCallback((a: { r: number; c: number }, dr: number, dc: number) => {
    const nr = a.r + dr, nc = a.c + dc;
    if (nr < 0 || nr >= N || nc < 0 || nc >= N) return;
    const b = boardRef.current;
    const t = b[a.r][a.c]; b[a.r][a.c] = b[nr][nc]; b[nr][nc] = t;
    if (hasMatch(b)) {
      const gained = resolve(b);
      setScore((s) => s + gained * 10);
      setMoves((m) => { const nm = m - 1; if (nm <= 0) { overRef.current = true; setOver(true); } return nm; });
    } else { b[nr][nc] = b[a.r][a.c]; b[a.r][a.c] = t; }
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (overRef.current) return;
      const key = e.key.toLowerCase();
      const dirs: Record<string, [number, number]> = { w: [-1, 0], arrowup: [-1, 0], s: [1, 0], arrowdown: [1, 0], a: [0, -1], arrowleft: [0, -1], d: [0, 1], arrowright: [0, 1] };
      if (key in dirs) {
        e.preventDefault();
        const [dr, dc] = dirs[key];
        if (selRef.current) { trySwap(selRef.current, dr, dc); selRef.current = null; }
        else { const cur = curRef.current; cur.r = Math.max(0, Math.min(N - 1, cur.r + dr)); cur.c = Math.max(0, Math.min(N - 1, cur.c + dc)); }
      } else if (key === " ") {
        e.preventDefault();
        const cur = curRef.current;
        selRef.current = selRef.current && selRef.current.r === cur.r && selRef.current.c === cur.c ? null : { r: cur.r, c: cur.c };
      } else return;
      setTick((t) => t + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [trySwap]);

  useEffect(() => {
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx) return;
    const b = boardRef.current;
    ctx.fillStyle = "#05090f"; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "rgb(10 18 30 / 70%)"; ctx.strokeStyle = "rgb(120 200 255 / 18%)"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.roundRect(BX - 8, BY - 8, N * CELL + 16, N * CELL + 16, 12); ctx.fill(); ctx.stroke();
    for (let r = 0; r < N; r += 1) for (let c = 0; c < N; c += 1) {
      const g = b[r][c]; if (g < 0) continue;
      const x = BX + c * CELL, y = BY + r * CELL;
      ctx.fillStyle = GEM[g]; ctx.beginPath(); ctx.roundRect(x + 4, y + 4, CELL - 8, CELL - 8, 9); ctx.fill();
      ctx.fillStyle = "rgb(255 255 255 / 22%)"; ctx.beginPath(); ctx.roundRect(x + 8, y + 8, CELL - 16, 6, 3); ctx.fill();
    }
    const sel = selRef.current;
    if (sel) { ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 3; ctx.strokeRect(BX + sel.c * CELL + 3, BY + sel.r * CELL + 3, CELL - 6, CELL - 6); }
    const cur = curRef.current;
    ctx.strokeStyle = sel ? "#ffb13b" : "#39d4ff"; ctx.lineWidth = 2.5; ctx.strokeRect(BX + cur.c * CELL + 2, BY + cur.r * CELL + 2, CELL - 4, CELL - 4);
    ctx.fillStyle = "#39d4ff"; ctx.font = "700 11px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText("SCORE", 30, BY); ctx.fillStyle = "#eafaff"; ctx.font = "800 24px ui-monospace, monospace"; ctx.fillText(String(score), 30, BY + 16);
    ctx.fillStyle = "#39d4ff"; ctx.font = "700 11px ui-monospace, monospace"; ctx.fillText("MOVES", 30, BY + 64); ctx.fillStyle = "#eafaff"; ctx.font = "800 24px ui-monospace, monospace"; ctx.fillText(String(moves), 30, BY + 80);
  }, [tick, score, moves]);

  useEffect(() => {
    onScoreChange?.(score);
  }, [onScoreChange, score]);

  return (
    <div className="cc-arcade-stage">
      <canvas className="cc-arcade-canvas" height={H} ref={canvasRef} width={W} />
      <div className="cc-arcade-hudbar"><span>得分 {score}</span><span>步数 {moves}</span><span>空格选中 · 方向交换</span></div>
      {over ? (
        <div className="cc-arcade-overlay">
          <strong className="cc-arcade-big">步数用尽</strong>
          <span>本局得分 {score}</span>
          <div className="cc-arcade-actions">
            <button className="cc-arcade-btn" onClick={restart} type="button"><RotateCcw aria-hidden="true" size={16} />再来一局</button>
            <button className="cc-arcade-btn ghost" onClick={onExit} type="button"><LogOut aria-hidden="true" size={16} />返回游戏厅</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

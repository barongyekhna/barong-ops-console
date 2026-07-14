"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

// 2048 —— WASD / 方向键滑动合并相同数字，凑到 2048。

const W = 760;
const H = 460;
type Grid = number[][];

const TILE_COLORS: Record<number, string> = {
  2: "#12303f", 4: "#164a5e", 8: "#1c6f82", 16: "#249fb4", 32: "#39d4ff",
  64: "#3fd6a0", 128: "#4dffa1", 256: "#ffd23b", 512: "#ffb13b", 1024: "#ff9a5f",
  2048: "#ff6b8a", 4096: "#a893ff", 8192: "#c9b8ff",
};
function tileColor(v: number) { return TILE_COLORS[v] ?? "#c9b8ff"; }
function textColor(v: number) { return v <= 16 ? "#d6e8f6" : "#04121a"; }

function empties(g: Grid): [number, number][] { const e: [number, number][] = []; for (let r = 0; r < 4; r += 1) for (let c = 0; c < 4; c += 1) if (g[r][c] === 0) e.push([r, c]); return e; }
function addTile(g: Grid): Grid { const e = empties(g); if (e.length === 0) return g; const [r, c] = e[Math.floor(Math.random() * e.length)]; const ng = g.map((row) => row.slice()); ng[r][c] = Math.random() < 0.9 ? 2 : 4; return ng; }
function newGrid(): Grid { let g: Grid = Array.from({ length: 4 }, () => [0, 0, 0, 0]); g = addTile(g); g = addTile(g); return g; }
function slide(line: number[]): { line: number[]; gained: number; moved: boolean } {
  const nz = line.filter((v) => v !== 0); const res: number[] = []; let gained = 0;
  for (let i = 0; i < nz.length; i += 1) { if (i + 1 < nz.length && nz[i] === nz[i + 1]) { res.push(nz[i] * 2); gained += nz[i] * 2; i += 1; } else res.push(nz[i]); }
  while (res.length < 4) res.push(0);
  return { line: res, gained, moved: res.some((v, idx) => v !== line[idx]) };
}
const transpose = (g: Grid): Grid => g[0].map((_, c) => g.map((row) => row[c]));
const rev = (g: Grid): Grid => g.map((row) => row.slice().reverse());
function move(grid: Grid, dir: "left" | "right" | "up" | "down"): { grid: Grid; gained: number; moved: boolean } {
  let g = grid.map((r) => r.slice()); let gained = 0; let moved = false;
  const vertical = dir === "up" || dir === "down";
  if (vertical) g = transpose(g);
  if (dir === "right" || dir === "down") g = rev(g);
  g = g.map((row) => { const s = slide(row); gained += s.gained; if (s.moved) moved = true; return s.line; });
  if (dir === "right" || dir === "down") g = rev(g);
  if (vertical) g = transpose(g);
  return { grid: g, gained, moved };
}
function canMove(g: Grid): boolean {
  if (empties(g).length > 0) return true;
  for (let r = 0; r < 4; r += 1) for (let c = 0; c < 4; c += 1) { if (c < 3 && g[r][c] === g[r][c + 1]) return true; if (r < 3 && g[r][c] === g[r + 1][c]) return true; }
  return false;
}

export function Game2048({
  onExit,
  onScoreChange,
}: {
  onExit: () => void;
  onScoreChange?: (score: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [grid, setGrid] = useState<Grid>(newGrid);
  const [score, setScore] = useState(0);
  const [over, setOver] = useState(false);
  const gridRef = useRef(grid);
  const overRef = useRef(over);
  gridRef.current = grid;
  overRef.current = over;

  const restart = useCallback(() => { setGrid(newGrid()); setScore(0); setOver(false); }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (overRef.current) return;
      const key = e.key.toLowerCase();
      const dir = key === "a" || key === "arrowleft" ? "left" : key === "d" || key === "arrowright" ? "right" : key === "w" || key === "arrowup" ? "up" : key === "s" || key === "arrowdown" ? "down" : null;
      if (!dir) return;
      e.preventDefault();
      const res = move(gridRef.current, dir);
      if (!res.moved) return;
      const ng = addTile(res.grid);
      setGrid(ng);
      if (res.gained) setScore((s) => s + res.gained);
      if (!canMove(ng)) setOver(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "#05090f"; ctx.fillRect(0, 0, W, H);
    const B = 416, gap = 10, cell = (B - gap * 5) / 4;
    const bx = (W - B) / 2, by = (H - B) / 2;
    ctx.fillStyle = "rgb(10 18 30 / 75%)"; ctx.strokeStyle = "rgb(120 200 255 / 20%)"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.roundRect(bx, by, B, B, 14); ctx.fill(); ctx.stroke();
    for (let r = 0; r < 4; r += 1) for (let c = 0; c < 4; c += 1) {
      const x = bx + gap + c * (cell + gap), y = by + gap + r * (cell + gap);
      const v = grid[r][c];
      ctx.fillStyle = v === 0 ? "rgb(120 200 255 / 6%)" : tileColor(v);
      ctx.beginPath(); ctx.roundRect(x, y, cell, cell, 9); ctx.fill();
      if (v !== 0) {
        ctx.fillStyle = textColor(v);
        const digits = String(v).length;
        ctx.font = `800 ${digits >= 4 ? 30 : digits === 3 ? 36 : 42}px ui-monospace, monospace`;
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(String(v), x + cell / 2, y + cell / 2 + 2);
      }
    }
    // 左侧标题 / 分数
    ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillStyle = "#eafaff"; ctx.font = "800 34px ui-monospace, monospace"; ctx.fillText("2048", 40, 40);
    ctx.fillStyle = "#39d4ff"; ctx.font = "700 11px ui-monospace, monospace"; ctx.fillText("SCORE", 40, 100);
    ctx.fillStyle = "#eafaff"; ctx.font = "800 26px ui-monospace, monospace"; ctx.fillText(String(score), 40, 116);
    ctx.fillStyle = "#7d95ae"; ctx.font = "600 12px ui-monospace, monospace";
    ctx.fillText("WASD 滑动", 40, 168); ctx.fillText("合并相同数字", 40, 188);
  }, [grid, score]);

  useEffect(() => {
    onScoreChange?.(score);
  }, [onScoreChange, score]);

  return (
    <div className="cc-arcade-stage">
      <canvas className="cc-arcade-canvas" height={H} ref={canvasRef} width={W} />
      <div className="cc-arcade-hudbar"><span>得分 {score}</span><span>WASD 滑动合并</span></div>
      {over ? (
        <div className="cc-arcade-overlay">
          <strong className="cc-arcade-big">无路可走</strong>
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

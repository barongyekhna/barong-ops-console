"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

// 俄罗斯方块 —— A/D 左右，W 旋转，S 软降，空格瞬降。消行得分、升级加速。

const COLS = 10;
const ROWS = 20;
const CELL = 22;
const FX = 270; // 场地左偏移
const FY = 0;
const W = 760;
const H = ROWS * CELL;

type Matrix = number[][];
const SHAPES: { m: Matrix; c: string }[] = [
  { c: "#39d4ff", m: [[1, 1, 1, 1]] },
  { c: "#ffd23b", m: [[1, 1], [1, 1]] },
  { c: "#a893ff", m: [[0, 1, 0], [1, 1, 1]] },
  { c: "#4dffa1", m: [[0, 1, 1], [1, 1, 0]] },
  { c: "#ff6b8a", m: [[1, 1, 0], [0, 1, 1]] },
  { c: "#5b8cff", m: [[1, 0, 0], [1, 1, 1]] },
  { c: "#ffb13b", m: [[0, 0, 1], [1, 1, 1]] },
];

type Piece = { m: Matrix; c: string; x: number; y: number };
type Board = (string | 0)[][];
type State = { board: Board; piece: Piece; nextIdx: number; score: number; lines: number; level: number; gap: number; acc: number };

function emptyBoard(): Board {
  return Array.from({ length: ROWS }, () => Array<string | 0>(COLS).fill(0));
}
function rotate(m: Matrix): Matrix {
  const rows = m.length, cols = m[0].length;
  const r: Matrix = Array.from({ length: cols }, () => Array(rows).fill(0));
  for (let y = 0; y < rows; y += 1) for (let x = 0; x < cols; x += 1) r[x][rows - 1 - y] = m[y][x];
  return r;
}
function collide(board: Board, m: Matrix, px: number, py: number): boolean {
  for (let y = 0; y < m.length; y += 1) for (let x = 0; x < m[0].length; x += 1) {
    if (!m[y][x]) continue;
    const bx = px + x, by = py + y;
    if (bx < 0 || bx >= COLS || by >= ROWS) return true;
    if (by >= 0 && board[by][bx] !== 0) return true;
  }
  return false;
}
function spawnPiece(idx: number): Piece {
  const s = SHAPES[idx];
  return { m: s.m.map((r) => r.slice()), c: s.c, x: Math.floor((COLS - s.m[0].length) / 2), y: 0 };
}
function makeState(): State {
  return { board: emptyBoard(), piece: spawnPiece(Math.floor(Math.random() * 7)), nextIdx: Math.floor(Math.random() * 7), score: 0, lines: 0, level: 1, gap: 800, acc: 0 };
}

export function TetrisGame({ onExit }: { onExit: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stRef = useRef<State>(makeState());
  const softRef = useRef(false);
  const rafRef = useRef<number | null>(null);
  const lastRef = useRef(0);
  const runningRef = useRef(false);
  const [over, setOver] = useState(false);
  const [hud, setHud] = useState({ score: 0, lines: 0, level: 1 });

  const lockAndNext = useCallback((s: State) => {
    for (let y = 0; y < s.piece.m.length; y += 1) for (let x = 0; x < s.piece.m[0].length; x += 1) {
      if (s.piece.m[y][x]) { const by = s.piece.y + y; const bx = s.piece.x + x; if (by >= 0) s.board[by][bx] = s.piece.c; }
    }
    let cleared = 0;
    s.board = s.board.filter((row) => {
      if (row.every((c) => c !== 0)) { cleared += 1; return false; }
      return true;
    });
    while (s.board.length < ROWS) s.board.unshift(Array<string | 0>(COLS).fill(0));
    if (cleared > 0) {
      s.lines += cleared;
      s.score += [0, 100, 300, 500, 800][cleared] * s.level;
      s.level = 1 + Math.floor(s.lines / 10);
      s.gap = Math.max(110, 800 - (s.level - 1) * 68);
    }
    s.piece = spawnPiece(s.nextIdx);
    s.nextIdx = Math.floor(Math.random() * 7);
    setHud({ score: s.score, lines: s.lines, level: s.level });
    if (collide(s.board, s.piece.m, s.piece.x, s.piece.y)) { runningRef.current = false; setOver(true); }
  }, []);

  const draw = useCallback((ctx: CanvasRenderingContext2D) => {
    const s = stRef.current;
    ctx.fillStyle = "#04070e"; ctx.fillRect(0, 0, W, H);
    // 场地底
    ctx.fillStyle = "#070d16"; ctx.fillRect(FX, FY, COLS * CELL, ROWS * CELL);
    ctx.strokeStyle = "rgb(120 200 255 / 6%)"; ctx.lineWidth = 1;
    for (let x = 0; x <= COLS; x += 1) { ctx.beginPath(); ctx.moveTo(FX + x * CELL, FY); ctx.lineTo(FX + x * CELL, FY + ROWS * CELL); ctx.stroke(); }
    for (let y = 0; y <= ROWS; y += 1) { ctx.beginPath(); ctx.moveTo(FX, FY + y * CELL); ctx.lineTo(FX + COLS * CELL, FY + y * CELL); ctx.stroke(); }
    const block = (bx: number, by: number, c: string) => {
      const px = FX + bx * CELL, py = FY + by * CELL;
      ctx.fillStyle = c; ctx.fillRect(px + 1, py + 1, CELL - 2, CELL - 2);
      ctx.fillStyle = "rgb(255 255 255 / 18%)"; ctx.fillRect(px + 1, py + 1, CELL - 2, 3);
    };
    for (let y = 0; y < ROWS; y += 1) for (let x = 0; x < COLS; x += 1) { const c = s.board[y][x]; if (c !== 0) block(x, y, c); }
    for (let y = 0; y < s.piece.m.length; y += 1) for (let x = 0; x < s.piece.m[0].length; x += 1) if (s.piece.m[y][x] && s.piece.y + y >= 0) block(s.piece.x + x, s.piece.y + y, s.piece.c);
    // 边框
    ctx.strokeStyle = "rgb(120 200 255 / 26%)"; ctx.lineWidth = 2; ctx.strokeRect(FX, FY, COLS * CELL, ROWS * CELL);
    // 左侧标题
    ctx.fillStyle = "#eafaff"; ctx.font = "800 22px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText("TETRIS", 30, 26);
    ctx.fillStyle = "#7d95ae"; ctx.font = "600 12px ui-monospace, monospace";
    ctx.fillText("A / D  左右", 30, 70);
    ctx.fillText("W  旋转", 30, 92);
    ctx.fillText("S  软降", 30, 114);
    ctx.fillText("空格  瞬降", 30, 136);
    // 右侧 HUD + NEXT
    const rx = FX + COLS * CELL + 34;
    ctx.fillStyle = "#39d4ff"; ctx.font = "700 11px ui-monospace, monospace"; ctx.fillText("SCORE", rx, 30);
    ctx.fillStyle = "#eafaff"; ctx.font = "800 20px ui-monospace, monospace"; ctx.fillText(String(s.score), rx, 46);
    ctx.fillStyle = "#39d4ff"; ctx.font = "700 11px ui-monospace, monospace"; ctx.fillText("LEVEL", rx, 84); ctx.fillText("LINES", rx, 128);
    ctx.fillStyle = "#eafaff"; ctx.font = "800 18px ui-monospace, monospace"; ctx.fillText(String(s.level), rx, 100); ctx.fillText(String(s.lines), rx, 144);
    ctx.fillStyle = "#39d4ff"; ctx.font = "700 11px ui-monospace, monospace"; ctx.fillText("NEXT", rx, 184);
    const nm = SHAPES[s.nextIdx];
    for (let y = 0; y < nm.m.length; y += 1) for (let x = 0; x < nm.m[0].length; x += 1) if (nm.m[y][x]) {
      const px = rx + x * 18, py = 204 + y * 18;
      ctx.fillStyle = nm.c; ctx.fillRect(px, py, 16, 16);
    }
  }, []);

  const step = useCallback((ts: number) => {
    if (!runningRef.current) return;
    const s = stRef.current;
    const ctx = canvasRef.current?.getContext("2d");
    const dtMs = Math.min(64, ts - (lastRef.current || ts));
    lastRef.current = ts;
    s.acc += dtMs;
    const gap = softRef.current ? 55 : s.gap;
    while (s.acc >= gap) {
      s.acc -= gap;
      if (!collide(s.board, s.piece.m, s.piece.x, s.piece.y + 1)) s.piece.y += 1;
      else lockAndNext(s);
      if (!runningRef.current) break;
    }
    if (ctx) draw(ctx);
    if (runningRef.current) rafRef.current = requestAnimationFrame(step);
  }, [draw, lockAndNext]);

  const start = useCallback(() => {
    stRef.current = makeState();
    setHud({ score: 0, lines: 0, level: 1 }); setOver(false);
    runningRef.current = true; lastRef.current = 0;
    rafRef.current = requestAnimationFrame(step);
  }, [step]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (!runningRef.current) return;
      const key = e.key.toLowerCase();
      const s = stRef.current;
      if (key === "a" || key === "arrowleft") { if (!collide(s.board, s.piece.m, s.piece.x - 1, s.piece.y)) s.piece.x -= 1; e.preventDefault(); }
      else if (key === "d" || key === "arrowright") { if (!collide(s.board, s.piece.m, s.piece.x + 1, s.piece.y)) s.piece.x += 1; e.preventDefault(); }
      else if (key === "w" || key === "arrowup") {
        const r = rotate(s.piece.m);
        for (const kick of [0, -1, 1, -2, 2]) { if (!collide(s.board, r, s.piece.x + kick, s.piece.y)) { s.piece.m = r; s.piece.x += kick; break; } }
        e.preventDefault();
      } else if (key === "s" || key === "arrowdown") { softRef.current = true; e.preventDefault(); }
      else if (key === " " || key === "spacebar") {
        while (!collide(s.board, s.piece.m, s.piece.x, s.piece.y + 1)) s.piece.y += 1;
        lockAndNext(s); s.acc = 0; e.preventDefault();
      }
    };
    const up = (e: KeyboardEvent) => { const key = e.key.toLowerCase(); if (key === "s" || key === "arrowdown") softRef.current = false; };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    start();
    return () => {
      runningRef.current = false;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [start, lockAndNext]);

  return (
    <div className="cc-arcade-stage">
      <canvas className="cc-arcade-canvas" height={H} ref={canvasRef} width={W} />
      <div className="cc-arcade-hudbar">
        <span>得分 {hud.score}</span>
        <span>等级 {hud.level}</span>
        <span>消行 {hud.lines}</span>
      </div>
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

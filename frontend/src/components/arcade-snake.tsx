"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

// 贪吃蛇 —— WASD / 方向键转向，吃光点变长、加速，撞墙或撞自己结束。

const CELL = 20;
const COLS = 38;
const ROWS = 22;
const W = COLS * CELL;
const H = ROWS * CELL;

type Cell = { x: number; y: number };
type State = { snake: Cell[]; dir: Cell; nextDir: Cell; food: Cell; score: number; gap: number; acc: number };

function randFood(snake: Cell[]): Cell {
  while (true) {
    const f = { x: Math.floor(Math.random() * COLS), y: Math.floor(Math.random() * ROWS) };
    if (!snake.some((s) => s.x === f.x && s.y === f.y)) return f;
  }
}

function makeState(): State {
  const snake = [
    { x: 8, y: 11 },
    { x: 7, y: 11 },
    { x: 6, y: 11 },
  ];
  return { snake, dir: { x: 1, y: 0 }, nextDir: { x: 1, y: 0 }, food: randFood(snake), score: 0, gap: 130, acc: 0 };
}

export function SnakeGame({
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

  const draw = useCallback((ctx: CanvasRenderingContext2D) => {
    const s = stRef.current;
    ctx.fillStyle = "#05090f";
    ctx.fillRect(0, 0, W, H);
    ctx.strokeStyle = "rgb(120 200 255 / 5%)";
    ctx.lineWidth = 1;
    for (let x = 0; x <= COLS; x += 1) { ctx.beginPath(); ctx.moveTo(x * CELL, 0); ctx.lineTo(x * CELL, H); ctx.stroke(); }
    for (let y = 0; y <= ROWS; y += 1) { ctx.beginPath(); ctx.moveTo(0, y * CELL); ctx.lineTo(W, y * CELL); ctx.stroke(); }
    // food
    ctx.fillStyle = "#ffb13b"; ctx.shadowColor = "#ffb13b"; ctx.shadowBlur = 12;
    ctx.beginPath(); ctx.arc(s.food.x * CELL + CELL / 2, s.food.y * CELL + CELL / 2, CELL / 2 - 3, 0, Math.PI * 2); ctx.fill();
    ctx.shadowBlur = 0;
    // snake
    s.snake.forEach((seg, i) => {
      const head = i === 0;
      ctx.fillStyle = head ? "#5fe3ff" : "#2aa7d8";
      if (head) { ctx.shadowColor = "#39d4ff"; ctx.shadowBlur = 12; }
      const pad = head ? 1 : 2;
      ctx.fillRect(seg.x * CELL + pad, seg.y * CELL + pad, CELL - pad * 2, CELL - pad * 2);
      ctx.shadowBlur = 0;
    });
    ctx.fillStyle = "#7d95ae"; ctx.font = "700 12px ui-monospace, monospace"; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText(`SCORE ${s.score}`, 12, 10);
  }, []);

  const step = useCallback((ts: number) => {
    if (!runningRef.current) return;
    const s = stRef.current;
    const ctx = canvasRef.current?.getContext("2d");
    const dtMs = Math.min(64, ts - (lastRef.current || ts));
    lastRef.current = ts;
    s.acc += dtMs;
    while (s.acc >= s.gap) {
      s.acc -= s.gap;
      s.dir = s.nextDir;
      const head = { x: s.snake[0].x + s.dir.x, y: s.snake[0].y + s.dir.y };
      if (head.x < 0 || head.x >= COLS || head.y < 0 || head.y >= ROWS || s.snake.some((seg) => seg.x === head.x && seg.y === head.y)) {
        runningRef.current = false;
        setOver(true);
        break;
      }
      s.snake.unshift(head);
      if (head.x === s.food.x && head.y === s.food.y) {
        s.score += 10;
        s.gap = Math.max(60, s.gap - 3);
        s.food = randFood(s.snake);
        setScore(s.score);
      } else {
        s.snake.pop();
      }
    }
    if (ctx) draw(ctx);
    if (runningRef.current) rafRef.current = requestAnimationFrame(step);
  }, [draw]);

  const start = useCallback(() => {
    stRef.current = makeState();
    setScore(0); setOver(false);
    runningRef.current = true; lastRef.current = 0;
    rafRef.current = requestAnimationFrame(step);
  }, [step]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!runningRef.current) return;
      const key = e.key.toLowerCase();
      const s = stRef.current;
      const set = (x: number, y: number) => { if (s.dir.x !== -x || s.dir.y !== -y) s.nextDir = { x, y }; };
      if (key === "w" || key === "arrowup") { set(0, -1); if (key.startsWith("arrow")) e.preventDefault(); }
      else if (key === "s" || key === "arrowdown") { set(0, 1); if (key.startsWith("arrow")) e.preventDefault(); }
      else if (key === "a" || key === "arrowleft") { set(-1, 0); if (key.startsWith("arrow")) e.preventDefault(); }
      else if (key === "d" || key === "arrowright") { set(1, 0); if (key.startsWith("arrow")) e.preventDefault(); }
    };
    window.addEventListener("keydown", onKey);
    start();
    return () => {
      runningRef.current = false;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      window.removeEventListener("keydown", onKey);
    };
  }, [start]);

  useEffect(() => {
    onScoreChange?.(score);
  }, [onScoreChange, score]);

  return (
    <div className="cc-arcade-stage">
      <canvas className="cc-arcade-canvas" height={H} ref={canvasRef} width={W} />
      <div className="cc-arcade-hudbar">
        <span>得分 {score}</span>
        <span>WASD 转向</span>
      </div>
      {over ? (
        <div className="cc-arcade-overlay">
          <strong className="cc-arcade-big">游戏结束</strong>
          <span>本局得分 {score}</span>
          <div className="cc-arcade-actions">
            <button className="cc-arcade-btn" onClick={start} type="button"><RotateCcw aria-hidden="true" size={16} />再来一局</button>
            <button className="cc-arcade-btn ghost" onClick={onExit} type="button"><LogOut aria-hidden="true" size={16} />返回游戏厅</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

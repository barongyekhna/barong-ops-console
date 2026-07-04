"use client";

import { useEffect, useRef } from "react";

/**
 * 纯装饰的深空背景 + 掠过的星舰 + 悬停彩蛋(锁定 + 三枚追踪导弹)。
 * 不承载任何业务逻辑;卸载时清理所有动画/监听。
 */
export function DashboardScene() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const shipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ship = shipRef.current;
    if (!canvas || !ship) {
      return;
    }
    const g = canvas.getContext("2d");
    if (!g) {
      return;
    }
    const fx = document.createElement("div");
    fx.className = "dsc-fx";
    document.body.appendChild(fx);

    const timeouts: number[] = [];
    const intervals: number[] = [];
    const rafs = new Set<number>();
    const track = (id: number) => {
      rafs.add(id);
      return id;
    };

    // ---- 星场 ----
    let width = 0;
    let height = 0;
    let stars: Array<{ x: number; y: number; r: number; b: number; t: number; s: number }> = [];
    const build = () => {
      width = canvas.width = canvas.offsetWidth;
      height = canvas.height = canvas.offsetHeight;
      const count = Math.round((width * height) / 16000);
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        r: Math.random() * 1.1 + 0.2,
        b: Math.random() * 0.5 + 0.3,
        t: Math.random() * 6.28,
        s: Math.random() * 0.02 + 0.004,
      }));
    };
    build();
    const onResize = () => build();
    window.addEventListener("resize", onResize);

    let starLoop = 0;
    const drawStars = () => {
      g.clearRect(0, 0, width, height);
      g.globalCompositeOperation = "lighter";
      for (const s of stars) {
        s.t += s.s;
        g.globalAlpha = s.b * (0.5 + 0.5 * Math.sin(s.t));
        g.fillStyle = "#ffffff";
        g.beginPath();
        g.arc(s.x, s.y, s.r, 0, 6.283);
        g.fill();
      }
      g.globalAlpha = 1;
      starLoop = requestAnimationFrame(drawStars);
    };
    starLoop = requestAnimationFrame(drawStars);

    // ---- 悬停彩蛋 ----
    let attacking = false;
    const shipVisible = () => Number.parseFloat(getComputedStyle(ship).opacity || "0") > 0.3;
    const rect = () => ship.getBoundingClientRect();

    const flash = () => {
      ship.style.filter = "drop-shadow(0 0 24px rgba(255,70,50,.95)) brightness(1.7) saturate(1.4)";
      timeouts.push(window.setTimeout(() => {
        ship.style.filter = "";
      }, 170));
    };

    const boom = (x: number, y: number) => {
      const b = document.createElement("div");
      b.className = "dsc-boom";
      b.style.left = `${x}px`;
      b.style.top = `${y}px`;
      fx.appendChild(b);
      timeouts.push(window.setTimeout(() => b.remove(), 520));
    };

    const launch = (index: number, done: () => void) => {
      const missile = document.createElement("div");
      missile.className = "dsc-missile";
      fx.appendChild(missile);
      let x = -40;
      let y = window.innerHeight * (0.5 + index * 0.14);
      const speed = 13;
      const step = () => {
        const r = rect();
        const cx = r.left + r.width / 2;
        const cy = r.top + r.height / 2;
        const dx = cx - x;
        const dy = cy - y;
        const dist = Math.hypot(dx, dy) || 1;
        x += (dx / dist) * speed;
        y += (dy / dist) * speed;
        missile.style.left = `${x}px`;
        missile.style.top = `${y}px`;
        missile.style.transform = `rotate(${Math.atan2(dy, dx)}rad)`;
        if (dist < 24) {
          boom(cx, cy);
          missile.remove();
          flash();
          done();
          return;
        }
        track(requestAnimationFrame(step));
      };
      track(requestAnimationFrame(step));
    };

    const fireThree = () => {
      let done = 0;
      for (let i = 0; i < 3; i += 1) {
        timeouts.push(window.setTimeout(() => {
          launch(i, () => {
            done += 1;
            if (done === 3) {
              timeouts.push(window.setTimeout(() => {
                attacking = false;
              }, 2500));
            }
          });
        }, i * 160));
      }
    };

    const lockAndFire = () => {
      attacking = true;
      const reticle = document.createElement("div");
      reticle.className = "dsc-reticle";
      reticle.innerHTML =
        '<span class="dsc-br tl"></span><span class="dsc-br tr"></span>' +
        '<span class="dsc-br bl"></span><span class="dsc-br br2"></span>' +
        '<div class="dsc-cross"></div><div class="dsc-ring"></div>' +
        '<div class="dsc-lbl">◣ TARGET LOCKED</div>';
      fx.appendChild(reticle);
      const pad = 14;
      const place = () => {
        const r = rect();
        reticle.style.left = `${r.left - pad}px`;
        reticle.style.top = `${r.top - pad}px`;
        reticle.style.width = `${r.width + pad * 2}px`;
        reticle.style.height = `${r.height + pad * 2}px`;
      };
      place();
      const follow = window.setInterval(place, 16);
      intervals.push(follow);
      timeouts.push(window.setTimeout(() => {
        fireThree();
        timeouts.push(window.setTimeout(() => {
          window.clearInterval(follow);
          reticle.remove();
        }, 700));
      }, 1000));
    };

    const onMove = (event: MouseEvent) => {
      if (attacking || !shipVisible()) {
        return;
      }
      const r = rect();
      if (
        event.clientX >= r.left - 8 &&
        event.clientX <= r.right + 8 &&
        event.clientY >= r.top - 8 &&
        event.clientY <= r.bottom + 8
      ) {
        lockAndFire();
      }
    };
    document.addEventListener("mousemove", onMove);

    return () => {
      cancelAnimationFrame(starLoop);
      rafs.forEach((id) => cancelAnimationFrame(id));
      timeouts.forEach((id) => window.clearTimeout(id));
      intervals.forEach((id) => window.clearInterval(id));
      window.removeEventListener("resize", onResize);
      document.removeEventListener("mousemove", onMove);
      fx.remove();
    };
  }, []);

  return (
    <div className="dsc-space" aria-hidden="true">
      <canvas className="dsc-stars" ref={canvasRef} />
      <div className="dsc-nebula" />
      <div className="dsc-phoenix" />
      <div className="dsc-ship" ref={shipRef} />
    </div>
  );
}

import { useEffect, useRef, useState } from "react";

interface Shard {
  x: number;
  y: number;
  vx: number;
  vy: number;
  rot: number;
  vr: number;
  born: number;
  ttl: number;
  verts: Array<{ x: number; y: number }>;
}

const MAX_SHARDS = 48;
const MIN_MOVE = 5;
const SPAWN_MS = 32;
const MAX_DPR = 1.5;

function parseRgb(value: string): [number, number, number] {
  const hex = value.trim();
  if (/^#[0-9a-fA-F]{6}$/.test(hex)) {
    return [
      Number.parseInt(hex.slice(1, 3), 16),
      Number.parseInt(hex.slice(3, 5), 16),
      Number.parseInt(hex.slice(5, 7), 16),
    ];
  }
  if (/^#[0-9a-fA-F]{3}$/.test(hex)) {
    const r = hex.charAt(1);
    const g = hex.charAt(2);
    const b = hex.charAt(3);
    return [Number.parseInt(r + r, 16), Number.parseInt(g + g, 16), Number.parseInt(b + b, 16)];
  }
  return [142, 220, 255];
}

function makeShard(x: number, y: number, dx: number, dy: number, now: number): Shard {
  const sides = 3 + Math.floor(Math.random() * 3);
  const size = 5 + Math.random() * 13;
  const rot = Math.random() * Math.PI * 2;
  const verts = Array.from({ length: sides }, (_, i) => {
    const angle = rot + (i / sides) * Math.PI * 2;
    const radius = size * (0.42 + Math.random() * 0.7);
    return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
  });
  const travel = Math.hypot(dx, dy) || 1;
  const speed = 0.12 + Math.random() * 0.38;
  return {
    x,
    y,
    vx: (-dx / travel) * speed + (Math.random() - 0.5) * 0.28,
    vy: (-dy / travel) * speed + (Math.random() - 0.5) * 0.28,
    rot,
    vr: (Math.random() - 0.5) * 0.035,
    born: now,
    ttl: 420 + Math.random() * 460,
    verts,
  };
}

export function CrystalField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const coarse = window.matchMedia("(pointer: coarse)");
    const sync = () => setEnabled(!motion.matches && !coarse.matches);
    sync();
    motion.addEventListener("change", sync);
    coarse.addEventListener("change", sync);
    return () => {
      motion.removeEventListener("change", sync);
      coarse.removeEventListener("change", sync);
    };
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    const shards: Shard[] = [];
    const pointer = { x: 0, y: 0, px: 0, py: 0, lastSpawn: 0, armed: false };
    let frame = 0;
    let running = true;
    let color: [number, number, number] = [142, 220, 255];

    const readColor = () => {
      color = parseRgb(getComputedStyle(document.documentElement).getPropertyValue("--crystal"));
    };
    readColor();
    const themeObserver = new MutationObserver(readColor);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
      const width = window.innerWidth;
      const height = window.innerHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();

    const onPointer = (event: PointerEvent) => {
      if (event.pointerType === "touch") return;
      if (!pointer.armed) {
        pointer.x = event.clientX;
        pointer.y = event.clientY;
        pointer.px = event.clientX;
        pointer.py = event.clientY;
        pointer.armed = true;
        return;
      }
      pointer.px = pointer.x;
      pointer.py = pointer.y;
      pointer.x = event.clientX;
      pointer.y = event.clientY;
    };

    const tick = (now: number) => {
      if (!running || document.hidden) return;

      const dx = pointer.x - pointer.px;
      const dy = pointer.y - pointer.py;
      const dist = Math.hypot(dx, dy);
      if (pointer.armed && dist >= MIN_MOVE && now - pointer.lastSpawn >= SPAWN_MS) {
        const count = dist > 28 ? 2 : 1;
        for (let i = 0; i < count && shards.length < MAX_SHARDS; i += 1) {
          shards.push(
            makeShard(
              pointer.x + (Math.random() - 0.5) * 10,
              pointer.y + (Math.random() - 0.5) * 10,
              dx,
              dy,
              now,
            ),
          );
        }
        pointer.lastSpawn = now;
        pointer.px = pointer.x;
        pointer.py = pointer.y;
      }

      ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
      for (let i = shards.length - 1; i >= 0; i -= 1) {
        const shard = shards[i];
        if (!shard) continue;
        const age = now - shard.born;
        if (age >= shard.ttl) {
          shards.splice(i, 1);
          continue;
        }
        shard.x += shard.vx;
        shard.y += shard.vy;
        shard.rot += shard.vr;
        const life = 1 - age / shard.ttl;
        const alpha = life * life * 0.55;
        ctx.save();
        ctx.translate(shard.x, shard.y);
        ctx.rotate(shard.rot);
        ctx.beginPath();
        shard.verts.forEach((vert, index) => {
          if (index === 0) ctx.moveTo(vert.x, vert.y);
          else ctx.lineTo(vert.x, vert.y);
        });
        ctx.closePath();
        ctx.fillStyle = `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${alpha * 0.18})`;
        ctx.strokeStyle = `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${alpha})`;
        ctx.lineWidth = 1;
        ctx.fill();
        ctx.stroke();
        ctx.restore();
      }

      frame = window.requestAnimationFrame(tick);
    };

    const onVisibility = () => {
      if (document.hidden) {
        window.cancelAnimationFrame(frame);
        frame = 0;
        return;
      }
      if (running && frame === 0) frame = window.requestAnimationFrame(tick);
    };

    window.addEventListener("pointermove", onPointer, { passive: true });
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", onVisibility);
    frame = window.requestAnimationFrame(tick);

    return () => {
      running = false;
      window.cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onPointer);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
      themeObserver.disconnect();
      shards.length = 0;
    };
  }, [enabled]);

  if (!enabled) return null;
  return <canvas ref={canvasRef} className="crystal-field" aria-hidden="true" />;
}

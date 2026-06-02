// 5-bar mic meter driven by `level` events from the server. The decay loop
// is local to this component (a useRef array + RAF), so it doesn't churn the
// global store on every frame.

import { useEffect, useRef } from "react";
import { useAppStore } from "../state/store";

const BAR_COUNT = 5;
const DECAY = 0.78;

export function MicMeter() {
  const showMeter = useAppStore((s) => s.prefs.showMeter);
  const muted = useAppStore((s) => s.muted);
  const levelRef = useRef(0);
  const barsRef = useRef<(HTMLSpanElement | null)[]>(
    new Array(BAR_COUNT).fill(null),
  );
  const containerRef = useRef<HTMLDivElement | null>(null);
  const meterStateRef = useRef<number[]>(new Array(BAR_COUNT).fill(0));

  // Push level into a ref so the RAF loop can read it without re-rendering.
  useEffect(() => {
    return useAppStore.subscribe((s) => {
      levelRef.current = s.micLevel;
    });
  }, []);

  // Single RAF loop for the entire bar lifetime.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const level = levelRef.current;
      const peak = Math.min(1, level * 4);
      const levels = meterStateRef.current;
      for (let i = 0; i < BAR_COUNT; i++) {
        const distFromCenter = Math.abs(i - (BAR_COUNT - 1) / 2);
        const target = Math.max(0, peak - distFromCenter * 0.18);
        levels[i] = Math.max(target, levels[i] * DECAY);
        const h = 6 + levels[i] * 16;
        const bar = barsRef.current[i];
        if (bar) bar.style.height = h.toFixed(1) + "px";
      }
      const container = containerRef.current;
      if (container) container.classList.toggle("active", peak > 0.05);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // Snap bars flat the moment we go muted.
  useEffect(() => {
    if (!muted) return;
    const levels = meterStateRef.current;
    for (let i = 0; i < BAR_COUNT; i++) {
      levels[i] = 0;
      const bar = barsRef.current[i];
      if (bar) bar.style.height = "6px";
    }
    containerRef.current?.classList.remove("active");
  }, [muted]);

  const className = [
    "mic-meter",
    muted ? "muted" : "",
    !showMeter ? "hidden" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      id="mic-meter"
      ref={containerRef}
      className={className}
      aria-hidden="true"
    >
      {Array.from({ length: BAR_COUNT }, (_, i) => (
        <span
          key={i}
          ref={(el) => (barsRef.current[i] = el)}
          className="bar"
        />
      ))}
    </div>
  );
}

// Mounts the three.js brain into a canvas via a ref and tears it down on
// unmount. The brain controller is exposed via a forward ref so the parent
// can call setScale() in response to mic level events.

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { BrainController, mountBrain } from "../lib/brain";
import { useAppStore } from "../state/store";

export interface OrbHandle {
  brain: BrainController | null;
}

export const OrbContainer = forwardRef<OrbHandle>((_, ref) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const orbRef = useRef<HTMLDivElement | null>(null);
  const brainRef = useRef<BrainController | null>(null);
  const phase = useAppStore((s) => s.phase);

  useEffect(() => {
    if (!canvasRef.current) return;
    const brain = mountBrain(canvasRef.current);
    brainRef.current = brain;
    brain.setPhase(phase);
    return () => {
      brain.dispose();
      brainRef.current = null;
    };
    // Intentionally mount-only: brain lives the entire app lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Phase changes flow into the brain controller.
  useEffect(() => {
    brainRef.current?.setPhase(phase);
  }, [phase]);

  useImperativeHandle(ref, () => ({
    get brain() {
      return brainRef.current;
    },
  }));

  return (
    <div className="orb-wrap">
      <span className="hud-corner tl" aria-hidden="true" />
      <span className="hud-corner tr" aria-hidden="true" />
      <span className="hud-corner bl" aria-hidden="true" />
      <span className="hud-corner br" aria-hidden="true" />
      <span className="hud-ring r1" aria-hidden="true" />
      <span className="hud-ring r2" aria-hidden="true" />
      <span className="hud-ring r3" aria-hidden="true" />
      <div
        id="orb"
        ref={orbRef}
        className={`orb ${phase}`}
        onClick={() => {
          // Tap-to-interrupt is hoisted to App via a click handler that reads
          // store state — kept the markup here for layout, no inline handler.
        }}
      >
        <canvas ref={canvasRef} className="brain-canvas" aria-hidden="true" />
      </div>
    </div>
  );
});
OrbContainer.displayName = "OrbContainer";

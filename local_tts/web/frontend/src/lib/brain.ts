// Three.js holographic brain: point cloud + k-NN line segments + bloom.
// Mounted via useOrb(ref) — imperative for both perf and to avoid binding
// React state to a 60fps RAF loop.

import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";

export type BrainPhase = "idle" | "listening" | "thinking" | "speaking";

// TS 5.6+ tracks the backing-buffer kind on Uint8Array as a generic; the DOM
// AnalyserNode APIs require Uint8Array<ArrayBuffer> specifically (not the
// SharedArrayBuffer variant), so we match that here.
export type FreqBuffer = Uint8Array<ArrayBuffer>;

export interface BrainController {
  setPhase: (phase: BrainPhase) => void;
  setScale: (scale: number) => void;
  setFreq: (buf: FreqBuffer | null) => void;
  dispose: () => void;
}

function generateBrainPoints(count: number): Float32Array {
  const out: number[] = [];
  let attempts = 0;
  const maxAttempts = count * 30;
  while (out.length < count * 3 && attempts < maxAttempts) {
    attempts++;
    const u = Math.random() * 2 - 1;
    const theta = Math.random() * Math.PI * 2;
    const sinPhi = Math.sqrt(1 - u * u);
    const dx = sinPhi * Math.cos(theta);
    const dy = u;
    const dz = sinPhi * Math.sin(theta);

    // Cortical-noise modulation gives the gyri/sulci look.
    const noise =
      Math.sin(dx * 7.0 + dy * 4.0) * 0.06 +
      Math.cos(dz * 6.0 - dy * 3.0) * 0.05 +
      Math.sin(dx * 11.0) * Math.cos(dz * 8.0) * 0.04;
    const r = Math.pow(Math.random(), 0.45) * (1 + noise);
    const x = dx * r * 1.45;
    const y = dy * r * 1.0;
    const z = dz * r * 0.95;

    // Carve a central sulcus along the top midline.
    if (y > 0.32 && Math.abs(z) < 0.1) {
      const depth = (y - 0.32) * 4;
      if (Math.random() < depth * 0.6) continue;
    }
    out.push(x, y, z);
  }
  return new Float32Array(out);
}

function buildConnections(positions: Float32Array, k = 3): Float32Array {
  const n = positions.length / 3;
  const segs: number[] = [];
  const dists: { j: number; d: number }[] = new Array(n);
  for (let i = 0; i < n; i++) {
    const xi = positions[i * 3];
    const yi = positions[i * 3 + 1];
    const zi = positions[i * 3 + 2];
    for (let j = 0; j < n; j++) {
      if (j === i) {
        dists[j] = { j, d: Infinity };
        continue;
      }
      const dx = xi - positions[j * 3];
      const dy = yi - positions[j * 3 + 1];
      const dz = zi - positions[j * 3 + 2];
      dists[j] = { j, d: dx * dx + dy * dy + dz * dz };
    }
    dists.sort((a, b) => a.d - b.d);
    for (let m = 0; m < k; m++) {
      const j = dists[m].j;
      if (i < j) {
        segs.push(xi, yi, zi);
        segs.push(positions[j * 3], positions[j * 3 + 1], positions[j * 3 + 2]);
      }
    }
  }
  return new Float32Array(segs);
}

export function mountBrain(canvas: HTMLCanvasElement): BrainController {
  const renderer = new THREE.WebGLRenderer({
    canvas,
    alpha: true,
    antialias: true,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 0, 4.2);

  const positions = generateBrainPoints(720);
  const connections = buildConnections(positions, 3);

  const pgeo = new THREE.BufferGeometry();
  pgeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const pmat = new THREE.PointsMaterial({
    color: 0x4dd0ff,
    size: 0.045,
    transparent: true,
    opacity: 0.95,
    sizeAttenuation: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const pointsObj = new THREE.Points(pgeo, pmat);

  const lgeo = new THREE.BufferGeometry();
  lgeo.setAttribute("position", new THREE.BufferAttribute(connections, 3));
  const lmat = new THREE.LineBasicMaterial({
    color: 0x4dd0ff,
    transparent: true,
    opacity: 0.18,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const linesObj = new THREE.LineSegments(lgeo, lmat);

  const group = new THREE.Group();
  group.add(pointsObj);
  group.add(linesObj);
  group.rotation.x = 0.18;
  scene.add(group);

  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 1.4, 0.7, 0.05);
  composer.addPass(bloom);

  function fitToCanvas() {
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.floor(rect.width));
    const h = Math.max(1, Math.floor(rect.height));
    renderer.setSize(w, h, false);
    composer.setSize(w, h);
    bloom.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  fitToCanvas();
  const resizeObserver = new ResizeObserver(fitToCanvas);
  resizeObserver.observe(canvas);

  function syncColorFromTheme() {
    const accent = getComputedStyle(document.body)
      .getPropertyValue("--accent")
      .trim();
    if (!accent) return;
    pmat.color.set(accent);
    lmat.color.set(accent);
  }
  syncColorFromTheme();
  const themeObserver = new MutationObserver(syncColorFromTheme);
  themeObserver.observe(document.body, {
    attributes: true,
    attributeFilter: ["class"],
  });

  const PHASE: Record<BrainPhase, { rotSpeed: number; bloom: number; lineOp: number; ptSize: number }> = {
    idle: { rotSpeed: 0.0028, bloom: 1.2, lineOp: 0.16, ptSize: 0.045 },
    listening: { rotSpeed: 0.0055, bloom: 1.4, lineOp: 0.22, ptSize: 0.05 },
    thinking: { rotSpeed: 0.009, bloom: 1.6, lineOp: 0.28, ptSize: 0.052 },
    speaking: { rotSpeed: 0.014, bloom: 2.0, lineOp: 0.34, ptSize: 0.06 },
  };
  let target = PHASE.idle;
  let currentPhase: BrainPhase = "idle";
  let curRot = target.rotSpeed;
  let pulseScale = 1;
  let freqBuf: FreqBuffer | null = null;
  let rafId = 0;
  let disposed = false;

  function tick(t: number) {
    if (disposed) return;
    const lerp = 0.06;
    curRot += (target.rotSpeed - curRot) * lerp;
    bloom.strength += (target.bloom - bloom.strength) * lerp;
    lmat.opacity += (target.lineOp - lmat.opacity) * lerp;
    pmat.size += (target.ptSize - pmat.size) * lerp;
    pulseScale += (1 - pulseScale) * 0.08;

    let scaleBoost = 1;
    let rotBoost = 1;

    if (currentPhase === "thinking") {
      const pulse =
        Math.sin(t * 0.0018) * 0.05 +
        Math.sin(t * 0.0031) * 0.03 +
        Math.sin(t * 0.0053) * 0.015;
      scaleBoost = 1 + pulse;
      bloom.strength = target.bloom + Math.abs(pulse) * 2.2;
    } else if (currentPhase === "speaking" && freqBuf) {
      const n = freqBuf.length;
      const bassEnd = Math.floor(n * 0.12);
      const midEnd = Math.floor(n * 0.45);
      let bass = 0, mid = 0, high = 0;
      for (let i = 0; i < bassEnd; i++) bass += freqBuf[i];
      for (let i = bassEnd; i < midEnd; i++) mid += freqBuf[i];
      for (let i = midEnd; i < n; i++) high += freqBuf[i];
      bass /= bassEnd * 255;
      mid /= (midEnd - bassEnd) * 255;
      high /= (n - midEnd) * 255;

      scaleBoost = 1 + bass * 0.38;
      rotBoost = 1 + mid * 3.2;
      bloom.strength = target.bloom + high * 1.8;
      pmat.size = target.ptSize + high * 0.045;
    }

    group.rotation.y += curRot * rotBoost;
    group.rotation.x = 0.18 + Math.sin(t * 0.0006) * 0.06;
    group.scale.setScalar(pulseScale * scaleBoost);

    composer.render();
    rafId = requestAnimationFrame(tick);
  }
  rafId = requestAnimationFrame(tick);

  return {
    setPhase(phase: BrainPhase) {
      currentPhase = phase;
      target = PHASE[phase] || PHASE.idle;
      if (phase !== "speaking") freqBuf = null;
    },
    setScale(s: number) {
      pulseScale = Math.max(pulseScale, Math.min(1.18, s));
    },
    setFreq(buf: FreqBuffer | null) {
      freqBuf = buf;
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
      themeObserver.disconnect();
      pgeo.dispose();
      lgeo.dispose();
      pmat.dispose();
      lmat.dispose();
      composer.dispose?.();
      renderer.dispose();
    },
  };
}

// local-tts web client: getUserMedia → AudioWorklet (16k Int16) → WS → server
//                       server → Float32@24k → Web Audio playback queue
//                       phase + level events animate the orb
//
// Browser handles echo cancellation natively (no PTT or RMS gates needed).
// Loaded as an ES module so we can dynamic-import three.js for the brain.

const els = {
  orb: document.getElementById("orb"),
  brainCanvas: document.getElementById("brain-canvas"),
  userCaption: document.getElementById("user-caption"),
  aiCaption: document.getElementById("ai-caption"),
  captions: document.getElementById("captions"),
  meter: document.getElementById("mic-meter"),
  meterBars: Array.from(document.querySelectorAll("#mic-meter .bar")),
  timer: document.getElementById("timer"),
  name: document.getElementById("assistant-name"),
  voiceName: document.getElementById("voice-name"),
  model: document.getElementById("model-name"),
  copyBtn: document.getElementById("copy-btn"),
  status: document.getElementById("status-text"),
  muteBtn: document.getElementById("mute-btn"),
  skipBtn: document.getElementById("skip-btn"),
  typeBtn: document.getElementById("type-btn"),
  endBtn: document.getElementById("end-btn"),
  textForm: document.getElementById("text-input-form"),
  textInput: document.getElementById("text-input"),
  settingsBtn: document.getElementById("settings-btn"),
  settingsPanel: document.getElementById("settings-panel"),
  orbSize: document.getElementById("orb-size"),
  orbSizeVal: document.getElementById("orb-size-val"),
  showMeter: document.getElementById("show-meter"),
  showCaptions: document.getElementById("show-captions"),
  micSelect: document.getElementById("mic-select"),
  sttSelect: document.getElementById("stt-select"),
  sttStatus: document.getElementById("stt-status"),
  voiceSelect: document.getElementById("voice-select"),
  voiceStatus: document.getElementById("voice-status"),
  themeSwatches: document.getElementById("theme-swatches"),
};

// Display labels for the STT picker. Keys must stay in sync with
// SUPPORTED_MODELS in local_tts/stt/transcriber.py.
const STT_MODEL_LABELS = {
  "tiny": "Tiny — fastest (<300ms), low accuracy",
  "base": "Base — fast (~300ms)",
  "small": "Small — fast + decent (~300-500ms)",
  "medium": "Medium — balanced (~500-800ms)",
  "large-v3-turbo": "Large v3 Turbo — accurate (~700-1100ms)",
  "large-v3": "Large v3 — max accuracy (~1500-2500ms)",
};

const state = {
  ws: null,
  audioCtx: null,
  micCtx: null,
  micStream: null,
  workletNode: null,
  micSource: null,
  muted: false,
  ended: false,
  paused: false,
  // Set true between a Skip click and the server's `phase: idle` confirmation.
  // While true we drop incoming AI transcripts and audio so a sentence already
  // in flight from the server can't briefly re-populate the cleared caption.
  skipping: false,
  phase: "idle",
  startedAt: null,
  timerHandle: null,
  timerElapsedMs: 0,        // accumulated runtime across pauses
  // playback queue
  outSampleRate: 24000,
  playbackTime: 0,
  scheduledNodes: [],
  speakingAnalyser: null,
  speakingRaf: 0,
  // accumulated AI response (sentences arrive one at a time)
  aiAccum: "",
  // STT model picker state
  sttModel: null,
  sttModelsAvailable: [],
  sttSwapping: false,
  // Kokoro voice picker state
  voice: null,
  voicesAvailable: [],   // [{id, label}]
  voiceSwapping: false,
  // three.js brain controller (set after async init)
  brain: null,
};

// ---------- UI helpers ----------

function setPhase(phase) {
  if (state.ended) return;
  if (state.paused && phase !== "idle") return;
  // Server has finished interrupting — clear the skipping gate so future
  // AI events flow normally again.
  if (state.skipping && phase === "idle") state.skipping = false;
  state.phase = phase;
  els.orb.classList.remove("idle", "listening", "thinking", "speaking");
  els.orb.classList.add(phase);
  // HUD-style status readouts.
  const labels = {
    idle: "STANDBY",
    listening: "LISTENING",
    thinking: "ANALYZING",
    speaking: "TRANSMITTING",
  };
  els.status.textContent = labels[phase] || phase.toUpperCase();
  if (phase !== "speaking") setOrbScale(1);
  // Skip button is only meaningful while AI is responding.
  els.skipBtn.disabled = !(phase === "speaking" || phase === "thinking");
  if (state.brain) state.brain.setPhase(phase);
}

function setUserCaption(text) {
  els.userCaption.textContent = text || "";
  els.userCaption.classList.toggle("show", !!text);
}

function clearAiCaption() {
  els.aiCaption.innerHTML = "";
  els.aiCaption.classList.remove("show");
  state.aiAccum = "";
  if (els.copyBtn) {
    els.copyBtn.hidden = true;
    els.copyBtn.classList.remove("copied");
    const lbl = els.copyBtn.querySelector(".copy-label");
    if (lbl) lbl.textContent = "Copy";
  }
}

function clearCaptions() {
  setUserCaption("");
  clearAiCaption();
}

let userCaptionTimer = null;
function showUserCaption(text) {
  setUserCaption(text);
  if (userCaptionTimer) clearTimeout(userCaptionTimer);
  // Fade away after a few seconds so it doesn't compete with the AI response.
  userCaptionTimer = setTimeout(() => setUserCaption(""), 6000);
}

// AI sentences arrive one-per-message. Render each as its own line that
// fades + slides in (terminal-style streaming output).
function appendAiSentence(text) {
  if (!text) return;
  const line = document.createElement("div");
  line.className = "ai-sentence";
  line.textContent = text;
  els.aiCaption.appendChild(line);
  els.aiCaption.classList.add("show");
  els.aiCaption.scrollTop = els.aiCaption.scrollHeight;
  state.aiAccum = state.aiAccum ? state.aiAccum + " " + text : text;
  if (els.copyBtn) els.copyBtn.hidden = false;
}

// ---------- mic meter ----------

const METER_DECAY = 0.78;
const meterLevels = new Array(els.meterBars.length).fill(0);
function updateMeter(level) {
  // Smooth and stagger across bars; outer bars react less.
  const peak = Math.min(1, level * 4); // input is 0..~0.3 normally
  for (let i = 0; i < meterLevels.length; i++) {
    const distFromCenter = Math.abs(i - (meterLevels.length - 1) / 2);
    const target = Math.max(0, peak - distFromCenter * 0.18);
    meterLevels[i] = Math.max(target, meterLevels[i] * METER_DECAY);
    const h = 6 + meterLevels[i] * 16; // 6..22 px
    els.meterBars[i].style.height = h.toFixed(1) + "px";
  }
  els.meter.classList.toggle("active", peak > 0.05);
}
function resetMeter() {
  for (let i = 0; i < meterLevels.length; i++) meterLevels[i] = 0;
  for (const b of els.meterBars) b.style.height = "6px";
  els.meter.classList.remove("active");
}

function setOrbScale(s) {
  els.orb.style.setProperty("--scale", s.toFixed(3));
  if (state.brain) state.brain.setScale(s);
}

// ---------- Three.js holographic brain ----------
// A point cloud sampled to a brain-shaped distribution + k-nearest-neighbour
// connection lines, rendered with UnrealBloomPass for the JARVIS glow.
// On macOS Safari this runs through Metal under the hood (WebGL → ANGLE/Metal).

function generateBrainPoints(count) {
  const out = [];
  let attempts = 0;
  const maxAttempts = count * 30;
  while (out.length < count * 3 && attempts < maxAttempts) {
    attempts++;
    // Random direction on unit sphere
    const u = Math.random() * 2 - 1;
    const theta = Math.random() * Math.PI * 2;
    const sinPhi = Math.sqrt(1 - u * u);
    const dx = sinPhi * Math.cos(theta);
    const dy = u;
    const dz = sinPhi * Math.sin(theta);

    // Cortical noise (gyri/sulci) — modulates radius
    const noise =
      Math.sin(dx * 7.0 + dy * 4.0) * 0.06 +
      Math.cos(dz * 6.0 - dy * 3.0) * 0.05 +
      Math.sin(dx * 11.0) * Math.cos(dz * 8.0) * 0.04;

    // Surface bias — most points near the cortex, fewer in deep matter
    const r = Math.pow(Math.random(), 0.45) * (1 + noise);

    // Brain proportions: longer front-back than wide
    let x = dx * r * 1.45;
    let y = dy * r * 1.0;
    let z = dz * r * 0.95;

    // Carve a central sulcus along the top midline (separates hemispheres)
    if (y > 0.32 && Math.abs(z) < 0.1) {
      const depth = (y - 0.32) * 4;
      if (Math.random() < depth * 0.6) continue;
    }

    out.push(x, y, z);
  }
  return new Float32Array(out);
}

function buildConnections(positions, k = 3) {
  const n = positions.length / 3;
  const segs = [];
  const dists = new Array(n);
  for (let i = 0; i < n; i++) {
    const xi = positions[i * 3];
    const yi = positions[i * 3 + 1];
    const zi = positions[i * 3 + 2];
    for (let j = 0; j < n; j++) {
      if (j === i) { dists[j] = { j, d: Infinity }; continue; }
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

async function initBrain() {
  const canvas = els.brainCanvas;
  if (!canvas) return null;

  let THREE, EffectComposer, RenderPass, UnrealBloomPass;
  try {
    THREE = await import("three");
    ({ EffectComposer } = await import("three/addons/postprocessing/EffectComposer.js"));
    ({ RenderPass } = await import("three/addons/postprocessing/RenderPass.js"));
    ({ UnrealBloomPass } = await import("three/addons/postprocessing/UnrealBloomPass.js"));
  } catch (e) {
    console.warn("[brain] three.js failed to load:", e);
    return null;
  }

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

  // Brain geometry
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

  // Postprocessing — bloom is what makes this look like a hologram.
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
  new ResizeObserver(fitToCanvas).observe(canvas);

  // Pull the current accent colour from CSS so we follow the active theme.
  function syncColorFromTheme() {
    const accent = getComputedStyle(document.body).getPropertyValue("--accent").trim();
    if (!accent) return;
    pmat.color.set(accent);
    lmat.color.set(accent);
  }
  syncColorFromTheme();
  // Re-sync whenever the body class flips (theme switch).
  new MutationObserver(syncColorFromTheme)
    .observe(document.body, { attributes: true, attributeFilter: ["class"] });

  // Phase tuning. Smoothed each frame so transitions feel organic.
  const PHASE = {
    idle:      { rotSpeed: 0.0028, bloom: 1.2, lineOp: 0.16, ptSize: 0.045 },
    listening: { rotSpeed: 0.0055, bloom: 1.4, lineOp: 0.22, ptSize: 0.05  },
    thinking:  { rotSpeed: 0.012,  bloom: 1.7, lineOp: 0.30, ptSize: 0.055 },
    speaking:  { rotSpeed: 0.014,  bloom: 2.0, lineOp: 0.34, ptSize: 0.06  },
  };
  let target = PHASE.idle;
  let curRot = target.rotSpeed;
  let pulseScale = 1;     // momentary bump from TTS amplitude

  function tick(t) {
    const lerp = 0.06;
    curRot += (target.rotSpeed - curRot) * lerp;
    bloom.strength += (target.bloom - bloom.strength) * lerp;
    lmat.opacity   += (target.lineOp - lmat.opacity) * lerp;
    pmat.size      += (target.ptSize - pmat.size) * lerp;
    pulseScale     += (1 - pulseScale) * 0.08;

    group.rotation.y += curRot;
    group.rotation.x = 0.18 + Math.sin(t * 0.0006) * 0.06;
    group.scale.setScalar(pulseScale);

    composer.render();
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  return {
    setPhase(phase) {
      target = PHASE[phase] || PHASE.idle;
    },
    setScale(s) {
      // Use the audio-driven scale to spike pulseScale; eased back each frame.
      pulseScale = Math.max(pulseScale, Math.min(1.18, s));
    },
  };
}

function startTimer() {
  state.startedAt = Date.now();
  const tick = () => {
    if (!state.startedAt) return;
    const totalMs = state.timerElapsedMs + (Date.now() - state.startedAt);
    const sec = Math.floor(totalMs / 1000);
    const m = String(Math.floor(sec / 60)).padStart(2, "0");
    const s = String(sec % 60).padStart(2, "0");
    els.timer.textContent = `${m}:${s}`;
  };
  tick();
  state.timerHandle = setInterval(tick, 1000);
}

function stopTimer() {
  if (state.timerHandle) clearInterval(state.timerHandle);
  state.timerHandle = null;
  state.startedAt = null;
  state.timerElapsedMs = 0;
}

function pauseTimer() {
  if (state.startedAt) {
    state.timerElapsedMs += Date.now() - state.startedAt;
    state.startedAt = null;
  }
  if (state.timerHandle) clearInterval(state.timerHandle);
  state.timerHandle = null;
}

// ---------- WebSocket ----------

function wsUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws`;
}

async function connect() {
  els.status.textContent = "CONNECTING";
  const ws = new WebSocket(wsUrl());
  ws.binaryType = "arraybuffer";
  state.ws = ws;

  ws.onopen = async () => {
    els.status.textContent = "ONLINE";
    startTimer();
    try {
      await startMic(prefs.micId);
      // Now that permission is granted, device labels become readable.
      refreshMicList();
    } catch (e) {
      console.error(e);
      // Fall back to default if a saved deviceId no longer exists.
      if (prefs.micId) {
        prefs.micId = null;
        savePrefs(prefs);
        try { await startMic(null); refreshMicList(); return; } catch {}
      }
      els.status.textContent = "MIC PERMISSION DENIED";
    }
  };

  ws.onmessage = (ev) => {
    if (typeof ev.data === "string") {
      handleControl(JSON.parse(ev.data));
    } else {
      handleAudio(ev.data);
    }
  };

  ws.onclose = () => {
    if (!state.ended) {
      els.status.textContent = "DISCONNECTED";
    }
  };

  ws.onerror = () => {
    els.status.textContent = "CONNECTION ERROR";
  };
}

function send(obj) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(obj));
  }
}

function handleControl(msg) {
  switch (msg.type) {
    case "config":
      if (msg.voice) updateVoiceLabel(msg.voice);
      if (msg.model) els.model.textContent = msg.model;
      if (msg.output_sample_rate) state.outSampleRate = msg.output_sample_rate;
      if (msg.voices_available) {
        state.voicesAvailable = msg.voices_available;
        populateVoiceSelect(msg.voice);
        const validIds = state.voicesAvailable.map((v) => v.id);
        if (prefs.voice && prefs.voice !== msg.voice
            && validIds.includes(prefs.voice)) {
          requestVoiceSwap(prefs.voice);
        } else {
          state.voice = msg.voice;
        }
      }
      if (msg.stt_models_available) {
        state.sttModelsAvailable = msg.stt_models_available;
        populateSttSelect(msg.stt_model);
        // If user has a saved pref that differs from the server-side default,
        // request a swap once the page is connected.
        if (prefs.sttModel && prefs.sttModel !== msg.stt_model
            && state.sttModelsAvailable.includes(prefs.sttModel)) {
          requestSttSwap(prefs.sttModel);
        } else {
          state.sttModel = msg.stt_model;
        }
      }
      break;
    case "stt_model":
      handleSttModelEvent(msg);
      break;
    case "voice":
      handleVoiceEvent(msg);
      break;
    case "phase":
      setPhase(msg.value);
      break;
    case "transcript":
      if (msg.role === "user") {
        // New user turn — clear the prior AI response from view.
        clearAiCaption();
        showUserCaption(msg.text);
      } else {
        // Drop AI sentences that arrive after a Skip click but before the
        // server's idle confirmation lands.
        if (state.skipping) break;
        appendAiSentence(msg.text);
      }
      break;
    case "level":
      // Drive both the mic meter and a subtle orb pulse while idle/listening.
      updateMeter(msg.value);
      if (state.phase === "idle" || state.phase === "listening") {
        const s = 1 + Math.min(0.18, msg.value * 1.4);
        setOrbScale(s);
      }
      break;
    case "error":
      els.status.textContent = "ERROR: " + msg.message;
      break;
  }
}

// ---------- Audio playback (server → speakers) ----------

function ensureAudioCtx() {
  if (!state.audioCtx) {
    state.audioCtx = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: state.outSampleRate,
    });
    state.playbackTime = state.audioCtx.currentTime;
  }
  return state.audioCtx;
}

function handleAudio(arrayBuf) {
  // Discard audio that's already in flight when the user hits Skip / Pause.
  if (state.skipping || state.paused) return;
  const ctx = ensureAudioCtx();
  const float32 = new Float32Array(arrayBuf);
  const buf = ctx.createBuffer(1, float32.length, state.outSampleRate);
  buf.copyToChannel(float32, 0);

  const src = ctx.createBufferSource();
  src.buffer = buf;

  // Add an analyser so the orb can scale with TTS amplitude.
  if (!state.speakingAnalyser) {
    state.speakingAnalyser = ctx.createAnalyser();
    state.speakingAnalyser.fftSize = 256;
    state.speakingAnalyser.connect(ctx.destination);
    runOrbAnimLoop();
  }
  src.connect(state.speakingAnalyser);

  const startAt = Math.max(ctx.currentTime, state.playbackTime);
  src.start(startAt);
  state.playbackTime = startAt + buf.duration;
  state.scheduledNodes.push(src);
  src.onended = () => {
    state.scheduledNodes = state.scheduledNodes.filter((n) => n !== src);
  };
}

function runOrbAnimLoop() {
  const buf = new Uint8Array(state.speakingAnalyser.frequencyBinCount);
  const tick = () => {
    if (!state.speakingAnalyser) return;
    state.speakingAnalyser.getByteTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) {
      const v = (buf[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / buf.length);
    if (state.phase === "speaking") {
      const s = 1 + Math.min(0.32, rms * 2.4);
      setOrbScale(s);
    }
    state.speakingRaf = requestAnimationFrame(tick);
  };
  tick();
}

function stopAllPlayback() {
  for (const n of state.scheduledNodes) {
    try { n.stop(); } catch {}
  }
  state.scheduledNodes = [];
  if (state.audioCtx) state.playbackTime = state.audioCtx.currentTime;
}

// ---------- Mic capture (browser → server) ----------

async function startMic(deviceId) {
  const audioConstraints = {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
    channelCount: 1,
  };
  if (deviceId) audioConstraints.deviceId = { exact: deviceId };

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: audioConstraints,
    video: false,
  });
  state.micStream = stream;

  // Use a separate AudioContext for capture so we can run at the device's
  // native rate; the worklet downsamples to 16k for the server.
  const micCtx = new (window.AudioContext || window.webkitAudioContext)();
  state.micCtx = micCtx;

  await micCtx.audioWorklet.addModule("/static/recorder.worklet.js");

  const source = micCtx.createMediaStreamSource(stream);
  state.micSource = source;

  const node = new AudioWorkletNode(micCtx, "recorder-processor", {
    processorOptions: { targetRate: 16000 },
  });
  node.port.onmessage = (ev) => {
    if (state.muted) return;
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(ev.data);
    }
  };
  source.connect(node);
  // Don't connect node to destination — we only want the data, not audible monitoring.
  state.workletNode = node;
}

function stopMic() {
  if (state.workletNode) try { state.workletNode.disconnect(); } catch {}
  if (state.micSource) try { state.micSource.disconnect(); } catch {}
  if (state.micStream) state.micStream.getTracks().forEach((t) => t.stop());
  if (state.micCtx) try { state.micCtx.close(); } catch {}
  state.workletNode = null;
  state.micSource = null;
  state.micStream = null;
  state.micCtx = null;
}

// ---------- Buttons ----------

els.muteBtn.addEventListener("click", () => {
  state.muted = !state.muted;
  els.muteBtn.classList.toggle("muted", state.muted);
  els.muteBtn.querySelector("span").textContent = state.muted ? "Unmute" : "Mute";
  els.meter.classList.toggle("muted", state.muted);
  if (state.muted) resetMeter();
  send({ type: state.muted ? "mute" : "unmute" });
  els.status.textContent = state.muted ? "MUTED" : "LISTENING";
});

els.endBtn.addEventListener("click", () => {
  togglePause();
});

// Skip current AI response (interrupt + drain local playback).
function skipCurrent() {
  state.skipping = true;
  stopAllPlayback();
  send({ type: "interrupt" });
  clearAiCaption();
  els.skipBtn.disabled = true;
  els.status.textContent = "SKIPPING";
}
els.skipBtn.addEventListener("click", skipCurrent);

if (els.copyBtn) {
  els.copyBtn.addEventListener("click", async () => {
    if (!state.aiAccum) return;
    const lbl = els.copyBtn.querySelector(".copy-label");
    try {
      await navigator.clipboard.writeText(state.aiAccum);
      els.copyBtn.classList.add("copied");
      if (lbl) lbl.textContent = "Copied";
      setTimeout(() => {
        els.copyBtn.classList.remove("copied");
        if (lbl) lbl.textContent = "Copy";
      }, 1400);
    } catch {
      if (lbl) lbl.textContent = "Failed";
      setTimeout(() => { if (lbl) lbl.textContent = "Copy"; }, 1400);
    }
  });
}

// Type-button popover: click to expand into a text input, Esc/blur to close.
function openTextInput() {
  if (state.ended) return;
  els.textForm.hidden = false;
  els.typeBtn.classList.add("active");
  // Wait a frame so the unhide takes effect before we focus.
  requestAnimationFrame(() => els.textInput.focus());
}
function closeTextInput() {
  els.textForm.hidden = true;
  els.typeBtn.classList.remove("active");
  els.textInput.blur();
}
els.typeBtn.addEventListener("click", () => {
  if (els.textForm.hidden) openTextInput();
  else closeTextInput();
});
els.textInput.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeTextInput();
});
// Close popover when clicking outside it.
document.addEventListener("click", (e) => {
  if (els.textForm.hidden) return;
  if (els.textForm.contains(e.target) || els.typeBtn.contains(e.target)) return;
  closeTextInput();
});

// Submit text — bypasses STT, still streams a voice response.
els.textForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = els.textInput.value.trim();
  if (!text || state.ended) return;
  if (state.phase === "speaking" || state.phase === "thinking") {
    skipCurrent();
  }
  send({ type: "text_input", text });
  els.textInput.value = "";
  closeTextInput();
});

// Pause stops mic + playback + AI generation and freezes the timer, but keeps
// the WebSocket open so a single click resumes the call where it left off.
const PAUSE_ICON_SVG = `
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <rect x="6" y="5" width="4" height="14" rx="1"/>
    <rect x="14" y="5" width="4" height="14" rx="1"/>
  </svg>`;
const RESUME_ICON_SVG = `
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <polygon points="6 4 20 12 6 20 6 4"/>
  </svg>`;

function setPauseButtonState(paused) {
  const label = els.endBtn.querySelector("span");
  const oldSvg = els.endBtn.querySelector("svg");
  if (oldSvg) oldSvg.remove();
  els.endBtn.insertAdjacentHTML(
    "afterbegin",
    paused ? RESUME_ICON_SVG : PAUSE_ICON_SVG,
  );
  if (label) label.textContent = paused ? "Resume" : "Pause";
  els.endBtn.setAttribute("aria-label", paused ? "Resume call" : "Pause call");
  els.endBtn.classList.toggle("paused", paused);
}

async function togglePause() {
  if (state.ended) return;
  if (!state.paused) {
    state.paused = true;
    stopAllPlayback();
    send({ type: "interrupt" });
    stopMic();
    pauseTimer();
    setPhase("idle");
    setPauseButtonState(true);
    els.status.textContent = "PAUSED";
    els.muteBtn.disabled = true;
    els.skipBtn.disabled = true;
    els.typeBtn.disabled = true;
    if (!els.textForm.hidden) closeTextInput();
    document.body.classList.add("paused");
  } else {
    state.paused = false;
    document.body.classList.remove("paused");
    setPauseButtonState(false);
    els.muteBtn.disabled = false;
    els.typeBtn.disabled = false;
    // Skip stays disabled until the AI is actually responding again.
    try {
      await startMic(prefs.micId);
    } catch (e) {
      console.warn("[pause] resume mic failed:", e);
    }
    startTimer();
    els.status.textContent = state.muted ? "MUTED" : "LISTENING";
  }
}

// Tap-to-interrupt on the orb (also useful when audio is playing)
els.orb.addEventListener("click", () => {
  if (state.phase === "speaking" || state.phase === "thinking") {
    stopAllPlayback();
    send({ type: "interrupt" });
  }
});

// ---------- Settings ----------

const PREFS_KEY = "local-tts.prefs.v4";
const THEMES = ["jarvis", "hacker", "amber"];
const defaultPrefs = {
  orbSize: 240,
  showMeter: true,
  showCaptions: true,
  theme: "jarvis",
  micId: null,            // null = browser default
  sttModel: null,         // null = use whatever the server has loaded
  voice: null,            // null = use whatever the server has loaded
};

function loadPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    return raw ? { ...defaultPrefs, ...JSON.parse(raw) } : { ...defaultPrefs };
  } catch {
    return { ...defaultPrefs };
  }
}
function savePrefs(p) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch {}
}

const prefs = loadPrefs();

function applyTheme(name) {
  if (!THEMES.includes(name)) name = "jarvis";
  for (const t of THEMES) document.body.classList.remove("theme-" + t);
  document.body.classList.add("theme-" + name);
  for (const card of els.themeSwatches.querySelectorAll(".theme-card")) {
    const active = card.dataset.theme === name;
    card.classList.toggle("active", active);
    card.setAttribute("aria-checked", active ? "true" : "false");
  }
  prefs.theme = name;
}

function applyPrefs() {
  document.documentElement.style.setProperty("--orb-size", prefs.orbSize + "px");
  els.orbSize.value = prefs.orbSize;
  els.orbSizeVal.textContent = prefs.orbSize;
  els.showMeter.checked = prefs.showMeter;
  els.showCaptions.checked = prefs.showCaptions;
  els.meter.classList.toggle("hidden", !prefs.showMeter);
  els.captions.classList.toggle("hidden", !prefs.showCaptions);
  applyTheme(prefs.theme);
}
applyPrefs();

els.settingsBtn.addEventListener("click", () => {
  els.settingsPanel.hidden = !els.settingsPanel.hidden;
  if (!els.settingsPanel.hidden) refreshMicList();
});
document.addEventListener("click", (e) => {
  if (els.settingsPanel.hidden) return;
  if (els.settingsPanel.contains(e.target) || els.settingsBtn.contains(e.target)) return;
  els.settingsPanel.hidden = true;
});

els.orbSize.addEventListener("input", () => {
  prefs.orbSize = parseInt(els.orbSize.value, 10);
  els.orbSizeVal.textContent = prefs.orbSize;
  document.documentElement.style.setProperty("--orb-size", prefs.orbSize + "px");
  savePrefs(prefs);
});
els.showMeter.addEventListener("change", () => {
  prefs.showMeter = els.showMeter.checked;
  els.meter.classList.toggle("hidden", !prefs.showMeter);
  savePrefs(prefs);
});
els.showCaptions.addEventListener("change", () => {
  prefs.showCaptions = els.showCaptions.checked;
  els.captions.classList.toggle("hidden", !prefs.showCaptions);
  savePrefs(prefs);
});

els.themeSwatches.addEventListener("click", (e) => {
  const card = e.target.closest(".theme-card");
  if (!card) return;
  applyTheme(card.dataset.theme);
  savePrefs(prefs);
});

// ---------- STT model picker ----------

function populateSttSelect(activeModel) {
  if (!els.sttSelect) return;
  els.sttSelect.innerHTML = "";
  for (const name of state.sttModelsAvailable) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = STT_MODEL_LABELS[name] || name;
    els.sttSelect.appendChild(opt);
  }
  if (activeModel && state.sttModelsAvailable.includes(activeModel)) {
    els.sttSelect.value = activeModel;
  }
}

function setSttStatus(text, kind) {
  if (!els.sttStatus) return;
  els.sttStatus.textContent = text || "";
  els.sttStatus.classList.remove("loading", "error");
  if (kind) els.sttStatus.classList.add(kind);
}

function requestSttSwap(name) {
  if (!name || name === state.sttModel) return;
  state.sttSwapping = true;
  els.sttSelect.disabled = true;
  setSttStatus("loading…", "loading");
  send({ type: "set_stt_model", model: name });
}

function handleSttModelEvent(msg) {
  switch (msg.state) {
    case "loading":
      state.sttSwapping = true;
      els.sttSelect.disabled = true;
      setSttStatus("loading " + msg.model + "…", "loading");
      break;
    case "ready":
      state.sttSwapping = false;
      state.sttModel = msg.model;
      els.sttSelect.disabled = false;
      els.sttSelect.value = msg.model;
      setSttStatus("ready", "");
      // Persist after the server confirms the swap actually succeeded.
      prefs.sttModel = msg.model;
      savePrefs(prefs);
      // Clear the "ready" hint after a moment so the row goes quiet.
      setTimeout(() => setSttStatus("", ""), 1400);
      break;
    case "error":
      state.sttSwapping = false;
      els.sttSelect.disabled = false;
      // Roll the dropdown back to whatever's actually loaded.
      if (state.sttModel) els.sttSelect.value = state.sttModel;
      setSttStatus(msg.message || "swap failed", "error");
      break;
  }
}

if (els.sttSelect) {
  els.sttSelect.addEventListener("change", () => {
    requestSttSwap(els.sttSelect.value);
  });
}

// ---------- Voice (Kokoro TTS) picker ----------

function updateVoiceLabel(voice) {
  if (!voice) return;
  // Strip the lang/gender prefix (af_, am_, bf_, bm_, ...) for the header.
  const pretty = voice.replace(/^[abefhijpz][fm]_/, "");
  const display = pretty.charAt(0).toUpperCase() + pretty.slice(1);
  if (els.voiceName) els.voiceName.textContent = display;
  document.title = `Second Brain · ${display}`;
}

function populateVoiceSelect(activeVoice) {
  if (!els.voiceSelect) return;
  els.voiceSelect.innerHTML = "";
  for (const { id, label } of state.voicesAvailable) {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = label;
    els.voiceSelect.appendChild(opt);
  }
  const ids = state.voicesAvailable.map((v) => v.id);
  if (activeVoice && ids.includes(activeVoice)) {
    els.voiceSelect.value = activeVoice;
  }
}

function setVoiceStatus(text, kind) {
  if (!els.voiceStatus) return;
  els.voiceStatus.textContent = text || "";
  els.voiceStatus.classList.remove("loading", "error");
  if (kind) els.voiceStatus.classList.add(kind);
}

function requestVoiceSwap(name) {
  if (!name || name === state.voice) return;
  state.voiceSwapping = true;
  els.voiceSelect.disabled = true;
  setVoiceStatus("loading…", "loading");
  send({ type: "set_voice", voice: name });
}

function handleVoiceEvent(msg) {
  switch (msg.state) {
    case "loading":
      state.voiceSwapping = true;
      els.voiceSelect.disabled = true;
      setVoiceStatus("loading…", "loading");
      break;
    case "ready":
      state.voiceSwapping = false;
      state.voice = msg.voice;
      els.voiceSelect.disabled = false;
      els.voiceSelect.value = msg.voice;
      updateVoiceLabel(msg.voice);
      setVoiceStatus("ready", "");
      prefs.voice = msg.voice;
      savePrefs(prefs);
      setTimeout(() => setVoiceStatus("", ""), 1400);
      break;
    case "error":
      state.voiceSwapping = false;
      els.voiceSelect.disabled = false;
      if (state.voice) els.voiceSelect.value = state.voice;
      setVoiceStatus(msg.message || "swap failed", "error");
      break;
  }
}

if (els.voiceSelect) {
  els.voiceSelect.addEventListener("change", () => {
    requestVoiceSwap(els.voiceSelect.value);
  });
}

// ---------- Microphone selection ----------

async function refreshMicList() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  let devices = [];
  try {
    devices = await navigator.mediaDevices.enumerateDevices();
  } catch { return; }
  const inputs = devices.filter((d) => d.kind === "audioinput");

  // Determine which device is currently active (so the dropdown reflects reality).
  let activeId = "";
  if (state.micStream) {
    const track = state.micStream.getAudioTracks()[0];
    activeId = track?.getSettings?.().deviceId || "";
  }

  els.micSelect.innerHTML = "";
  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = "System default";
  els.micSelect.appendChild(defaultOpt);

  for (const d of inputs) {
    const opt = document.createElement("option");
    opt.value = d.deviceId;
    opt.textContent = d.label || `Microphone (${d.deviceId.slice(0, 6)})`;
    els.micSelect.appendChild(opt);
  }

  // Prefer saved pref if it still exists; else current active; else default.
  const savedExists = inputs.some((d) => d.deviceId === prefs.micId);
  if (savedExists) els.micSelect.value = prefs.micId;
  else if (inputs.some((d) => d.deviceId === activeId)) els.micSelect.value = activeId;
  else els.micSelect.value = "";
}

els.micSelect.addEventListener("change", async () => {
  const id = els.micSelect.value || null;
  prefs.micId = id;
  savePrefs(prefs);
  if (state.ended) return;
  // Restart capture with the new device.
  stopMic();
  try {
    await startMic(id);
    els.status.textContent = state.muted ? "MUTED" : "LISTENING";
  } catch (e) {
    console.error(e);
    els.status.textContent = "MIC ERROR: " + e.message;
  }
});

// Keep the list fresh when devices come and go (AirPods connect/disconnect, etc.)
if (navigator.mediaDevices?.addEventListener) {
  navigator.mediaDevices.addEventListener("devicechange", refreshMicList);
}

// ---------- Boot ----------

document.addEventListener("visibilitychange", () => {
  // No-op for now; could pause mic when hidden.
});

// Kick off three.js brain in parallel with the websocket connect — the
// websocket doesn't need to wait for the GPU pipeline to be ready.
initBrain().then((brain) => {
  state.brain = brain;
  if (brain) brain.setPhase(state.phase);
});

connect();

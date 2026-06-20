import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { useAudioData, visualizeAudioWaveform } from "@remotion/media-utils";
import { COLORS, display, mono } from "./theme";

// ── shared helpers ──────────────────────────────────────────────────────────

const fadeUp = (frame: number, fps: number, delay = 0) => {
  const s = spring({ frame: frame - delay, fps, config: { damping: 200 }, durationInFrames: 24 });
  return { opacity: s, transform: `translateY(${interpolate(s, [0, 1], [16, 0])}px)` };
};

const Wordmark: React.FC<{ size: number }> = ({ size }) => (
  <span style={{ fontFamily: display, fontWeight: 700, fontSize: size, letterSpacing: -1 }}>
    <span style={{ color: COLORS.text }}>read</span>
    <span style={{ color: COLORS.accent }}>back</span>
  </span>
);

const Grain: React.FC = () => (
  // faint hairline frame, echoing the Ghost "terminal canvas"
  <AbsoluteFill
    style={{ border: `1px solid ${COLORS.line}`, margin: 28, borderRadius: 8 }}
  />
);

// ── scene 1 · hero ──────────────────────────────────────────────────────────

const Hero: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", gap: 26 }}>
      <div style={fadeUp(frame, fps, 0)}>
        <Wordmark size={120} />
      </div>
      <div
        style={{
          ...fadeUp(frame, fps, 10),
          fontFamily: mono,
          color: COLORS.dim,
          fontSize: 26,
          textAlign: "center",
          maxWidth: 880,
          lineHeight: 1.5,
        }}
      >
        Paste a URL or snap a book —{" "}
        <span style={{ color: COLORS.text }}>hear it read aloud</span> by a neural
        voice, entirely on your Mac.
      </div>
      <div style={{ ...fadeUp(frame, fps, 22), fontFamily: mono, color: COLORS.accent, fontSize: 18 }}>
        100% offline · Apple Silicon · CSM-1B
      </div>
    </AbsoluteFill>
  );
};

// ── scene 2 · pipeline ──────────────────────────────────────────────────────

const STAGES: Array<{ label: string; sub: string; color: string }> = [
  { label: "URL · image · book", sub: "your source", color: COLORS.text },
  { label: "extract", sub: "trafilatura · vision OCR", color: COLORS.accent },
  { label: "summarize", sub: "local LLM · optional", color: COLORS.accent },
  { label: "synthesize", sub: "CSM-1B neural TTS", color: COLORS.accent },
  { label: "play", sub: "in your terminal", color: COLORS.green },
];

const Pipeline: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", flexDirection: "column", gap: 40 }}>
      <div style={{ ...fadeUp(frame, fps, 0), fontFamily: display, color: COLORS.text, fontSize: 34 }}>
        how it works
      </div>
      <div style={{ display: "flex", alignItems: "stretch", gap: 14 }}>
        {STAGES.map((st, i) => {
          const delay = 14 + i * 16;
          return (
            <React.Fragment key={st.label}>
              <div
                style={{
                  ...fadeUp(frame, fps, delay),
                  fontFamily: mono,
                  background: COLORS.panel,
                  border: `1px solid ${COLORS.line}`,
                  borderRadius: 8,
                  padding: "20px 22px",
                  width: 200,
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                <span style={{ color: st.color, fontSize: 22, fontWeight: 600 }}>{st.label}</span>
                <span style={{ color: COLORS.dim, fontSize: 15, lineHeight: 1.35 }}>{st.sub}</span>
              </div>
              {i < STAGES.length - 1 && (
                <div
                  style={{
                    ...fadeUp(frame, fps, delay + 8),
                    color: COLORS.accent,
                    fontFamily: mono,
                    fontSize: 26,
                    display: "flex",
                    alignItems: "center",
                  }}
                >
                  →
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
      <div style={{ ...fadeUp(frame, fps, 110), fontFamily: mono, color: COLORS.dim, fontSize: 18 }}>
        no cloud · no API keys · nothing leaves your machine
      </div>
    </AbsoluteFill>
  );
};

// ── scene 3 · terminal mock ─────────────────────────────────────────────────

const URL_TEXT = "https://example.com/the-transformer-explained";
const PHASES: Array<{ at: number; text: string; color: string }> = [
  { at: 46, text: "⠋ loading models", color: COLORS.dim },
  { at: 58, text: "⠙ fetching article", color: COLORS.dim },
  { at: 70, text: "⠹ summarizing", color: COLORS.dim },
  { at: 82, text: "⠸ synthesizing", color: COLORS.accent },
];

const Terminal: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const typed = Math.min(URL_TEXT.length, Math.max(0, Math.floor((frame - 6) / 1.4)));
  const caretOn = Math.floor(frame / 8) % 2 === 0;
  const showBar = frame > 88;
  const barPct = interpolate(frame, [88, 102], [0, 100], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <div
        style={{
          ...fadeUp(frame, fps, 0),
          fontFamily: mono,
          background: COLORS.panel,
          border: `1px solid ${COLORS.lineHi}`,
          borderRadius: 10,
          width: 920,
          padding: 28,
          boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
        }}
      >
        <div style={{ display: "flex", gap: 8, marginBottom: 22 }}>
          <Dot c={COLORS.red} /> <Dot c={COLORS.yellow} /> <Dot c={COLORS.green} />
          <span style={{ color: COLORS.dim, fontSize: 15, marginLeft: 12 }}>readback-cli</span>
        </div>

        <div style={{ fontSize: 22, lineHeight: 1.7 }}>
          <span style={{ color: COLORS.accent }}>❯ </span>
          <span style={{ color: COLORS.text }}>{URL_TEXT.slice(0, typed)}</span>
          {typed < URL_TEXT.length && caretOn && (
            <span style={{ color: COLORS.accent }}>▋</span>
          )}
        </div>

        <div style={{ marginTop: 14, fontSize: 19, display: "flex", flexDirection: "column", gap: 6 }}>
          {PHASES.map((p) =>
            frame >= p.at ? (
              <span key={p.text} style={{ color: p.color }}>
                {p.text}
              </span>
            ) : null,
          )}
          {showBar && (
            <span style={{ color: COLORS.accent }}>
              {"━".repeat(Math.round(barPct / 4))}
              <span style={{ color: COLORS.line }}>{"─".repeat(25 - Math.round(barPct / 4))}</span>{" "}
              {Math.round(barPct)}%
            </span>
          )}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Dot: React.FC<{ c: string }> = ({ c }) => (
  <span style={{ width: 13, height: 13, borderRadius: "50%", background: c, display: "inline-block" }} />
);

// ── scene 4 · waveform (the real sample read) ───────────────────────────────

const Waveform: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  const audioData = useAudioData(staticFile("sample-read.wav"));

  const bars = 80;
  // Time-domain waveform (centered, symmetric) reads as "audio playing" far
  // better than an FFT spectrum (which piles all the energy into the low bins).
  const values = audioData
    ? visualizeAudioWaveform({ fps, frame, audioData, numberOfSamples: bars, windowInSeconds: 1.2 })
    : new Array(bars).fill(0);

  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", flexDirection: "column", gap: 36 }}>
      <Audio src={staticFile("sample-read.wav")} startFrom={30} volume={0.9} />
      <div style={{ ...fadeUp(frame, fps, 0), fontFamily: display, color: COLORS.text, fontSize: 30 }}>
        the actual read — a CSM-1B neural voice
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 4, height: 240, opacity: interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }) }}>
        {values.map((v, i) => {
          const h = Math.max(6, Math.min(230, Math.abs(v) * 900));
          return (
            <div
              key={i}
              style={{
                width: (width * 0.62) / bars - 4,
                height: h,
                background: i % 6 === 0 ? COLORS.accentHi : COLORS.accent,
                borderRadius: 4,
              }}
            />
          );
        })}
      </div>
      <div style={{ fontFamily: mono, color: COLORS.dim, fontSize: 18 }}>
        played in your shell via <span style={{ color: COLORS.text }}>afplay</span> · seek · transcript sync
      </div>
    </AbsoluteFill>
  );
};

// ── scene 5 · outro ─────────────────────────────────────────────────────────

const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", gap: 22 }}>
      <div style={fadeUp(frame, fps, 0)}>
        <Wordmark size={88} />
      </div>
      <div style={{ ...fadeUp(frame, fps, 8), fontFamily: mono, color: COLORS.dim, fontSize: 22 }}>
        offline article reader · <span style={{ color: COLORS.accent }}>github.com/MKS-01/readback</span>
      </div>
    </AbsoluteFill>
  );
};

// ── timeline ────────────────────────────────────────────────────────────────

export const Explainer: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: COLORS.bg }}>
      <Grain />
      <Sequence durationInFrames={80}>
        <Hero />
      </Sequence>
      <Sequence from={80} durationInFrames={130}>
        <Pipeline />
      </Sequence>
      <Sequence from={210} durationInFrames={110}>
        <Terminal />
      </Sequence>
      <Sequence from={320} durationInFrames={85}>
        <Waveform />
      </Sequence>
      <Sequence from={405} durationInFrames={45}>
        <Outro />
      </Sequence>
    </AbsoluteFill>
  );
};

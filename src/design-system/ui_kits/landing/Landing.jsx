/* readback landing page — recreation of src/landing-page. "The page is the
   terminal." Composes Wordmark, SectionHeader, Button, WaveformPlayer.
   Loaded as a Babel script; exposes Landing on window. */

const NS = () => window.ReadbackDesignSystem_7af2ab;

const FEATURES = [
  ["offline", "100% on-device", "extraction, summary & speech run on Apple Silicon. No cloud, no API keys."],
  ["sources", "Snap a book, hear the chapter", "read a URL, an image, or a folder of page photos; a local vision model OCRs them into one continuous read."],
  ["voice", "A voice worth listening to", "CSM-1B neural TTS (Sesame); clone any voice from a short clip, or LoRA fine-tune."],
  ["modes", "Full or Summary", "verbatim, or a local Ollama LLM rewrites it as a spoken explanation; /model fits your RAM."],
  ["player", "A real player", "pause, seek ±5 s, and a transcript that highlights word by word — in your shell or the web dashboard."],
  ["library", "Replay anytime", "every read saved to a searchable SQLite library."],
  ["network", "Run it on your network", "deploy the dashboard to a Raspberry Pi and replay from any device at home."],
];

function Hero() {
  const { Wordmark, Button } = NS();
  return (
    <header style={{ textAlign: "center", position: "relative" }}>
      <div style={{ position: "absolute", left: "50%", top: 50, width: "min(560px,96%)", height: 280, transform: "translateX(-50%)", background: "radial-gradient(ellipse at center, rgba(77,163,255,0.13), transparent 68%)", pointerEvents: "none", zIndex: -1 }} />
      <p style={{ fontFamily: "var(--font-display)", fontSize: "var(--text-sm)", letterSpacing: "0.03em", color: "var(--dim)", marginBottom: 26 }}>
        <span style={{ color: "var(--accent)" }}>//</span> a weekend project · built with Claude Code
      </p>
      <div style={{ display: "flex", justifyContent: "center" }}>
        <Wordmark height={64} src="../../assets/wordmark.png" />
      </div>
      <h1 style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "var(--text-xl)", lineHeight: 1.3, marginTop: 26, color: "var(--text)" }}>
        Make reading interesting again.
      </h1>
      <p style={{ color: "var(--dim)", maxWidth: 540, margin: "16px auto 0" }}>
        Articles and books, read aloud by a neural voice — <span style={{ color: "var(--text)", fontWeight: 500 }}>entirely on your Mac.</span>
      </p>
      <div style={{ marginTop: 36, display: "flex", gap: 14, justifyContent: "center", flexWrap: "wrap" }}>
        <Button variant="accent" href="#">GitHub ↗</Button>
        <Button href="#">Quick start</Button>
      </div>
    </header>
  );
}

function FeatureTerm() {
  return (
    <div style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "20px 22px", fontSize: "var(--text-base)", fontFamily: "var(--font-mono)" }}>
      <p style={{ fontSize: "var(--text-base)", marginBottom: 16, color: "var(--dim)" }}>
        <span style={{ color: "var(--dim)" }}>~ $</span> readback <span style={{ color: "var(--accent)" }}>--features</span>
        <span style={{ display: "inline-block", width: 9, height: 3, marginLeft: 4, background: "var(--accent)", animation: "rb-blink 1.1s steps(1) infinite", verticalAlign: "baseline" }} />
      </p>
      <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 13, margin: 0, padding: 0 }}>
        {FEATURES.map(([key, head, desc]) => (
          <li key={key} style={{ display: "grid", gridTemplateColumns: "auto 82px 1fr", gap: "0 12px", alignItems: "baseline" }}>
            <span style={{ color: "var(--green)" }}>✓</span>
            <span style={{ fontFamily: "var(--font-display)", fontSize: "var(--text-xs)", letterSpacing: "0.02em", color: "var(--accent)" }}>{key}</span>
            <span style={{ color: "var(--dim)", lineHeight: 1.6 }}>
              <span style={{ color: "var(--text)" }}>{head}</span> — {desc}
            </span>
          </li>
        ))}
      </ul>
      <p style={{ marginTop: 16, paddingTop: 13, borderTop: "1px solid var(--line)", fontSize: "var(--text-sm)", color: "var(--green)" }}>
        7 features <span style={{ color: "var(--dim)" }}>·</span> 0 cloud calls <span style={{ color: "var(--dim)" }}>·</span> 0 API keys
      </p>
    </div>
  );
}

function Landing() {
  const { SectionHeader, WaveformPlayer, Button, PromptLine } = NS();
  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "64px 24px 48px" }}>
      <Hero />

      <section style={{ marginTop: 104 }}>
        <SectionHeader>Hear it</SectionHeader>
        <p style={{ color: "var(--dim)", fontSize: "var(--text-base)" }}>
          A real Summary-mode read — local LLM + CSM-1B, in <span style={{ color: "var(--text)", fontWeight: 500 }}>codeword</span>, a custom-tuned clone voice.
        </p>
        <WaveformPlayer duration={111} />
      </section>

      <section style={{ marginTop: 104 }}>
        <SectionHeader>Features</SectionHeader>
        <FeatureTerm />
      </section>

      <section style={{ marginTop: 104 }}>
        <SectionHeader>Dive in</SectionHeader>
        <p style={{ color: "var(--dim)", fontSize: "var(--text-base)", marginBottom: 22 }}>
          Install steps, the pipeline, the architecture, and the full build story — all on GitHub.
        </p>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
          <Button variant="accent" href="#">Quick start ↗</Button>
          <Button href="#">Run it on a Pi ↗</Button>
          <Button href="#">Architecture ↗</Button>
        </div>
      </section>

      <footer style={{ marginTop: 104, borderTop: "1px solid var(--line)", paddingTop: 28, textAlign: "center" }}>
        <p><a href="#" style={{ color: "var(--accent)" }}>GitHub</a> · <a href="#" style={{ color: "var(--accent)" }}>MIT License</a></p>
        <p style={{ color: "var(--dim)", fontSize: "var(--text-base)", marginTop: 8 }}>Open source · built on Apple Silicon · MLX / Metal</p>
        <div style={{ display: "flex", justifyContent: "center", marginTop: 26 }}>
          <PromptLine cwd="~" command="" />
        </div>
      </footer>
    </main>
  );
}

window.Landing = Landing;

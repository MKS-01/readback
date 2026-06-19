/* readback terminal CLI — recreation of the Ink terminal client (src/cli).
   Renders the real screens (input · player · /model · /lib · /help) as terminal
   text inside a macOS terminal window. Composes Wordmark (ascii) + Badge.
   Loaded as a Babel script; exposes Terminal on window. */

const NS = () => window.ReadbackDesignSystem_7af2ab;

const C = {
  fg: "var(--text)", dim: "var(--dim)", blue: "var(--accent)",
  green: "var(--green)", red: "var(--red)", yellow: "var(--yellow)",
};

function fmt(sec) {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// ── header shared by every screen ──────────────────────────────
function Banner({ intro }) {
  const { Wordmark } = NS();
  return (
    <div style={{ padding: "0 4px" }}>
      <Wordmark variant="ascii" height={46} />
      <div style={{ marginTop: 12 }}>
        <span style={{ color: C.dim }}>offline article reader · </span>
        <span style={{ color: C.blue }}>v3.6.0</span>
      </div>
      {intro && (
        <div style={{ marginTop: 12, color: C.dim }}>
          <div>turn any article or image into spoken audio — all on-device.</div>
          <div style={{ marginTop: 12 }}>
            paste a <span style={{ color: C.fg }}>URL</span>, <span style={{ color: C.fg }}>image</span>, or <span style={{ color: C.fg }}>folder</span> ·{" "}
            <span style={{ color: C.blue }}>/lib</span> · <span style={{ color: C.blue }}>/voice</span> · <span style={{ color: C.blue }}>/model</span> · <span style={{ color: C.blue }}>/mode</span> · <span style={{ color: C.blue }}>/help</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── input screen ───────────────────────────────────────────────
function InputScreen() {
  return (
    <div>
      <Banner intro />
      <div style={{ marginTop: 18, border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "8px 12px", display: "flex", alignItems: "center" }}>
        <span style={{ color: C.blue }}>❯&nbsp;</span>
        <span style={{ color: C.dim }}>Paste a URL or image path…  (/help for commands)</span>
        <span style={{ display: "inline-block", width: 9, height: 3, marginLeft: 6, background: C.blue, animation: "rb-blink 1.1s steps(1) infinite" }} />
      </div>
    </div>
  );
}

// ── player screen (live clock) ─────────────────────────────────
const TRANSCRIPT = "So, I was just reading this interesting piece about bug bounty programs and how they work to help companies stay secure. Basically, as technology changes so fast with new features and AI, it becomes really hard for a single internal team to catch every single vulnerability or security flaw. That is where bug bounties come in.";

function PlayerScreen({ t, playing, onToggle, duration }) {
  const barW = 52;
  const pos = Math.min(t / duration, 1);
  const filled = Math.round(pos * barW);
  const icon = t >= duration ? "↺ " : playing ? "❚❚" : "▸ ";

  const words = TRANSCRIPT.split(" ");
  const lens = words.map((w) => w.length);
  const totalW = lens.reduce((a, b) => a + b, 0);
  const target = (t / duration) * totalW;
  let spoken = 0, acc = 0;
  for (const l of lens) { acc += l; if (acc <= target) spoken++; else break; }
  const blue = words.slice(0, spoken).join(" ");
  const dim = words.slice(spoken).join(" ");

  return (
    <div style={{ padding: "0 4px" }}>
      <div style={{ color: C.fg, fontWeight: 700 }}>What Are Bug Bounties and How They Work | HackerOne</div>
      <div style={{ color: C.dim }}>Summary · 1161 words · {fmt(duration)}</div>

      <div style={{ marginTop: 14, display: "flex", alignItems: "center", cursor: "pointer" }} onClick={onToggle}>
        <span style={{ color: C.fg }}>{icon} </span>
        <span style={{ color: C.dim }}>{fmt(t)} </span>
        <span style={{ whiteSpace: "pre" }}>
          <span style={{ color: C.blue }}>{"━".repeat(filled)}</span>
          <span style={{ color: C.dim }}>{"─".repeat(Math.max(0, barW - filled))}</span>
        </span>
        <span style={{ color: C.dim }}> {fmt(duration)}</span>
      </div>

      <div style={{ marginTop: 14, border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "12px 14px", lineHeight: 1.6 }}>
        <span style={{ color: C.blue }}>{blue}</span>
        <span style={{ color: C.dim }}>{(blue && dim ? " " : "") + dim}</span>
      </div>

      <div style={{ marginTop: 14, color: C.dim }}>
        <span style={{ color: C.fg }}>space</span> {t >= duration ? "replay" : "pause/resume"}  ·  <span style={{ color: C.fg }}>←/→</span> ±5s  ·  <span style={{ color: C.fg }}>t</span> hide transcript  ·  <span style={{ color: C.fg }}>q</span> back
      </div>
      <div style={{ color: C.dim }}>↓ eb36191518084b97a64116d4e29a8311.wav</div>
    </div>
  );
}

// ── /model screen ──────────────────────────────────────────────
const MODELS = [
  { name: "qwen3.5:9b", size: "5.4", params: "9.0B", fit: "fits", color: C.green, mark: "★", active: true, tags: "recommended" },
  { name: "llama3.3:70b", size: "42.5", params: "70B", fit: "too big", color: C.red, mark: " " },
  { name: "mistral-small", size: "14.3", params: "24B", fit: "tight", color: C.yellow, mark: " " },
  { name: "llava:13b", size: "8.0", params: "13B", fit: "fits", color: C.green, mark: " ", tags: "vision" },
  { name: "nomic-embed", size: "0.3", params: "—", fit: "embed", color: C.dim, mark: " " },
];

function ModelScreen() {
  return (
    <div style={{ padding: "0 4px" }}>
      <div style={{ color: C.dim }}>models on this mac (16 GB):</div>
      <div style={{ marginTop: 6 }}>
        {MODELS.map((m) => (
          <div key={m.name} style={{ display: "flex", gap: 0, whiteSpace: "pre" }}>
            <span style={{ color: m.active ? C.blue : C.dim, width: 18 }}>{m.mark} </span>
            <span style={{ color: m.active ? C.fg : C.dim, width: 150, display: "inline-block" }}>{m.name}</span>
            <span style={{ color: C.dim }}>{String(m.size).padStart(5)} GB  {m.params.padEnd(5)}  </span>
            <span style={{ color: m.color, width: 70, display: "inline-block" }}>{m.fit}</span>
            {m.tags && <span style={{ color: C.blue }}> {m.tags}</span>}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 14, color: C.dim }}>
        <span style={{ color: C.blue }}>/model &lt;name&gt;</span> to switch · Summary mode only
      </div>
    </div>
  );
}

// ── /lib screen ────────────────────────────────────────────────
const LIB = [
  { title: "Value Creation: Making Things People Want", meta: "summary  ·  1:56  ·  810 words  ·  18 Jun" },
  { title: "Android 17 is here", meta: "summary  ·  2:32  ·  2281 words  ·  18 Jun" },
  { title: "What Are Bug Bounties and How They Work | HackerOne", meta: "summary  ·  1:51  ·  1161 words  ·  16 Jun" },
];

function LibScreen() {
  const [cur, setCur] = React.useState(2);
  return (
    <div style={{ padding: "0 4px" }}>
      <div><span style={{ color: C.fg, fontWeight: 700 }}>library</span><span style={{ color: C.dim }}> — 9 reads</span></div>
      <div style={{ marginTop: 12 }}>
        {LIB.map((it, i) => (
          <div key={i} onClick={() => setCur(i)} style={{ cursor: "pointer" }}>
            <div>
              <span style={{ color: i === cur ? C.blue : C.dim }}>{i === cur ? "▸ " : "  "}</span>
              <span style={{ color: i === cur ? C.fg : C.dim, fontWeight: i === cur ? 700 : 400 }}>{it.title}</span>
            </div>
            {i === cur && <div style={{ marginLeft: 18, color: C.dim }}>{it.meta}</div>}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 14, color: C.dim }}>
        <span style={{ color: C.fg }}>↑↓</span> navigate  ·  <span style={{ color: C.fg }}>enter</span> play  ·  <span style={{ color: C.fg }}>d</span> delete  ·  <span style={{ color: C.fg }}>n</span> more  ·  <span style={{ color: C.fg }}>esc</span> back
      </div>
    </div>
  );
}

// ── /help screen ───────────────────────────────────────────────
const CMDS = [["/voice", "list voices"], ["/voice <id>", "switch voice"], ["/model", "list models (RAM fit + suggestion)"], ["/model <name>", "switch summary model"], ["/mode", "show current mode"], ["/mode summary", "spoken summary (local LLM)"], ["/lib", "browse past reads"], ["/quit", "exit"]];
const KEYS = [["space", "pause / resume"], ["← →", "seek ±5s"], ["t", "toggle transcript"], ["q", "back"]];

function HelpScreen() {
  return (
    <div style={{ padding: "0 4px" }}>
      <div style={{ color: C.fg, fontWeight: 700 }}>commands</div>
      <div style={{ marginTop: 4 }}>
        {CMDS.map(([c, d]) => (
          <div key={c} style={{ whiteSpace: "pre" }}>
            <span style={{ color: C.blue, display: "inline-block", width: 150 }}>{c}</span>
            <span style={{ color: C.dim }}>{d}</span>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 14, color: C.fg, fontWeight: 700 }}>player</div>
      <div style={{ marginTop: 4 }}>
        {KEYS.map(([k, d]) => (
          <div key={k} style={{ whiteSpace: "pre" }}>
            <span style={{ color: C.fg, display: "inline-block", width: 70 }}>{k}</span>
            <span style={{ color: C.dim }}>{d}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── window chrome + tab switcher ───────────────────────────────
const TABS = [
  ["input", "input"], ["player", "player"], ["model", "/model"], ["lib", "/lib"], ["help", "/help"],
];

function Terminal() {
  const [tab, setTab] = React.useState("player");
  const [t, setT] = React.useState(15);
  const [playing, setPlaying] = React.useState(false);
  const D = 111;
  const raf = React.useRef(null), last = React.useRef(null);

  React.useEffect(() => {
    if (!playing) return;
    const tick = (now) => {
      if (last.current == null) last.current = now;
      const dt = (now - last.current) / 1000; last.current = now;
      setT((p) => { const n = p + dt; if (n >= D) { setPlaying(false); return D; } return n; });
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf.current); last.current = null; };
  }, [playing]);

  const toggle = () => { if (t >= D) setT(0); setPlaying((p) => !p); };

  const screens = {
    input: <InputScreen />,
    player: <PlayerScreen t={t} playing={playing} onToggle={toggle} duration={D} />,
    model: <ModelScreen />,
    lib: <LibScreen />,
    help: <HelpScreen />,
  };

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: 24 }}>
      {/* tab switcher (kit affordance, not part of the CLI) */}
      <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
        {TABS.map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)} style={{
            background: tab === key ? "var(--accent-08)" : "none",
            border: `1px solid ${tab === key ? "var(--accent)" : "var(--line)"}`,
            color: tab === key ? "var(--accent)" : "var(--dim)",
            borderRadius: "var(--radius)", padding: "5px 12px", fontSize: "var(--text-sm)", cursor: "pointer",
            fontFamily: "var(--font-mono)", transition: "all var(--dur-fast)",
          }}>{label}</button>
        ))}
      </div>

      {/* macOS terminal window. Traffic-light hexes are genuine macOS chrome
          colours (not brand tokens) — left literal on purpose. */}
      <div style={{ background: "var(--bg)", border: "1px solid var(--line)", borderRadius: 12, overflow: "hidden", boxShadow: "var(--shadow-window)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
          <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff5f57" }} />
          <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#febc2e" }} />
          <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#28c840" }} />
          <span style={{ marginLeft: 12, color: C.dim, fontSize: "var(--text-sm)", fontFamily: "var(--font-mono)" }}>~ — readback-cli</span>
        </div>
        <div style={{ padding: "20px 18px", fontFamily: "var(--font-mono)", fontSize: "var(--text-base)", lineHeight: 1.55, minHeight: 380 }}>
          <div style={{ color: C.dim, marginBottom: 14 }}>~ (19s)<br />readback-cli</div>
          {screens[tab]}
        </div>
      </div>
    </div>
  );
}

window.Terminal = Terminal;

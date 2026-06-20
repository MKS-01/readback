/* readback library dashboard — recreation of the Vue 3 SPA (src/dashboard).
   Composes the design-system components: Wordmark, PromptLine, SearchInput,
   SortToggle (local), ReadCard. Loaded as a Babel script; reads components off
   the design-system namespace and exposes Dashboard on window. */

const NS = () => window.ReadbackDesignSystem_7af2ab;

const READS = [
  { id: "1", title: "Value Creation: Making Things People Want", date: "18 Jun 2026", duration: 116, mode: "summary", voice: "codeword", words: 810,
    snippet: "The chapter is titled Value Creation: Making Things People Want. It begins with an observation from Paul Graham, who notes that there is nothing more valuable than finding a broken thing that can be fixed for many people at once. This idea sets the tone for everything that follows.", sourceUrl: "#" },
  { id: "2", title: "Android 17 is here", date: "18 Jun 2026", duration: 152, mode: "summary", voice: "codeword", words: 2281,
    snippet: "Today we are releasing Android 17 for most supported Pixel devices, marking a major shift from an operating system to what Google calls an intelligence system that puts your apps at the center of user experiences. This update introduces a new on-device model layer.", sourceUrl: "#" },
  { id: "3", title: "What Are Bug Bounties and How They Work | HackerOne", date: "16 Jun 2026", duration: 111, mode: "summary", voice: "codeword", words: 1161,
    snippet: "So, I was just reading this interesting piece about bug bounty programs and how they work to help companies stay secure. Basically, as technology changes so fast with new features and AI, it becomes really hard for a single internal team to catch every vulnerability or security flaw.", sourceUrl: "#" },
  { id: "4", title: "The Pragmatic Programmer — Chapter 2", date: "14 Jun 2026", duration: 198, mode: "full", voice: "conversational_a", words: 3024,
    snippet: "A pragmatic approach begins with the idea that you should care about your craft. There is no point in developing software unless you care about doing it well, and that care shows up in every small decision you make along the way.", sourceUrl: "#" },
  { id: "5", title: "Introducing the AI Security Fabric", date: "12 Jun 2026", duration: 134, mode: "summary", voice: "conversational_b", words: 1480,
    snippet: "Empowering software builders in the age of autonomous agents means rethinking the boundary between trusted and untrusted code. The AI Security Fabric is a layer that sits between your agents and the systems they touch.", sourceUrl: "#" },
];

function SortToggle({ value, onChange }) {
  const opt = (key, label) => (
    React.createElement("button", {
      onClick: () => onChange(key),
      style: {
        background: value === key ? "var(--accent-08)" : "none",
        border: "none", color: value === key ? "var(--accent)" : "var(--dim)",
        padding: "9px 14px", fontSize: "var(--text-base)", cursor: "pointer", fontFamily: "var(--font-mono)",
        transition: "color var(--dur-fast), background var(--dur-fast)",
      },
    }, label)
  );
  return React.createElement("div", {
    style: { display: "flex", border: "1px solid var(--line)", borderRadius: "var(--radius)", overflow: "hidden", flexShrink: 0 },
  }, opt("newest", "Newest"), opt("oldest", "Oldest"));
}

function Dashboard() {
  const { Wordmark, PromptLine, SearchInput, ReadCard } = NS();
  const [q, setQ] = React.useState("");
  const [sort, setSort] = React.useState("newest");

  const filtered = READS
    .filter((r) => (q ? (r.title + " " + r.snippet).toLowerCase().includes(q.toLowerCase()) : true))
    .slice()
    .sort((a, b) => (sort === "newest" ? 0 : -1)); // demo: order kept

  return (
    <main style={{ maxWidth: 820, margin: "0 auto", padding: "56px 24px 72px" }}>
      <header style={{ marginBottom: 8 }}>
        <PromptLine command="readback-cli --library" style={{ marginBottom: 18 }} />
        <Wordmark height={32} src="../../assets/wordmark.png" subtitle="offline article reader · library" />
      </header>

      <div style={{ display: "flex", gap: 12, alignItems: "center", margin: "32px 0 24px", flexWrap: "wrap" }}>
        <SearchInput value={q} onChange={setQ} placeholder="search title, summary, url…" />
        <SortToggle value={sort} onChange={setSort} />
      </div>

      <p style={{ color: "var(--dim)", fontSize: "var(--text-sm)", marginBottom: 16, fontFamily: "var(--font-mono)" }}>
        {filtered.length === READS.length
          ? `${READS.length} reads`
          : `${filtered.length} of ${READS.length}`}
      </p>

      {filtered.length === 0 ? (
        <p style={{ color: "var(--dim)", fontSize: "var(--text-body)", padding: "40px 0", textAlign: "center", fontFamily: "var(--font-mono)" }}>
          no reads match “{q}”.
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {filtered.map((r) => <ReadCard key={r.id} {...r} />)}
        </div>
      )}

      <footer style={{ marginTop: 48, paddingTop: 24, borderTop: "1px solid var(--line)", textAlign: "center", color: "var(--dim)", fontSize: "var(--text-sm)", fontFamily: "var(--font-mono)" }}>
        readback · offline article reader · all on-device
      </footer>
    </main>
  );
}

window.Dashboard = Dashboard;

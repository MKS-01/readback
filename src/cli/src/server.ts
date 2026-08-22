import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

export interface ServerConfig {
  voices_available: { id: string; label: string }[];
  voice: string;
  model: string;
  default_mode: "full" | "summary";
  audio_dir?: string;   // server's output_dir — same-machine playback shortcut
  feed_picks?: number;  // numbered picks to show from reader.feeds (0 = none)
}

export interface ServerHandle {
  base: string; // http://host:port
  origin: "attached" | "spawned";
  proc: ReturnType<typeof Bun.spawn> | null;
  config: ServerConfig;
}

// In dev this file lives at <repo>/src/cli/src/; in a compiled binary
// import.meta.dir is a virtual bundle path, so install.sh bakes the real
// repo root in via --define process.env.READBACK_ROOT.
const REPO_ROOT = process.env.READBACK_ROOT ?? resolve(import.meta.dir, "..", "..", "..");

async function health(base: string, timeoutMs = 1500): Promise<ServerConfig | null> {
  try {
    const res = await fetch(`${base}/api/config`, {
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!res.ok) return null;
    return (await res.json()) as ServerConfig;
  } catch {
    return null;
  }
}

function readbackBin(): string[] | null {
  // Prefer the venv's Python running readback as a module — this works even
  // when the venv isn't activated, because we invoke the venv interpreter
  // directly (its sys.prefix already points at the venv).
  const venvPython = join(REPO_ROOT, ".venv", "bin", "python3");
  if (existsSync(venvPython)) return [venvPython, "-m", "readback"];
  // Fall back to the pip-installed `readback` entry point (its shebang
  // includes the absolute venv python path, so it's also self-contained).
  const venvBin = join(REPO_ROOT, ".venv", "bin", "readback");
  if (existsSync(venvBin)) return [venvBin];
  const found = Bun.which("readback");
  return found ? [found] : null;
}

/**
 * Connect to a running server, or spawn one and wait for health.
 * `onStatus` receives progress lines for the boot spinner.
 */
export async function ensureServer(
  host: string,
  port: number,
  noSpawn: boolean,
  onStatus: (line: string) => void,
): Promise<ServerHandle> {
  const base = `http://${host}:${port}`;

  onStatus(`looking for readback at ${base}…`);
  const existing = await health(base);
  if (existing) return { base, origin: "attached", proc: null, config: existing };

  if (noSpawn) {
    throw new Error(`no readback server at ${base} (--no-spawn given, so not starting one)`);
  }

  const cmd = readbackBin();
  if (!cmd) {
    throw new Error(
      `no readback server at ${base} and the \`readback\` command was not found — ` +
        `start the server manually or \`pip install -e .\` in the repo venv`,
    );
  }

  onStatus("starting readback server…");
  const proc = Bun.spawn([...cmd, "--host", host, "--port", String(port)], {
    cwd: REPO_ROOT,
    stdout: "ignore",
    stderr: "pipe",
  });

  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (proc.exitCode !== null) {
      let detail = "";
      try {
        detail = await new Response(proc.stderr).text();
      } catch {}
      throw new Error(
        `readback server exited during startup (code ${proc.exitCode})` +
          (detail ? `\n${detail.trim().split("\n").slice(-5).join("\n")}` : ""),
      );
    }
    const cfg = await health(base, 1000);
    if (cfg) return { base, origin: "spawned", proc, config: cfg };
    await Bun.sleep(500);
  }
  proc.kill();
  throw new Error("readback server did not become healthy within 60 s");
}

export function stopServer(handle: ServerHandle | null): void {
  const proc = handle?.origin === "spawned" ? handle.proc : null;
  if (!proc || proc.exitCode !== null) return;
  // SIGKILL outright and return — no wait. uvicorn's graceful (SIGTERM) shutdown
  // hangs on the open /ws, so the old code SIGTERM'd then busy-waited up to 1.5 s
  // for SIGKILL. But the synchronous busy-wait blocks the very event loop Bun
  // needs to reap the child, so exitCode never updated and the loop ALWAYS ran
  // its full deadline — that wait was the entire quit delay. This server is an
  // ephemeral, stateless process we spawned, so SIGKILL (uncatchable, ~instant,
  // no orphan) is the right tool; the kernel kills it even as we exit.
  proc.kill("SIGKILL");
}


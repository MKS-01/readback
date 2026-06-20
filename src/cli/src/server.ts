import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

export interface ServerConfig {
  voices_available: { id: string; label: string }[];
  voice: string;
  model: string;
  vision_model: string;
  default_mode: "full" | "summary";
  audio_dir?: string;   // server's output_dir — same-machine playback shortcut
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

function readbackBin(): string | null {
  const venv = join(REPO_ROOT, ".venv", "bin", "readback");
  if (existsSync(venv)) return venv;
  const found = Bun.which("readback");
  return found ?? null;
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

  const bin = readbackBin();
  if (!bin) {
    throw new Error(
      `no readback server at ${base} and the \`readback\` command was not found — ` +
        `start the server manually or \`pip install -e .\` in the repo venv`,
    );
  }

  onStatus("starting readback server…");
  const proc = Bun.spawn([bin, "--host", host, "--port", String(port)], {
    cwd: REPO_ROOT, // config.yaml resolves relative to cwd
    stdout: "ignore",
    stderr: "ignore",
  });

  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (proc.exitCode !== null) {
      throw new Error(`readback server exited during startup (code ${proc.exitCode})`);
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


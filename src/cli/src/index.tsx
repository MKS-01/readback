import React from "react";
import { render } from "ink";
import { App } from "./app";
import { ensureServer, stopServer, type ServerHandle } from "./server";
import { closeActiveSocket } from "./ws";
import { loadPrefs } from "./prefs";
import * as player from "./player";

function parseArgs() {
  const args = process.argv.slice(2);
  let host = "127.0.0.1";
  let port = 8000;
  let noSpawn = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--host" && args[i + 1]) host = args[++i]!;
    else if (args[i] === "--port" && args[i + 1]) port = Number(args[++i]);
    else if (args[i] === "--no-spawn") noSpawn = true;
    else if (args[i] === "--help" || args[i] === "-h") {
      console.log("readback-cli [--host 127.0.0.1] [--port 8000] [--no-spawn]");
      process.exit(0);
    }
  }
  return { host, port, noSpawn };
}

// pre-render output (before Ink mounts) — same Ghost palette as theme.ts
const dim = (s: string) => `\x1b[38;2;128;128;128m${s}\x1b[0m`;
const red = (s: string) => `\x1b[38;2;255;93;93m${s}\x1b[0m`;

let handle: ServerHandle | null = null;
let shutdownDone = false;

function shutdown() {
  if (shutdownDone) return;
  shutdownDone = true;
  player.stop();
  // Close the /ws first: uvicorn's graceful shutdown hangs on an open socket,
  // so this lets the spawned server exit immediately instead of waiting out
  // stopServer's SIGKILL timer.
  closeActiveSocket();
  stopServer(handle);
}

process.on("SIGINT", () => {
  shutdown();
  process.exit(0);
});
process.on("SIGTERM", () => {
  shutdown();
  process.exit(0);
});
process.on("exit", shutdown);

const { host, port, noSpawn } = parseArgs();

try {
  handle = await ensureServer(host, port, noSpawn, (line) => console.log(dim(line)));
} catch (err) {
  console.error(red(String(err instanceof Error ? err.message : err)));
  process.exit(1);
}

console.clear();
const ink = render(<App handle={handle} prefs={loadPrefs()} onQuit={shutdown} />);

// On resize the previous frame re-wraps, so ink erases the wrong number of
// lines and stale copies pile up. Run BEFORE ink's own resize handler
// (prependListener): drop ink's frame tracking and wipe the screen, so the
// repaint ink is about to do always starts from a blank slate at the top.
process.stdout.prependListener("resize", () => {
  ink.clear();
  process.stdout.write("\x1b[2J\x1b[3J\x1b[H"); // clear screen + scrollback, home
});

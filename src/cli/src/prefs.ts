import { homedir } from "node:os";
import { join } from "node:path";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

export interface Prefs {
  voice: string | null;
  mode: "full" | "summary" | null;
  model: string | null;
  visionModel: string | null;
}

const PREFS_PATH = join(homedir(), ".readback", "cli.json");

export function loadPrefs(): Prefs {
  try {
    if (existsSync(PREFS_PATH)) {
      const raw = JSON.parse(readFileSync(PREFS_PATH, "utf8"));
      return {
        voice: typeof raw.voice === "string" ? raw.voice : null,
        mode: raw.mode === "full" || raw.mode === "summary" ? raw.mode : null,
        model: typeof raw.model === "string" ? raw.model : null,
        visionModel: typeof raw.visionModel === "string" ? raw.visionModel : null,
      };
    }
  } catch {
    // corrupt prefs file — fall through to defaults
  }
  return { voice: null, mode: null, model: null, visionModel: null };
}

export function savePrefs(prefs: Prefs): void {
  try {
    mkdirSync(join(homedir(), ".readback"), { recursive: true });
    writeFileSync(PREFS_PATH, JSON.stringify(prefs, null, 2) + "\n");
  } catch {
    // prefs are a nicety; never crash on save
  }
}

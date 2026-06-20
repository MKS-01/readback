// Ghost palette + brand fonts — mirrors src/design-system/tokens so the video
// matches the CLI, dashboard, and landing page. Keep in sync with colors.css.
import { loadFont as loadPlex } from "@remotion/google-fonts/IBMPlexMono";
import { loadFont as loadMartian } from "@remotion/google-fonts/MartianMono";

export const COLORS = {
  bg: "#0a0a0a",
  panel: "#121212",
  line: "#232323",
  lineHi: "#333333",
  text: "#f0f0f0",
  dim: "#808080",
  accent: "#4da3ff",
  accentHi: "#6cb4ff",
  green: "#5dd17a",
  red: "#ff5d5d",
  yellow: "#e6c35a",
} as const;

// Loaded at bundle time by Remotion (no font files committed).
export const mono = loadPlex().fontFamily; // IBM Plex Mono — body / terminal
export const display = loadMartian().fontFamily; // Martian Mono — wordmark / headings

import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Dev: Vite serves the SPA on :5173 and proxies the data routes to the running
// `readback` server (:8000) — same origin as in production (FastAPI mounts the
// built dist at /). Build: emits ./dist, which the server serves at /.
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/audio": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});

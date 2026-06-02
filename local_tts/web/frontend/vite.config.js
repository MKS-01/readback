import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Vite emits assets with this URL prefix; FastAPI serves the built dist/
// from /static/dist/ via the StaticFiles mount.
// outDir is relative to this config file (frontend/), so `../static/dist`
// lands the build inside the FastAPI static mount.
export default defineConfig({
    plugins: [react()],
    base: "/static/dist/",
    build: {
        outDir: "../static/dist",
        emptyOutDir: true,
        target: "es2020",
        sourcemap: false,
    },
});

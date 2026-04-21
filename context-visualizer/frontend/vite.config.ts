import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

/**
 * Build output lands inside the Python package so wheels ship with the UI.
 * ``base`` matches the Flask static mount point; change both together if the
 * server-side mount ever moves.
 *
 * Dev proxy points at the Flask default (127.0.0.1:5000) so ``npm run dev``
 * against a locally running ``python -m context_visualizer`` works with no
 * extra CORS wiring.
 */
export default defineConfig({
  plugins: [react()],
  base: "/static/workspace/",
  build: {
    outDir: path.resolve(
      __dirname,
      "../context_visualizer/static/workspace"
    ),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/_interceptor": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
      },
      "/api": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
      },
    },
  },
});

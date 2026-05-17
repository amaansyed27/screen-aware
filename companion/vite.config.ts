import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**"]
    },
    proxy: {
      "/screen-aware-api": {
        target: "http://127.0.0.1:8787",
        changeOrigin: true,
        rewrite: path => path.replace(/^\/screen-aware-api/, "")
      },
      "/screen-aware-live": {
        target: "ws://127.0.0.1:8787",
        changeOrigin: true,
        ws: true,
        rewrite: path => path.replace(/^\/screen-aware-live/, "/api/live")
      }
    }
  },
  build: {
    target: process.env.TAURI_ENV_PLATFORM === "windows" ? "chrome105" : "safari13",
    outDir: "dist",
    emptyOutDir: true,
    minify: !process.env.TAURI_ENV_DEBUG,
    sourcemap: Boolean(process.env.TAURI_ENV_DEBUG)
  }
});

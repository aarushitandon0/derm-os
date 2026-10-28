import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

// Node global, typed here so the app doesn't need @types/node.
declare const process: { env: Record<string, string | undefined> };

// `npm run dev` for laptop work. `npm run dev:https` to open it on a phone over
// the LAN: phone browsers only allow the camera on https (or localhost).
export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === "https" ? [basicSsl()] : [])],
  server: {
    host: true,
    // DERMOS_API_PROXY: another local API port, e.g. http://127.0.0.1:8010 (default 8000).
    proxy: {
      "/api": process.env.DERMOS_API_PROXY ?? "http://127.0.0.1:8000",
      "/media": process.env.DERMOS_API_PROXY ?? "http://127.0.0.1:8000",
      "/health": process.env.DERMOS_API_PROXY ?? "http://127.0.0.1:8000",
    },
  },
}));

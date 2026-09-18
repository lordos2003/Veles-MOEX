import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The frontend calls the backend through /api and the Vite dev server proxies
// those requests to FastAPI on port 8000. In Docker, nginx does the same.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});

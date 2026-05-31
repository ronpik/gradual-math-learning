import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The static client is built into `dist/` and mounted at the backend root in
// production, so all asset URLs must be root-relative.
export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    proxy: {
      // In dev the Vite server forwards the student-safe API to the backend so
      // same-origin fetches (VITE_API_BASE unset) work without CORS.
      "/v1": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});

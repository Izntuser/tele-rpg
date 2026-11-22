import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Defaults serve the test stack (init.sh/e2e); scripts/live.sh overrides both for the live stack.
const backend = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000';
const port = Number(process.env.VITE_DEV_PORT) || 3000;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port,
    strictPort: true,
    // Dev tunnels for opening the Mini App inside Telegram (leading dot = any subdomain).
    allowedHosts: ['.ngrok-free.app', '.trycloudflare.com'],
    proxy: {
      '/api': backend,
      '/healthz': backend,
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./src/test-setup.ts'],
  },
});

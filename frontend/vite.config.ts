import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const backend = 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 3000,
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

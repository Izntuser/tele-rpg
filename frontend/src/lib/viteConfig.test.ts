// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';

type Cfg = {
  server: {
    port: number;
    strictPort: boolean;
    allowedHosts: string[];
    proxy: Record<string, string>;
  };
};

async function load(): Promise<Cfg> {
  vi.resetModules();
  const mod = await import('../../vite.config');
  return mod.default as unknown as Cfg;
}

describe('vite.config env overrides', () => {
  afterEach(() => vi.unstubAllEnvs());

  it('keeps the test-stack defaults', async () => {
    vi.stubEnv('VITE_DEV_PORT', '');
    vi.stubEnv('API_PROXY_TARGET', '');
    const { server } = await load();
    expect(server.port).toBe(3000);
    expect(server.strictPort).toBe(true);
    expect(server.proxy['/api']).toBe('http://127.0.0.1:8000');
    expect(server.proxy['/healthz']).toBe('http://127.0.0.1:8000');
  });

  it('honours VITE_DEV_PORT and API_PROXY_TARGET', async () => {
    vi.stubEnv('VITE_DEV_PORT', '3010');
    vi.stubEnv('API_PROXY_TARGET', 'http://127.0.0.1:8010');
    const { server } = await load();
    expect(server.port).toBe(3010);
    expect(server.proxy['/api']).toBe('http://127.0.0.1:8010');
    expect(server.allowedHosts).toEqual(['.ngrok-free.app', '.trycloudflare.com']);
  });
});

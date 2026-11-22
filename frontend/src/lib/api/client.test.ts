import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { ApiError, NoInitDataError, createApiClient } from './client';

type Call = { url: string; init: RequestInit };

function json(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function authBody(jwt: string) {
  return {
    jwt,
    token_type: 'bearer',
    expires_at: '2026-01-16T12:00:00Z',
    start_param: null,
    user: {
      id: 1,
      tg_user_id: 42,
      tg_username: 'alice',
      display_name: 'Alice',
      avatar_url: null,
      locale: 'en',
      timezone: 'UTC',
      onboarded_at: null,
    },
  };
}

/** Fake backend: issues jwt-1, jwt-2, ...; `valid` holds the tokens it currently accepts. */
function fakeServer() {
  const calls: Call[] = [];
  const valid = new Set<string>();
  let issued = 0;
  const fetch = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    calls.push({ url, init });
    if (url === '/api/auth/telegram') {
      const body = JSON.parse(String(init.body)) as { init_data: string };
      if (body.init_data !== 'signed-init-data') return json(401, { detail: 'Not authenticated' });
      const jwt = `jwt-${++issued}`;
      valid.add(jwt);
      return json(200, authBody(jwt));
    }
    const auth = new Headers(init.headers).get('Authorization') ?? '';
    if (!valid.has(auth.replace('Bearer ', ''))) return json(401, { detail: 'Not authenticated' });
    if (url === '/api/empty') return new Response(null, { status: 204 });
    if (url === '/api/fail') return json(409, { detail: 'conflict' });
    return json(200, { ok: true, url });
  });
  return { calls, valid, fetch };
}

function headersOf(call: Call): Headers {
  return new Headers(call.init.headers);
}

describe('api client', () => {
  let server: ReturnType<typeof fakeServer>;
  let initData: string;
  let client: ReturnType<typeof createApiClient>;

  beforeEach(() => {
    server = fakeServer();
    initData = 'signed-init-data';
    client = createApiClient({
      getInitData: () => initData,
      fetch: server.fetch as unknown as typeof fetch,
      newIdempotencyKey: () => 'generated-key',
    });
  });

  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  test('logs in with initData in the JSON body, then sends the JWT as a Bearer header', async () => {
    await expect(client.get('/thing')).resolves.toEqual({ ok: true, url: '/api/thing' });
    const [login, call] = server.calls;
    expect(login.url).toBe('/api/auth/telegram');
    expect(login.init.method).toBe('POST');
    expect(JSON.parse(String(login.init.body))).toEqual({ init_data: 'signed-init-data' });
    expect(call.url).toBe('/api/thing');
    expect(headersOf(call).get('Authorization')).toBe('Bearer jwt-1');
    // The token never travels in the URL.
    expect(server.calls.every((c) => !c.url.includes('jwt-'))).toBe(true);
  });

  test('keeps the JWT in memory only: no localStorage, sessionStorage or cookies', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    await client.get('/thing');
    await client.login();
    expect(setItem).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe('');
    expect(server.calls.every((c) => c.init.credentials === 'omit')).toBe(true);
    setItem.mockRestore();
  });

  test('reuses the token for later requests', async () => {
    await client.get('/a');
    await client.get('/b');
    expect(server.calls.filter((c) => c.url === '/api/auth/telegram')).toHaveLength(1);
  });

  test('re-authenticates once on 401 and retries the request', async () => {
    await client.get('/a');
    server.valid.clear(); // jwt-1 expired
    await expect(client.get('/b')).resolves.toEqual({ ok: true, url: '/api/b' });
    const urls = server.calls.map((c) => c.url);
    expect(urls).toEqual(['/api/auth/telegram', '/api/a', '/api/b', '/api/auth/telegram', '/api/b']);
    expect(headersOf(server.calls[4]).get('Authorization')).toBe('Bearer jwt-2');
  });

  test('gives up after one re-auth: a second 401 is an ApiError', async () => {
    await client.get('/a');
    server.valid.clear();
    server.fetch.mockImplementationOnce(async () => json(401, {})); // /b with old token
    server.fetch.mockImplementationOnce(async () => json(200, authBody('jwt-x'))); // re-login
    server.fetch.mockImplementationOnce(async () => json(401, { detail: 'nope' })); // retry
    const error = await client.get('/b').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect(server.fetch).toHaveBeenCalledTimes(5);
  });

  test('sends Idempotency-Key when asked and keeps it across the re-auth retry', async () => {
    await client.post('/buy', { id: 1 }, { idempotencyKey: 'fixed-key' });
    expect(headersOf(server.calls[1]).get('Idempotency-Key')).toBe('fixed-key');

    server.valid.clear();
    await client.post('/buy', { id: 2 }, { idempotencyKey: true });
    const buys = server.calls.filter((c) => c.url === '/api/buy').slice(1);
    expect(buys).toHaveLength(2);
    expect(buys.map((c) => headersOf(c).get('Idempotency-Key'))).toEqual([
      'generated-key',
      'generated-key',
    ]);
    expect(JSON.parse(String(buys[1].init.body))).toEqual({ id: 2 });
  });

  test('omits Idempotency-Key unless asked', async () => {
    await client.post('/thing', {});
    expect(headersOf(server.calls[1]).has('Idempotency-Key')).toBe(false);
  });

  test('deduplicates concurrent logins', async () => {
    await Promise.all([client.get('/a'), client.get('/b'), client.login()]);
    expect(server.calls.filter((c) => c.url === '/api/auth/telegram')).toHaveLength(1);
  });

  test('throws NoInitDataError without calling the server when initData is empty', async () => {
    initData = '';
    await expect(client.get('/a')).rejects.toBeInstanceOf(NoInitDataError);
    expect(server.fetch).not.toHaveBeenCalled();
  });

  test('a rejected login surfaces as ApiError and leaves no token', async () => {
    initData = 'forged';
    const error = await client.login().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect(client.hasToken()).toBe(false);
  });

  test('non-2xx responses become ApiError with the detail', async () => {
    const error = await client.post('/fail').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).detail).toBe('conflict');
  });

  test('204 resolves to undefined', async () => {
    await expect(client.delete('/empty')).resolves.toBeUndefined();
  });

  test('sends FormData as multipart (no JSON Content-Type) with the Bearer header', async () => {
    const form = new FormData();
    form.append('file', new Blob(['x'], { type: 'image/jpeg' }), 'a.jpg');
    await client.post('/files', form);
    const call = server.calls.at(-1)!;
    expect(call.init.body).toBe(form);
    expect(headersOf(call).get('Content-Type')).toBeNull();
    expect(headersOf(call).get('Authorization')).toBe('Bearer jwt-1');
  });

  test("responseType 'blob' returns the body as a Blob; errors are still ApiError", async () => {
    const blob = await client.get<Blob>('/files/1', { responseType: 'blob' });
    // Node's fetch Response makes a Node Blob (another realm than jsdom's), so check the shape.
    expect(typeof blob.text).toBe('function');
    expect(blob.type).toBe('application/json');
    expect(JSON.parse(await blob.text())).toEqual({ ok: true, url: '/api/files/1' });
    const error = await client.get('/fail', { responseType: 'blob' }).catch((e: unknown) => e);
    expect((error as ApiError).status).toBe(409);
  });

  test('logout forgets the token', async () => {
    await client.login();
    expect(client.hasToken()).toBe(true);
    client.logout();
    expect(client.hasToken()).toBe(false);
  });
});

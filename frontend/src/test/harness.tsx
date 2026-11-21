/**
 * Test harness: the real app (providers, AuthGate, router) over a scripted fake API.
 * `routes` maps "METHOD /path" to a response value or a function of the request body;
 * unknown requests reject so a test notices an unexpected call.
 */
import { QueryClient } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { vi } from 'vitest';

import { App } from '../app/App';
import { Providers } from '../app/providers';
import { createTestRouter } from '../app/router';
import { AuthGate } from '../features/auth/AuthGate';
import type { ApiClient, AuthResponse, Method, User } from '../lib/api/client';
import type { components } from '../lib/api/schema';
import { MockAdapter, type MockAdapterOptions } from '../lib/telegram/mock';

export type Character = components['schemas']['CharacterOut'];

export function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 1,
    tg_user_id: 42,
    tg_username: 'alice',
    display_name: 'Alice Archer',
    avatar_url: null,
    locale: 'en',
    timezone: 'UTC',
    onboarded_at: '2026-01-15T12:00:00Z',
    ...overrides,
  };
}

export function makeCharacter(overrides: Partial<Character> = {}): Character {
  return {
    id: 7,
    name: 'Aria',
    nickname: null,
    bio: null,
    avatar_url: null,
    level: 3,
    total_xp: 260,
    xp_into_level: 10,
    xp_for_next_level: 200,
    xp_to_next_level: 190,
    attributes: (['physical', 'intellectual', 'discipline', 'social', 'creativity', 'wellbeing'] as const).map(
      (attribute) => ({ attribute, xp: 0, level: 1, xp_into_level: 0, xp_for_next_level: 100 }),
    ),
    gold: 75,
    locale: 'en',
    timezone: 'UTC',
    onboarded_at: '2026-01-15T12:00:00Z',
    ...overrides,
  };
}

type Handler = unknown | ((body: unknown, path: string) => unknown);
export type Routes = Record<string, Handler>;

export class FakeApiError extends Error {}

export function fakeApi(user: User, routes: Routes = {}, startParam: string | null = null) {
  const calls: { method: Method; path: string; body: unknown }[] = [];
  const request = vi.fn(async (method: Method, path: string, opts: { body?: unknown } = {}) => {
    calls.push({ method, path, body: opts.body });
    const key = `${method} ${path}`;
    if (!(key in routes)) throw new FakeApiError(`unexpected ${key}`);
    const handler = routes[key];
    return typeof handler === 'function' ? await (handler as (b: unknown, p: string) => unknown)(opts.body, path) : handler;
  });
  const login = vi.fn(
    (): Promise<AuthResponse> =>
      Promise.resolve({
        jwt: 'j',
        token_type: 'bearer',
        expires_at: '2026-01-16T12:00:00Z',
        start_param: startParam,
        user,
      }),
  );
  const api: ApiClient = {
    login,
    request: request as ApiClient['request'],
    get: ((path: string, o?: object) => request('GET', path, o)) as ApiClient['get'],
    post: ((path: string, body?: unknown) => request('POST', path, { body })) as ApiClient['post'],
    patch: ((path: string, body?: unknown) => request('PATCH', path, { body })) as ApiClient['patch'],
    delete: ((path: string) => request('DELETE', path)) as ApiClient['delete'],
    hasToken: () => true,
    logout: () => {},
  };
  return { api, calls, request };
}

export function renderApp(
  path: string,
  {
    user = makeUser(),
    routes = {},
    startParam = null,
    telegram = {},
  }: { user?: User; routes?: Routes; startParam?: string | null; telegram?: MockAdapterOptions } = {},
) {
  const fake = fakeApi(user, routes, startParam);
  const adapter = new MockAdapter({ initData: 'x', ...telegram });
  const router = createTestRouter([path]);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <Providers api={fake.api} telegram={adapter} queryClient={queryClient}>
      <AuthGate>
        <App router={router} />
      </AuthGate>
    </Providers>,
  );
  return { ...fake, adapter, router, queryClient, view };
}

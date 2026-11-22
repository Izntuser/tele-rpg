import { QueryClient } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import { AuthGate } from '../features/auth/AuthGate';
import type { ApiClient } from '../lib/api/client';
import { MockAdapter } from '../lib/telegram';
import indexHtml from '../../index.html?raw';
import { App } from './App';
import { Providers } from './providers';

test('renders the home with the signed-in, onboarded user', async () => {
  const fail = () => Promise.reject(new Error('unused'));
  const api: ApiClient = {
    login: vi.fn(() =>
      Promise.resolve({
        jwt: 'j',
        token_type: 'bearer',
        expires_at: '2026-01-16T12:00:00Z',
        start_param: null,
        user: {
          id: 1,
          tg_user_id: 2,
          tg_username: null,
          display_name: 'Bob',
          avatar_url: null,
          avatar_file_id: null,
          locale: 'en' as const,
          timezone: 'UTC',
          onboarded_at: '2026-01-15T12:00:00Z',
        },
      }),
    ),
    request: fail,
    get: fail,
    post: fail,
    patch: fail,
    delete: fail,
    hasToken: () => true,
    logout: () => {},
  };
  render(
    <Providers api={api} telegram={new MockAdapter({ initData: 'x' })} queryClient={new QueryClient()}>
      <AuthGate>
        <App />
      </AuthGate>
    </Providers>,
  );
  expect(await screen.findByRole('heading', { name: 'Modern Life RPG' })).toBeInTheDocument();
  expect(screen.getByText('Hi, Bob')).toBeInTheDocument();
});

test('index.html tells the browser never to send a Referer (invite tokens sit in the URL)', () => {
  const doc = new DOMParser().parseFromString(indexHtml, 'text/html');
  expect(doc.querySelector('meta[name="referrer"]')?.getAttribute('content')).toBe('no-referrer');
});

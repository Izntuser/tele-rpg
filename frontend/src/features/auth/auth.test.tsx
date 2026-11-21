import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';

import { App } from '../../app/App';
import { Providers } from '../../app/providers';
import { ApiError, type ApiClient, type AuthResponse } from '../../lib/api/client';
import { MockAdapter } from '../../lib/telegram';
import { AuthGate } from './AuthGate';

const AUTH: AuthResponse = {
  jwt: 'jwt-1',
  token_type: 'bearer',
  expires_at: '2026-01-16T12:00:00Z',
  start_param: 'invite_abc',
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

function fakeApi(login: ApiClient['login']): ApiClient {
  const fail = () => Promise.reject(new Error('unused'));
  return {
    login: vi.fn(login),
    request: fail,
    get: fail,
    post: fail,
    patch: fail,
    delete: fail,
    hasToken: () => false,
    logout: () => {},
  };
}

function renderApp(api: ApiClient, telegram: MockAdapter) {
  const queryClient = new QueryClient();
  return render(
    <Providers api={api} telegram={telegram} queryClient={queryClient}>
      <AuthGate>
        <App />
      </AuthGate>
    </Providers>,
  );
}

describe('auth bootstrap', () => {
  test('logs in on start and shows the Telegram name on the home page', async () => {
    const telegram = new MockAdapter({ initData: 'signed' });
    const api = fakeApi(() => Promise.resolve(AUTH));
    renderApp(api, telegram);
    expect(screen.getByRole('status')).toHaveTextContent('Signing in');
    expect(await screen.findByTestId('user-greeting')).toHaveTextContent('Hi, Alice');
    expect(screen.getByRole('heading', { name: 'Modern Life RPG' })).toBeInTheDocument();
    expect(api.login).toHaveBeenCalledTimes(1);
    expect(telegram.calls.map((c) => c.method)).toContain('ready');
  });

  test('outside Telegram it asks to open the app from Telegram and does not call the API', () => {
    const api = fakeApi(() => Promise.resolve(AUTH));
    renderApp(api, new MockAdapter());
    expect(screen.getByText(/Open this app from Telegram/)).toBeInTheDocument();
    expect(api.login).not.toHaveBeenCalled();
  });

  test('a rejected login shows an inline error with a retry button (no native dialogs)', async () => {
    const alert = vi.spyOn(window, 'alert').mockImplementation(() => {});
    let attempts = 0;
    const api = fakeApi(() =>
      ++attempts === 1 ? Promise.reject(new ApiError(401, 'nope')) : Promise.resolve(AUTH),
    );
    renderApp(api, new MockAdapter({ initData: 'signed' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('rejected');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByTestId('user-greeting')).toHaveTextContent('Alice');
    expect(alert).not.toHaveBeenCalled();
    alert.mockRestore();
  });
});

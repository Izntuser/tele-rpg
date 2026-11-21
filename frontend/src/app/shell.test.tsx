import { QueryClient } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { AuthGate } from '../features/auth/AuthGate';
import { setLocale } from '../i18n';
import type { ApiClient, AuthResponse } from '../lib/api/client';
import { MockAdapter } from '../lib/telegram';
import type { MockAdapterOptions } from '../lib/telegram/mock';
import { App } from './App';
import { Providers } from './providers';
import { createTestRouter } from './router';

function auth(locale: 'en' | 'uk' = 'en', startParam: string | null = null, onboarded = true): AuthResponse {
  return {
    jwt: 'j',
    token_type: 'bearer',
    expires_at: '2026-01-16T12:00:00Z',
    start_param: startParam,
    user: {
      id: 1,
      tg_user_id: 2,
      tg_username: null,
      display_name: 'Bob',
      avatar_url: null,
      locale,
      timezone: 'UTC',
      onboarded_at: onboarded ? '2026-01-15T12:00:00Z' : null,
    },
  };
}

function renderShell(
  path: string,
  {
    locale,
    startParam,
    telegram,
    onboarded = true,
  }: { locale?: 'en' | 'uk'; startParam?: string | null; telegram?: MockAdapterOptions; onboarded?: boolean } = {},
) {
  const fail = () => Promise.reject(new Error('unused'));
  const api: ApiClient = {
    login: () => Promise.resolve(auth(locale, startParam ?? null, onboarded)),
    request: fail,
    get: fail,
    post: fail,
    patch: fail,
    delete: fail,
    hasToken: () => true,
    logout: () => {},
  };
  const adapter = new MockAdapter({ initData: 'x', ...telegram });
  const router = createTestRouter([path]);
  render(
    <Providers api={api} telegram={adapter} queryClient={new QueryClient()}>
      <AuthGate>
        <App router={router} />
      </AuthGate>
    </Providers>,
  );
  return { adapter, router };
}

afterEach(() => {
  setLocale('en');
  delete document.documentElement.dataset.theme;
});

const ROUTES: [string, string][] = [
  ['/', 'page-home'],
  ['/invite/tok', 'page-invite'],
  ['/quests', 'page-quests'],
  ['/quests/new', 'page-quests'],
  ['/quests/5', 'page-quest-detail'],
  ['/shop', 'page-shop'],
  ['/shop/inventory', 'page-inventory'],
  ['/shop/manage', 'page-shop-manage'],
  ['/stats', 'page-stats'],
  ['/stats/journal', 'page-journal'],
  ['/companion', 'page-companion'],
  ['/me/goals', 'page-goals'],
  ['/me/wishlist', 'page-wishlist'],
  ['/notifications', 'page-notifications'],
  ['/settings', 'page-settings'],
];

describe('routes', () => {
  test.each(ROUTES)('%s renders %s', async (path, testId) => {
    renderShell(path);
    expect(await screen.findByTestId(testId)).toBeInTheDocument();
  });

  test('an unknown route redirects to Home', async () => {
    const { router } = renderShell('/definitely/not/here');
    expect(await screen.findByTestId('page-home')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/');
  });
});

describe('bottom nav', () => {
  test('has the five tabs and highlights the active one', async () => {
    renderShell('/quests/9');
    await screen.findByTestId('page-quest-detail');
    expect(screen.getAllByRole('link')).toHaveLength(5);
    expect(screen.getByTestId('nav-quests')).toHaveAttribute('aria-current', 'page');
    for (const other of ['home', 'shop', 'stats', 'companion']) {
      expect(screen.getByTestId(`nav-${other}`)).not.toHaveAttribute('aria-current');
    }
  });

  test('Home is active only on the root route', async () => {
    renderShell('/');
    await screen.findByTestId('page-home');
    expect(screen.getByTestId('nav-home')).toHaveAttribute('aria-current', 'page');
  });

  test('is hidden during onboarding', async () => {
    renderShell('/onboarding', { onboarded: false });
    await screen.findByTestId('page-onboarding');
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  test('tapping a tab navigates', async () => {
    renderShell('/');
    await screen.findByTestId('page-home');
    await act(async () => screen.getByTestId('nav-shop').click());
    expect(await screen.findByTestId('page-shop')).toBeInTheDocument();
    expect(screen.getByTestId('nav-shop')).toHaveAttribute('aria-current', 'page');
  });
});

describe('telegram back button', () => {
  const methods = (a: MockAdapter) => a.calls.map((c) => c.method);

  test('hidden on the root route', async () => {
    const { adapter } = renderShell('/');
    await screen.findByTestId('page-home');
    expect(methods(adapter)).toContain('backButton.hide');
    expect(methods(adapter)).not.toContain('backButton.show');
  });

  test('shown on a non-root route and navigates back', async () => {
    const { adapter, router } = renderShell('/');
    await screen.findByTestId('page-home');
    await act(async () => {
      await router.navigate('/quests');
    });
    expect(methods(adapter)).toContain('backButton.show');
    await act(async () => {
      adapter.pressBack();
    });
    await waitFor(() => expect(router.state.location.pathname).toBe('/'));
  });

  test('on a first-entry deep page it goes Home instead of leaving the app', async () => {
    const { adapter, router } = renderShell('/quests/3');
    await screen.findByTestId('page-quest-detail');
    await act(async () => {
      adapter.pressBack();
    });
    await waitFor(() => expect(router.state.location.pathname).toBe('/'));
  });
});

describe('theme, locale and deeplinks', () => {
  test('Back after a start-param redirect goes Home instead of leaving the app', async () => {
    const { adapter, router } = renderShell('/', { telegram: { startParam: 'q_12' } });
    await screen.findByTestId('page-quest-detail');
    expect(router.state.location.pathname).toBe('/quests/12');
    await act(async () => {
      adapter.pressBack();
    });
    await waitFor(() => expect(router.state.location.pathname).toBe('/'));
    expect(await screen.findByTestId('page-home')).toBeInTheDocument();
  });

  test('Back after in-app navigation past a deeplink steps back through history', async () => {
    const { adapter, router } = renderShell('/', { telegram: { startParam: 'q_12' } });
    await screen.findByTestId('page-quest-detail');
    await act(async () => {
      await router.navigate('/shop');
    });
    await act(async () => {
      adapter.pressBack();
    });
    await waitFor(() => expect(router.state.location.pathname).toBe('/quests/12'));
  });

  test('a server-provided start_param opens the mapped route', async () => {
    const { router } = renderShell('/', { startParam: 'q_31' });
    await waitFor(() => expect(router.state.location.pathname).toBe('/quests/31'));
    expect(await screen.findByTestId('page-quest-detail')).toBeInTheDocument();
  });

  test('Telegram safe-area insets reach the --safe-* CSS variables', async () => {
    const root = document.documentElement.style;
    ['top', 'bottom', 'left', 'right'].forEach((s) => root.removeProperty(`--safe-${s}`));
    const viewport = vi
      .spyOn(MockAdapter.prototype, 'viewport')
      .mockReturnValue({ height: 600, stableHeight: 600, safeArea: { top: 11, bottom: 22, left: 33, right: 44 } });
    renderShell('/');
    await screen.findByTestId('page-home');
    expect(root.getPropertyValue('--safe-top')).toBe('11px');
    expect(root.getPropertyValue('--safe-bottom')).toBe('22px');
    expect(root.getPropertyValue('--safe-left')).toBe('33px');
    expect(root.getPropertyValue('--safe-right')).toBe('44px');
    viewport.mockRestore();
    ['top', 'bottom', 'left', 'right'].forEach((s) => root.removeProperty(`--safe-${s}`));
  });

  test('dark by default; light when Telegram says so', async () => {
    renderShell('/');
    await screen.findByTestId('page-home');
    expect(document.documentElement.dataset.theme).toBe('dark');
    renderShell('/', { telegram: { colorScheme: 'light' } });
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('light'));
  });

  test('the UI follows the user locale', async () => {
    renderShell('/', { locale: 'uk' });
    // setLocale runs in an effect after the first render; wait for it instead of racing it.
    await waitFor(() => expect(screen.getByTestId('user-greeting')).toHaveTextContent('Привіт, Bob'));
    expect(screen.getByTestId('nav-home')).toHaveTextContent('Головна');
  });

  test('a start param opens the mapped route', async () => {
    const { router } = renderShell('/', { telegram: { startParam: 'q_12' } });
    await waitFor(() => expect(router.state.location.pathname).toBe('/quests/12'));
    expect(await screen.findByTestId('page-quest-detail')).toBeInTheDocument();
  });

  test('an unknown start param stays on Home', async () => {
    const { router } = renderShell('/', { telegram: { startParam: 'weird' } });
    await screen.findByTestId('page-home');
    expect(router.state.location.pathname).toBe('/');
  });
});

test('no native dialogs are used', async () => {
  const alert = vi.spyOn(window, 'alert');
  renderShell('/settings');
  await screen.findByTestId('page-settings');
  expect(alert).not.toHaveBeenCalled();
  alert.mockRestore();
});

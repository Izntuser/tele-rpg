import { MockAdapter } from './mock';
import { TmaAdapter, detectWebApp } from './tma';
import type { TelegramAdapter } from './types';

export { MockAdapter } from './mock';
export { TmaAdapter, createSdkWebApp, detectWebApp } from './tma';
export type * from './types';

/**
 * TmaAdapter inside Telegram (a `window.Telegram.WebApp` with initData, or SDK launch params),
 * MockAdapter in a plain browser. Never throws.
 */
export function createTelegramAdapter(
  win: Window | undefined = typeof window === 'undefined' ? undefined : window,
): TelegramAdapter {
  const webApp = detectWebApp(win);
  if (webApp) return new TmaAdapter(webApp);
  return new MockAdapter({ initData: import.meta.env.VITE_MOCK_INIT_DATA ?? '' });
}

let current: TelegramAdapter | null = null;

/** The app-wide adapter (created on first use). */
export function getTelegram(): TelegramAdapter {
  current ??= createTelegramAdapter();
  return current;
}

/** Tests only: replace (or with null, reset) the app-wide adapter. */
export function setTelegram(adapter: TelegramAdapter | null): void {
  current = adapter;
}

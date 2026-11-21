/**
 * Playwright fixtures for the Telegram Mini App.
 *
 * - `signInitData` signs initData exactly as Telegram does (HMAC-SHA256 with
 *   secret = HMAC("WebAppData", bot token)), using the fake bot token of the init.sh stack, so
 *   e2e runs the real POST /api/auth/telegram path.
 * - `telegram(who)` injects a `window.Telegram.WebApp` stub carrying that initData before any
 *   page script runs. Calls to the stub are recorded in `window.__telegramCalls`.
 * - Every test starts from an empty database: an automatic fixture signs in as user A and
 *   calls the test-only POST /api/test/reset (APP_ENV=test stacks only).
 */
import { createHmac } from 'node:crypto';

import { test as base, expect, type APIRequestContext, type Page } from '@playwright/test';

/** Must equal TG_BOT_TOKEN of the stack started by init.sh (the public fake dev token). */
export const BOT_TOKEN =
  process.env.TG_BOT_TOKEN ?? '123456789:AAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE';

export interface TelegramTestUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  language_code?: string;
}

export const USERS = {
  A: { id: 7_000_001, first_name: 'Alice', last_name: 'Archer', username: 'alice_a', language_code: 'en' },
  B: { id: 7_000_002, first_name: 'Bohdan', username: 'bohdan_b', language_code: 'uk' },
} satisfies Record<string, TelegramTestUser>;

export type UserKey = keyof typeof USERS;

export interface SignOptions {
  botToken?: string;
  authDate?: Date;
  startParam?: string;
}

export function signInitData(user: TelegramTestUser, options: SignOptions = {}): string {
  const authDate = Math.floor((options.authDate ?? new Date()).getTime() / 1000);
  const fields: Record<string, string> = {
    auth_date: String(authDate),
    query_id: `AAE2E${user.id}`,
    user: JSON.stringify(user),
  };
  if (options.startParam) fields.start_param = options.startParam;
  const dataCheckString = Object.keys(fields)
    .sort()
    .map((key) => `${key}=${fields[key]}`)
    .join('\n');
  const secret = createHmac('sha256', 'WebAppData')
    .update(options.botToken ?? BOT_TOKEN)
    .digest();
  const hash = createHmac('sha256', secret).update(dataCheckString).digest('hex');
  return new URLSearchParams({ ...fields, hash }).toString();
}

interface StubArgs {
  initData: string;
  user: TelegramTestUser;
  startParam: string | null;
}

/** Runs in the browser before the app: a minimal Telegram.WebApp that records calls. */
function installTelegramStub({ initData, user, startParam }: StubArgs): void {
  const calls: { method: string; args: unknown[] }[] = [];
  const rec =
    (method: string) =>
    (...args: unknown[]) => {
      calls.push({ method, args });
    };
  const handlers: Record<string, () => void> = {};
  const button = (name: string) => ({
    isVisible: false,
    show: rec(`${name}.show`),
    hide: rec(`${name}.hide`),
    onClick: (handler: () => void) => {
      calls.push({ method: `${name}.onClick`, args: [] });
      handlers[name] = handler;
    },
    offClick: (handler: () => void) => {
      calls.push({ method: `${name}.offClick`, args: [] });
      if (handlers[name] === handler) delete handlers[name];
    },
    setText: rec(`${name}.setText`),
    showProgress: rec(`${name}.showProgress`),
    hideProgress: rec(`${name}.hideProgress`),
  });
  const w = window as unknown as Record<string, unknown>;
  w.__telegramCalls = calls;
  w.__telegramClick = (name: string) => handlers[name]?.();
  w.Telegram = {
    WebApp: {
      initData,
      initDataUnsafe: { user, start_param: startParam ?? undefined },
      version: '8.0',
      platform: 'tdesktop',
      colorScheme: 'dark',
      themeParams: { bg_color: '#17212b', text_color: '#f5f5f5' },
      viewportHeight: window.innerHeight,
      viewportStableHeight: window.innerHeight,
      safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
      ready: rec('ready'),
      expand: rec('expand'),
      HapticFeedback: {
        impactOccurred: rec('HapticFeedback.impactOccurred'),
        notificationOccurred: rec('HapticFeedback.notificationOccurred'),
        selectionChanged: rec('HapticFeedback.selectionChanged'),
      },
      BackButton: button('BackButton'),
      MainButton: button('MainButton'),
      enableClosingConfirmation: rec('enableClosingConfirmation'),
      disableClosingConfirmation: rec('disableClosingConfirmation'),
      requestWriteAccess: (cb?: (granted: boolean) => void) => {
        calls.push({ method: 'requestWriteAccess', args: [] });
        cb?.(true);
      },
    },
  };
}

export async function injectTelegram(
  page: Page,
  who: UserKey | TelegramTestUser,
  options: SignOptions & { initData?: string } = {},
): Promise<void> {
  const user = typeof who === 'string' ? USERS[who] : who;
  const initData = options.initData ?? signInitData(user, options);
  await page.addInitScript(installTelegramStub, {
    initData,
    user,
    startParam: options.startParam ?? null,
  });
}

/** Signs in as `who` through the real auth endpoint and returns the JWT. */
export async function apiLogin(request: APIRequestContext, who: UserKey = 'A'): Promise<string> {
  const response = await request.post('/api/auth/telegram', {
    data: { init_data: signInitData(USERS[who]) },
  });
  expect(response.status(), await response.text()).toBe(200);
  return ((await response.json()) as { jwt: string }).jwt;
}

/** Empties the e2e database via the test-only endpoint (it requires a JWT like every route). */
export async function resetDatabase(request: APIRequestContext): Promise<void> {
  const jwt = await apiLogin(request, 'A');
  const response = await request.post('/api/test/reset', {
    headers: { Authorization: `Bearer ${jwt}` },
  });
  expect(response.status(), 'POST /api/test/reset (is the stack APP_ENV=test?)').toBe(204);
}

export const test = base.extend<{
  resetDb: void;
  telegram: (who: UserKey | TelegramTestUser, options?: SignOptions & { initData?: string }) => Promise<void>;
}>({
  resetDb: [
    async ({ request }, use) => {
      await resetDatabase(request);
      await use();
    },
    { auto: true },
  ],
  telegram: async ({ page }, use) => {
    await use((who, options) => injectTelegram(page, who, options));
  },
});

export { expect };

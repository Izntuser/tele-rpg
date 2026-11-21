import { afterEach, describe, expect, test, vi } from 'vitest';

import {
  MockAdapter,
  TmaAdapter,
  createTelegramAdapter,
  mockInitData,
  getTelegram,
  setTelegram,
  type TelegramAdapter,
  type WebAppLike,
} from './index';

function fakeWindow(telegram?: unknown): Window {
  return { Telegram: telegram, innerHeight: 700 } as unknown as Window;
}

function exercise(adapter: TelegramAdapter): void {
  adapter.getInitData();
  adapter.startParam();
  adapter.ready();
  adapter.haptic.impact();
  adapter.haptic.notification('success');
  adapter.haptic.selection();
  adapter.backButton.show();
  adapter.backButton.hide();
  adapter.backButton.onClick(() => {})();
  adapter.mainButton.show('Go');
  adapter.mainButton.setLoading(true);
  adapter.mainButton.setLoading(false);
  adapter.mainButton.hide();
  adapter.mainButton.onClick(() => {})();
  adapter.theme();
  adapter.viewport();
  adapter.closingConfirmation(true);
  adapter.closingConfirmation(false);
}

function throwingWebApp(): WebAppLike {
  const boom = () => {
    throw new Error('unsupported in this client version');
  };
  const button = { show: boom, hide: boom, onClick: boom, offClick: boom };
  return {
    initData: 'query_id=1&hash=abc',
    ready: boom,
    expand: boom,
    HapticFeedback: { impactOccurred: boom, notificationOccurred: boom, selectionChanged: boom },
    BackButton: button,
    MainButton: { ...button, setText: boom, showProgress: boom, hideProgress: boom },
    enableClosingConfirmation: boom,
    disableClosingConfirmation: boom,
    requestWriteAccess: boom,
    get themeParams(): Record<string, unknown> {
      throw new Error('getter');
    },
  };
}

describe('createTelegramAdapter', () => {
  test('picks TmaAdapter when window.Telegram.WebApp has initData', () => {
    const adapter = createTelegramAdapter(
      fakeWindow({ WebApp: { initData: 'user=x&hash=y', initDataUnsafe: { start_param: 'inv_1' } } }),
    );
    expect(adapter).toBeInstanceOf(TmaAdapter);
    expect(adapter.kind).toBe('tma');
    expect(adapter.getInitData()).toBe('user=x&hash=y');
    expect(adapter.startParam()).toBe('inv_1');
  });

  test.each([
    ['no Telegram object', undefined],
    ['no WebApp', {}],
    ['empty initData (telegram-web-app.js in a plain browser)', { WebApp: { initData: '' } }],
    ['non-string initData', { WebApp: { initData: 42 } }],
  ])('picks MockAdapter in a plain browser: %s', (_name, telegram) => {
    const adapter = createTelegramAdapter(fakeWindow(telegram));
    expect(adapter).toBeInstanceOf(MockAdapter);
    expect(adapter.kind).toBe('mock');
    expect(adapter.getInitData()).toBe('');
    expect(adapter.startParam()).toBeNull();
  });

  test('picks MockAdapter for the real jsdom window and without a window', () => {
    expect(createTelegramAdapter()).toBeInstanceOf(MockAdapter);
    expect(createTelegramAdapter(undefined)).toBeInstanceOf(MockAdapter);
  });

  test('does not throw when window.Telegram is a throwing getter', () => {
    const win = {} as Window;
    Object.defineProperty(win, 'Telegram', {
      get() {
        throw new Error('blocked');
      },
    });
    expect(createTelegramAdapter(win)).toBeInstanceOf(MockAdapter);
  });
});

describe('VITE_MOCK_INIT_DATA', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  test('feeds the MockAdapter in DEV', () => {
    vi.stubEnv('DEV', true);
    vi.stubEnv('VITE_MOCK_INIT_DATA', 'user=dev&hash=h');
    expect(mockInitData()).toBe('user=dev&hash=h');
    expect(createTelegramAdapter(fakeWindow()).getInitData()).toBe('user=dev&hash=h');
  });

  test('is ignored outside DEV (production build)', () => {
    vi.stubEnv('DEV', false);
    vi.stubEnv('PROD', true);
    vi.stubEnv('VITE_MOCK_INIT_DATA', 'user=leak&hash=h');
    expect(mockInitData()).toBe('');
    const adapter = createTelegramAdapter(fakeWindow());
    expect(adapter).toBeInstanceOf(MockAdapter);
    expect(adapter.getInitData()).toBe('');
  });
});

describe('TmaAdapter', () => {
  test('forwards calls to the WebApp object', async () => {
    const webApp = {
      initData: 'a=1&hash=h',
      colorScheme: 'light',
      themeParams: { bg_color: '#ffffff', bad: 3 },
      viewportHeight: 600,
      viewportStableHeight: 580,
      safeAreaInset: { top: 10, bottom: 20 },
      ready: vi.fn(),
      expand: vi.fn(),
      HapticFeedback: {
        impactOccurred: vi.fn(),
        notificationOccurred: vi.fn(),
        selectionChanged: vi.fn(),
      },
      BackButton: { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() },
      MainButton: {
        show: vi.fn(),
        hide: vi.fn(),
        setText: vi.fn(),
        showProgress: vi.fn(),
        hideProgress: vi.fn(),
        onClick: vi.fn(),
        offClick: vi.fn(),
      },
      enableClosingConfirmation: vi.fn(),
      disableClosingConfirmation: vi.fn(),
      requestWriteAccess: vi.fn((cb: (granted: boolean) => void) => cb(true)),
    };
    const adapter = new TmaAdapter(webApp);

    adapter.ready();
    expect(webApp.ready).toHaveBeenCalled();
    expect(webApp.expand).toHaveBeenCalled();
    adapter.haptic.impact('heavy');
    expect(webApp.HapticFeedback.impactOccurred).toHaveBeenCalledWith('heavy');
    adapter.haptic.notification('error');
    expect(webApp.HapticFeedback.notificationOccurred).toHaveBeenCalledWith('error');
    const cb = () => {};
    const off = adapter.backButton.onClick(cb);
    expect(webApp.BackButton.onClick).toHaveBeenCalledWith(cb);
    off();
    expect(webApp.BackButton.offClick).toHaveBeenCalledWith(cb);
    adapter.mainButton.show('Save');
    expect(webApp.MainButton.setText).toHaveBeenCalledWith('Save');
    expect(webApp.MainButton.show).toHaveBeenCalled();
    adapter.closingConfirmation(true);
    expect(webApp.enableClosingConfirmation).toHaveBeenCalled();
    adapter.closingConfirmation(false);
    expect(webApp.disableClosingConfirmation).toHaveBeenCalled();
    expect(adapter.theme()).toEqual({ colorScheme: 'light', params: { bg_color: '#ffffff' } });
    expect(adapter.viewport()).toEqual({
      height: 600,
      stableHeight: 580,
      safeArea: { top: 10, bottom: 20, left: 0, right: 0 },
    });
    await expect(adapter.requestWriteAccess()).resolves.toBe(true);
  });

  test('never throws, even when every WebApp method throws', async () => {
    const adapter = new TmaAdapter(throwingWebApp());
    expect(() => exercise(adapter)).not.toThrow();
    expect(adapter.theme()).toEqual({ colorScheme: 'dark', params: {} });
    await expect(adapter.requestWriteAccess()).resolves.toBe(false);
  });

  test('never throws on an empty WebApp object (old clients)', async () => {
    const adapter = new TmaAdapter({});
    expect(() => exercise(adapter)).not.toThrow();
    expect(adapter.getInitData()).toBe('');
    expect(adapter.startParam()).toBeNull();
    await expect(adapter.requestWriteAccess()).resolves.toBe(false);
  });
});

describe('MockAdapter', () => {
  test('never throws and records calls', async () => {
    const adapter = new MockAdapter();
    expect(() => exercise(adapter)).not.toThrow();
    expect(adapter.calls.map((c) => c.method)).toContain('haptic.impact');
    await expect(adapter.requestWriteAccess()).resolves.toBe(false);
  });

  test('serves configured initData and simulates buttons', () => {
    const adapter = new MockAdapter({ initData: 'signed', startParam: 'inv_9' });
    expect(adapter.getInitData()).toBe('signed');
    expect(adapter.startParam()).toBe('inv_9');
    const back = vi.fn();
    const off = adapter.backButton.onClick(back);
    adapter.pressBack();
    off();
    adapter.pressBack();
    expect(back).toHaveBeenCalledTimes(1);
  });
});

describe('getTelegram', () => {
  afterEach(() => setTelegram(null));

  test('returns one shared adapter and can be replaced in tests', () => {
    const first = getTelegram();
    expect(getTelegram()).toBe(first);
    const mock = new MockAdapter({ initData: 'x' });
    setTelegram(mock);
    expect(getTelegram()).toBe(mock);
  });
});

import { beforeEach, describe, expect, test, vi } from 'vitest';

const sdk = vi.hoisted(() => ({
  isTMA: vi.fn(() => true),
  retrieveRawInitData: vi.fn(() => 'user=%7B%7D&hash=abc'),
  retrieveLaunchParams: vi.fn(() => ({
    tgWebAppStartParam: 'invite_1',
    tgWebAppThemeParams: { bg_color: '#000000' },
  })),
  postEvent: vi.fn(),
  on: vi.fn(() => vi.fn()),
  request: vi.fn(() => Promise.resolve({ status: 'allowed' })),
}));

vi.mock('@telegram-apps/sdk-react', () => sdk);

import { TmaAdapter, createTelegramAdapter } from './index';

const plainWindow = { innerHeight: 700 } as unknown as Window;

describe('SDK launch-params path (no telegram-web-app.js)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sdk.isTMA.mockReturnValue(true);
  });

  test('picks TmaAdapter over the SDK bridge', async () => {
    const adapter = createTelegramAdapter(plainWindow);
    expect(adapter).toBeInstanceOf(TmaAdapter);
    expect(adapter.getInitData()).toBe('user=%7B%7D&hash=abc');
    expect(adapter.startParam()).toBe('invite_1');
    expect(adapter.theme().params).toEqual({ bg_color: '#000000' });

    adapter.ready();
    expect(sdk.postEvent).toHaveBeenCalledWith('web_app_ready');
    adapter.haptic.impact('soft');
    expect(sdk.postEvent).toHaveBeenCalledWith('web_app_trigger_haptic_feedback', {
      type: 'impact',
      impact_style: 'soft',
    });
    adapter.closingConfirmation(true);
    expect(sdk.postEvent).toHaveBeenCalledWith('web_app_setup_closing_behavior', {
      need_confirmation: true,
    });
    const off = adapter.backButton.onClick(() => {});
    expect(sdk.on).toHaveBeenCalledWith('back_button_pressed', expect.any(Function));
    off();
    await expect(adapter.requestWriteAccess()).resolves.toBe(true);
  });

  test('falls back to MockAdapter when the SDK finds no launch params', () => {
    sdk.isTMA.mockReturnValue(false);
    expect(createTelegramAdapter(plainWindow).kind).toBe('mock');
  });

  test('falls back to MockAdapter when the SDK throws', () => {
    sdk.isTMA.mockImplementation(() => {
      throw new Error('boom');
    });
    expect(createTelegramAdapter(plainWindow).kind).toBe('mock');
  });

  test('bridge errors never escape the adapter', () => {
    sdk.postEvent.mockImplementation(() => {
      throw new Error('unknown env');
    });
    const adapter = createTelegramAdapter(plainWindow);
    expect(() => {
      adapter.ready();
      adapter.haptic.selection();
      adapter.backButton.show();
      adapter.mainButton.show('x');
      adapter.closingConfirmation(false);
    }).not.toThrow();
  });
});

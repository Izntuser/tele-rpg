import {
  isTMA,
  on,
  postEvent,
  request,
  retrieveLaunchParams,
  retrieveRawInitData,
} from '@telegram-apps/sdk-react';

import type {
  ColorScheme,
  HapticImpactStyle,
  HapticNotificationType,
  TelegramAdapter,
  ViewportInfo,
  WebAppLike,
} from './types';

/** Run ``fn``; on any error return ``fallback``. The adapter must never throw. */
function safe<T>(fn: () => T, fallback: T): T {
  try {
    return fn();
  } catch {
    return fallback;
  }
}

function toNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function stringParams(params: Record<string, unknown> | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(params ?? {})) {
    if (typeof value === 'string') out[key] = value;
  }
  return out;
}

/** Telegram adapter over a `WebApp`-shaped object (the official script or the SDK shim). */
export class TmaAdapter implements TelegramAdapter {
  readonly kind = 'tma' as const;

  constructor(private readonly webApp: WebAppLike) {}

  getInitData(): string {
    return safe(() => (typeof this.webApp.initData === 'string' ? this.webApp.initData : ''), '');
  }

  startParam(): string | null {
    return safe(() => this.webApp.initDataUnsafe?.start_param || null, null);
  }

  ready(): void {
    safe(() => {
      this.webApp.ready?.();
      this.webApp.expand?.();
    }, undefined);
  }

  haptic = {
    impact: (style: HapticImpactStyle = 'light') =>
      safe(() => this.webApp.HapticFeedback?.impactOccurred?.(style), undefined),
    notification: (type: HapticNotificationType) =>
      safe(() => this.webApp.HapticFeedback?.notificationOccurred?.(type), undefined),
    selection: () => safe(() => this.webApp.HapticFeedback?.selectionChanged?.(), undefined),
  };

  backButton = {
    show: () => safe(() => this.webApp.BackButton?.show?.(), undefined),
    hide: () => safe(() => this.webApp.BackButton?.hide?.(), undefined),
    onClick: (callback: () => void) => {
      safe(() => this.webApp.BackButton?.onClick?.(callback), undefined);
      return () => safe(() => this.webApp.BackButton?.offClick?.(callback), undefined);
    },
  };

  mainButton = {
    show: (text: string) =>
      safe(() => {
        this.webApp.MainButton?.setText?.(text);
        this.webApp.MainButton?.show?.();
      }, undefined),
    hide: () => safe(() => this.webApp.MainButton?.hide?.(), undefined),
    setLoading: (loading: boolean) =>
      safe(
        () =>
          loading
            ? this.webApp.MainButton?.showProgress?.(false)
            : this.webApp.MainButton?.hideProgress?.(),
        undefined,
      ),
    onClick: (callback: () => void) => {
      safe(() => this.webApp.MainButton?.onClick?.(callback), undefined);
      return () => safe(() => this.webApp.MainButton?.offClick?.(callback), undefined);
    },
  };

  theme(): { colorScheme: ColorScheme; params: Record<string, string> } {
    return safe(
      () => ({
        colorScheme: this.webApp.colorScheme === 'light' ? 'light' : 'dark',
        params: stringParams(this.webApp.themeParams),
      }),
      { colorScheme: 'dark' as ColorScheme, params: {} },
    );
  }

  viewport(): ViewportInfo {
    const fallbackHeight = typeof window === 'undefined' ? 0 : window.innerHeight;
    return safe(
      () => {
        const height = toNumber(this.webApp.viewportHeight, fallbackHeight);
        const inset = this.webApp.safeAreaInset ?? {};
        return {
          height,
          stableHeight: toNumber(this.webApp.viewportStableHeight, height),
          safeArea: {
            top: toNumber(inset.top, 0),
            bottom: toNumber(inset.bottom, 0),
            left: toNumber(inset.left, 0),
            right: toNumber(inset.right, 0),
          },
        };
      },
      {
        height: fallbackHeight,
        stableHeight: fallbackHeight,
        safeArea: { top: 0, bottom: 0, left: 0, right: 0 },
      },
    );
  }

  requestWriteAccess(): Promise<boolean> {
    return new Promise((resolve) => {
      const call = this.webApp.requestWriteAccess;
      if (typeof call !== 'function') {
        resolve(false);
        return;
      }
      try {
        call.call(this.webApp, (granted: boolean) => resolve(granted === true));
      } catch {
        resolve(false);
      }
    });
  }

  closingConfirmation(enabled: boolean): void {
    safe(
      () =>
        enabled
          ? this.webApp.enableClosingConfirmation?.()
          : this.webApp.disableClosingConfirmation?.(),
      undefined,
    );
  }
}

/**
 * A `WebApp`-shaped object backed by @telegram-apps/sdk (the bridge), for clients that launch
 * the app with launch parameters but without Telegram's `telegram-web-app.js` script.
 */
export function createSdkWebApp(): WebAppLike {
  const launch = safe(() => retrieveLaunchParams(), null);
  const listeners = new Map<() => void, () => void>();
  const button = (event: 'back_button_pressed' | 'main_button_pressed') => ({
    onClick: (cb: () => void) => listeners.set(cb, on(event, cb)),
    offClick: (cb: () => void) => {
      listeners.get(cb)?.();
      listeners.delete(cb);
    },
  });
  let mainText = '';
  const setupMain = (params: { is_visible: boolean; is_progress_visible?: boolean }) =>
    postEvent('web_app_setup_main_button', { text: mainText, is_active: true, ...params });
  return {
    initData: safe(() => retrieveRawInitData() ?? '', ''),
    initDataUnsafe: { start_param: launch?.tgWebAppStartParam ?? undefined },
    themeParams: launch?.tgWebAppThemeParams as Record<string, unknown> | undefined,
    ready: () => postEvent('web_app_ready'),
    expand: () => postEvent('web_app_expand'),
    HapticFeedback: {
      impactOccurred: (style) =>
        postEvent('web_app_trigger_haptic_feedback', { type: 'impact', impact_style: style }),
      notificationOccurred: (type) =>
        postEvent('web_app_trigger_haptic_feedback', {
          type: 'notification',
          notification_type: type,
        }),
      selectionChanged: () =>
        postEvent('web_app_trigger_haptic_feedback', { type: 'selection_change' }),
    },
    BackButton: {
      show: () => postEvent('web_app_setup_back_button', { is_visible: true }),
      hide: () => postEvent('web_app_setup_back_button', { is_visible: false }),
      ...button('back_button_pressed'),
    },
    MainButton: {
      setText: (text) => {
        mainText = text;
      },
      show: () => setupMain({ is_visible: true }),
      hide: () => setupMain({ is_visible: false }),
      showProgress: () => setupMain({ is_visible: true, is_progress_visible: true }),
      hideProgress: () => setupMain({ is_visible: true, is_progress_visible: false }),
      ...button('main_button_pressed'),
    },
    enableClosingConfirmation: () =>
      postEvent('web_app_setup_closing_behavior', { need_confirmation: true }),
    disableClosingConfirmation: () =>
      postEvent('web_app_setup_closing_behavior', { need_confirmation: false }),
    requestWriteAccess: (callback) => {
      request('web_app_request_write_access', 'write_access_requested')
        .then((result) => callback?.(result.status === 'allowed'))
        .catch(() => callback?.(false));
    },
  };
}

/** The Telegram WebApp for this page, or null in a plain browser. Never throws. */
export function detectWebApp(win: Window | undefined): WebAppLike | null {
  if (!win) return null;
  const webApp = safe(() => win.Telegram?.WebApp, undefined);
  if (webApp && typeof webApp.initData === 'string' && webApp.initData.length > 0) {
    return webApp;
  }
  if (safe(() => isTMA(), false)) {
    const shim = safe(() => createSdkWebApp(), null);
    if (shim?.initData) return shim;
  }
  return null;
}

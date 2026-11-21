import type {
  ColorScheme,
  HapticImpactStyle,
  HapticNotificationType,
  TelegramAdapter,
  ViewportInfo,
} from './types';

export interface MockAdapterOptions {
  /** Signed initData to log in with (dev only); '' means "not inside Telegram". */
  initData?: string;
  startParam?: string | null;
  colorScheme?: ColorScheme;
  writeAccess?: boolean;
}

export type MockCall = { method: string; args: unknown[] };

/** Plain-browser stand-in: everything is a recorded no-op. Used in dev and unit tests. */
export class MockAdapter implements TelegramAdapter {
  readonly kind = 'mock' as const;
  readonly calls: MockCall[] = [];
  private readonly back = new Set<() => void>();
  private readonly main = new Set<() => void>();

  constructor(private readonly options: MockAdapterOptions = {}) {}

  private record(method: string, ...args: unknown[]): void {
    this.calls.push({ method, args });
  }

  getInitData(): string {
    return this.options.initData ?? '';
  }

  startParam(): string | null {
    return this.options.startParam ?? null;
  }

  ready(): void {
    this.record('ready');
  }

  haptic = {
    impact: (style: HapticImpactStyle = 'light') => this.record('haptic.impact', style),
    notification: (type: HapticNotificationType) => this.record('haptic.notification', type),
    selection: () => this.record('haptic.selection'),
  };

  backButton = {
    show: () => this.record('backButton.show'),
    hide: () => this.record('backButton.hide'),
    onClick: (callback: () => void) => {
      this.back.add(callback);
      return () => {
        this.back.delete(callback);
      };
    },
  };

  mainButton = {
    show: (text: string) => this.record('mainButton.show', text),
    hide: () => this.record('mainButton.hide'),
    setLoading: (loading: boolean) => this.record('mainButton.setLoading', loading),
    onClick: (callback: () => void) => {
      this.main.add(callback);
      return () => {
        this.main.delete(callback);
      };
    },
  };

  /** Test helpers: simulate the user pressing Telegram's buttons. */
  pressBack(): void {
    this.back.forEach((cb) => cb());
  }

  pressMain(): void {
    this.main.forEach((cb) => cb());
  }

  theme(): { colorScheme: ColorScheme; params: Record<string, string> } {
    return { colorScheme: this.options.colorScheme ?? 'dark', params: {} };
  }

  viewport(): ViewportInfo {
    const height = typeof window === 'undefined' ? 0 : window.innerHeight;
    return { height, stableHeight: height, safeArea: { top: 0, bottom: 0, left: 0, right: 0 } };
  }

  requestWriteAccess(): Promise<boolean> {
    this.record('requestWriteAccess');
    return Promise.resolve(this.options.writeAccess ?? false);
  }

  closingConfirmation(enabled: boolean): void {
    this.record('closingConfirmation', enabled);
  }
}

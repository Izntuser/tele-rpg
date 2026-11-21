export type HapticImpactStyle = 'light' | 'medium' | 'heavy' | 'rigid' | 'soft';
export type HapticNotificationType = 'success' | 'warning' | 'error';
export type ColorScheme = 'light' | 'dark';

export interface SafeAreaInsets {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export interface ViewportInfo {
  height: number;
  stableHeight: number;
  safeArea: SafeAreaInsets;
}

/**
 * The app's only view of Telegram. Every method is safe to call in any environment: it never
 * throws, and features the client does not support become no-ops.
 */
export interface TelegramAdapter {
  readonly kind: 'tma' | 'mock';
  /** Raw, signed initData to send to POST /api/auth/telegram ('' when there is none). */
  getInitData(): string;
  /** The deep-link start parameter (startapp=...), if any. Unsigned: validate on the server. */
  startParam(): string | null;
  /** Tell Telegram the app is ready to be shown (and expand to full height). */
  ready(): void;
  haptic: {
    impact(style?: HapticImpactStyle): void;
    notification(type: HapticNotificationType): void;
    selection(): void;
  };
  backButton: {
    show(): void;
    hide(): void;
    /** Returns an unsubscribe function. */
    onClick(callback: () => void): () => void;
  };
  mainButton: {
    show(text: string): void;
    hide(): void;
    setLoading(loading: boolean): void;
    /** Returns an unsubscribe function. */
    onClick(callback: () => void): () => void;
  };
  theme(): { colorScheme: ColorScheme; params: Record<string, string> };
  viewport(): ViewportInfo;
  /** Ask the user to let the bot message them. Resolves false when unsupported or denied. */
  requestWriteAccess(): Promise<boolean>;
  /** Ask for confirmation before the Mini App is closed (e.g. while a form is dirty). */
  closingConfirmation(enabled: boolean): void;
}

/** The subset of Telegram's `window.Telegram.WebApp` object that the adapter uses. */
export interface WebAppLike {
  initData?: string;
  initDataUnsafe?: { start_param?: string };
  colorScheme?: string;
  themeParams?: Record<string, unknown>;
  viewportHeight?: number;
  viewportStableHeight?: number;
  safeAreaInset?: Partial<SafeAreaInsets>;
  ready?(): void;
  expand?(): void;
  HapticFeedback?: {
    impactOccurred?(style: HapticImpactStyle): void;
    notificationOccurred?(type: HapticNotificationType): void;
    selectionChanged?(): void;
  };
  BackButton?: ButtonLike;
  MainButton?: ButtonLike & {
    setText?(text: string): void;
    showProgress?(leaveActive?: boolean): void;
    hideProgress?(): void;
  };
  enableClosingConfirmation?(): void;
  disableClosingConfirmation?(): void;
  requestWriteAccess?(callback?: (granted: boolean) => void): void;
}

export interface ButtonLike {
  show?(): void;
  hide?(): void;
  onClick?(callback: () => void): void;
  offClick?(callback: () => void): void;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: WebAppLike };
  }
}

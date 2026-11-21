export const ONBOARDING_PATH = '/onboarding';

const ONBOARDING_ROUTE = /^\/onboarding(\/|$)/;
/** Screens a not-yet-onboarded user may open: onboarding itself and an invitation link. */
const EXEMPT = [ONBOARDING_ROUTE, /^\/invite\//];

export function isOnboardingRoute(pathname: string): boolean {
  return ONBOARDING_ROUTE.test(pathname);
}

/** True when a user without `onboarded_at` must be sent to onboarding from `pathname`. */
export function needsOnboarding(onboardedAt: string | null | undefined, pathname: string): boolean {
  return !onboardedAt && !EXEMPT.some((pattern) => pattern.test(pathname));
}

/** Whether a start-param target may be opened before onboarding (only invitations). */
export function deeplinkAllowedBeforeOnboarding(target: string): boolean {
  return /^\/invite\//.test(target);
}

/**
 * Location state for a `replace` redirect at app start. AppLayout treats an entry carrying it
 * as the first history entry, so Telegram's Back goes Home instead of leaving the app.
 */
export const FIRST_ENTRY_STATE = { deeplink: true } as const;

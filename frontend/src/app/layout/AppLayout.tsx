import { useEffect, useRef, useState } from 'react';
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router';

import { useAuth } from '../../features/auth/context';
import { NotificationBell } from '../../features/notifications/NotificationBell';
import { AchievementToaster } from '../../features/stats/AchievementToast';
import {
  FIRST_ENTRY_STATE,
  ONBOARDING_PATH,
  deeplinkAllowedBeforeOnboarding,
  isOnboardingRoute,
  needsOnboarding,
} from '../../features/onboarding/redirect';
import { setLocale } from '../../i18n';
import { deeplinkToRoute } from '../../lib/deeplink';
import { BottomNav } from './BottomNav';

/** Full-screen flows that hide the tab bar. */
const NO_NAV = [/^\/onboarding(\/|$)/, /^\/invite\//];

/** Shell below <AuthGate>: locale, theme, safe areas, deeplink, BackButton, the header bell and
 * the bottom nav. */
export function AppLayout() {
  const { state, telegram } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const startParam = state.status === 'authenticated' ? state.startParam : null;
  const locale = state.status === 'authenticated' ? state.user.locale : null;
  const onboardedAt = state.status === 'authenticated' ? state.user.onboarded_at : null;
  // A user without a character goes to onboarding first (invitation links excepted).
  const mustOnboard = state.status === 'authenticated' && needsOnboarding(onboardedAt, location.pathname);
  const isRoot = location.pathname === '/';
  const deeplinkTarget = deeplinkToRoute(startParam ?? telegram.startParam());
  const [deeplinkDone, setDeeplinkDone] = useState(false);
  // A new user launched from an invitation goes to the invitation, not to onboarding. Doing it
  // in the redirect itself (not only in the effect below) keeps a re-run <Navigate> (StrictMode
  // runs effects twice) from overriding the deeplink with /onboarding.
  const onboardingTarget =
    !deeplinkDone && deeplinkAllowedBeforeOnboarding(deeplinkTarget) ? deeplinkTarget : ONBOARDING_PATH;
  // The first history entry is either the cold-start entry or the one the deeplink redirect
  // replaced it with (marked via location state, since a replace gives it a new key).
  const isInitialEntry =
    location.key === 'default' || (location.state as { deeplink?: boolean } | null)?.deeplink === true;

  useEffect(() => {
    setLocale(locale);
  }, [locale]);

  // Dark is the default (theme.css :root); only an explicit light scheme switches it.
  useEffect(() => {
    const { colorScheme } = telegram.theme();
    document.documentElement.dataset.theme = colorScheme === 'light' ? 'light' : 'dark';
    const { safeArea } = telegram.viewport();
    const root = document.documentElement.style;
    for (const side of ['top', 'bottom', 'left', 'right'] as const) {
      // Telegram reports 0 when it has no inset; keep the CSS env() fallback in that case.
      if (safeArea[side] > 0) root.setProperty(`--safe-${side}`, `${safeArea[side]}px`);
    }
  }, [telegram]);

  // Open the screen a deeplink points at, once, when the app was launched on Home.
  const handledDeeplink = useRef(false);
  useEffect(() => {
    if (handledDeeplink.current) return;
    handledDeeplink.current = true;
    const target = deeplinkTarget;
    if (!onboardedAt && !deeplinkAllowedBeforeOnboarding(target)) return;
    if (target !== '/' && isRoot) {
      void navigate(target, { replace: true, state: FIRST_ENTRY_STATE });
    }
  }, [deeplinkTarget, isRoot, onboardedAt, navigate]);

  // The start param applies to the launch only: once the app has left "/", it is spent.
  useEffect(() => {
    if (!isRoot) setDeeplinkDone(true);
  }, [isRoot]);

  // Onboarding has its own in-page Back; Telegram's Back would only bounce back to it.
  const hideBack = isRoot || (!onboardedAt && isOnboardingRoute(location.pathname));

  useEffect(() => {
    if (hideBack) {
      telegram.backButton.hide();
      return;
    }
    telegram.backButton.show();
    const off = telegram.backButton.onClick(() => {
      // A deeplink can be the first history entry; going back would leave the app.
      void (isInitialEntry ? navigate('/', { replace: true }) : navigate(-1));
    });
    return () => {
      off();
    };
  }, [telegram, hideBack, isInitialEntry, navigate]);

  const showNav = !NO_NAV.some((pattern) => pattern.test(location.pathname));
  // The bell needs an onboarded user (the inbox is theirs); full-screen flows have no header.
  const showBell = showNav && Boolean(onboardedAt) && !mustOnboard;
  return (
    <div
      className="min-h-screen bg-bg text-fg"
      style={{
        paddingTop: 'var(--safe-top)',
        paddingLeft: 'var(--safe-left)',
        paddingRight: 'var(--safe-right)',
        paddingBottom: showNav ? 'calc(var(--nav-height) + var(--safe-bottom))' : 'var(--safe-bottom)',
      }}
    >
      {showBell ? (
        <header data-testid="app-header" className="mx-auto flex max-w-md justify-end px-2 pt-1">
          <NotificationBell />
        </header>
      ) : null}
      <main className="mx-auto max-w-md">
        {mustOnboard ? <Navigate to={onboardingTarget} replace state={FIRST_ENTRY_STATE} /> : <Outlet />}
      </main>
      {showBell ? <AchievementToaster /> : null}
      {showNav ? <BottomNav /> : null}
    </div>
  );
}

import { useEffect, useRef } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router';

import { useAuth } from '../../features/auth/context';
import { setLocale } from '../../i18n';
import { deeplinkToRoute } from '../../lib/deeplink';
import { BottomNav } from './BottomNav';

/** Full-screen flows that hide the tab bar. */
const NO_NAV = [/^\/onboarding(\/|$)/, /^\/invite\//];

/** Shell below <AuthGate>: locale, theme, safe areas, deeplink, BackButton and the bottom nav. */
export function AppLayout() {
  const { state, telegram } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const startParam = state.status === 'authenticated' ? state.startParam : null;
  const locale = state.status === 'authenticated' ? state.user.locale : null;
  const isRoot = location.pathname === '/';
  const isInitialEntry = location.key === 'default';

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
    const target = deeplinkToRoute(startParam ?? telegram.startParam());
    if (target !== '/' && isRoot) void navigate(target, { replace: true });
  }, [startParam, telegram, isRoot, navigate]);

  useEffect(() => {
    if (isRoot) {
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
  }, [telegram, isRoot, isInitialEntry, navigate]);

  const showNav = !NO_NAV.some((pattern) => pattern.test(location.pathname));
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
      <main className="mx-auto max-w-md">
        <Outlet />
      </main>
      {showNav ? <BottomNav /> : null}
    </div>
  );
}

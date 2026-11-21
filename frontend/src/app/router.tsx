import { Navigate, createBrowserRouter, createMemoryRouter, type RouteObject } from 'react-router';

import { CompanionPage } from '../features/companion/pages/CompanionPage';
import { GoalsPage } from '../features/goals/pages/GoalsPage';
import { HomePage } from '../features/home/pages/HomePage';
import { InvitePage } from '../features/invitations/pages/InvitePage';
import { NotificationsPage } from '../features/notifications/pages/NotificationsPage';
import { OnboardingPage } from '../features/onboarding/pages/OnboardingPage';
import { QuestDetailPage } from '../features/quests/pages/QuestDetailPage';
import { QuestNewPage } from '../features/quests/pages/QuestNewPage';
import { QuestsPage } from '../features/quests/pages/QuestsPage';
import { SettingsPage } from '../features/settings/pages/SettingsPage';
import { InventoryPage } from '../features/shop/pages/InventoryPage';
import { ShopManagePage } from '../features/shop/pages/ShopManagePage';
import { ShopPage } from '../features/shop/pages/ShopPage';
import { JournalPage } from '../features/stats/pages/JournalPage';
import { StatsPage } from '../features/stats/pages/StatsPage';
import { WishlistPage } from '../features/wishlist/pages/WishlistPage';
import { AppLayout } from './layout/AppLayout';

/** Every ARCHITECTURE section 6 route; an unknown path redirects to Home. */
export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'onboarding/*', element: <OnboardingPage /> },
      { path: 'invite/:token', element: <InvitePage /> },
      { path: 'quests', element: <QuestsPage /> },
      { path: 'quests/new', element: <QuestNewPage /> },
      { path: 'quests/:id', element: <QuestDetailPage /> },
      { path: 'shop', element: <ShopPage /> },
      { path: 'shop/inventory', element: <InventoryPage /> },
      { path: 'shop/manage', element: <ShopManagePage /> },
      { path: 'stats', element: <StatsPage /> },
      { path: 'stats/journal', element: <JournalPage /> },
      { path: 'companion', element: <CompanionPage /> },
      { path: 'me/goals', element: <GoalsPage /> },
      { path: 'me/wishlist', element: <WishlistPage /> },
      { path: 'notifications', element: <NotificationsPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
];

export type AppRouter = ReturnType<typeof createBrowserRouter>;

export const createAppRouter = (): AppRouter => createBrowserRouter(routes);

/** Tests: the same route table on an in-memory history. */
export const createTestRouter = (initialEntries: string[] = ['/']): AppRouter =>
  createMemoryRouter(routes, { initialEntries });

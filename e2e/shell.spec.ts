import { USERS, expect, test } from './fixtures/telegram';

test.use({ viewport: { width: 390, height: 844 } });

const TABS = [
  { key: 'home', path: '/', page: 'page-home' },
  { key: 'quests', path: '/quests', page: 'page-quests' },
  { key: 'shop', path: '/shop', page: 'page-shop' },
  { key: 'stats', path: '/stats', page: 'page-stats' },
  { key: 'companion', path: '/companion', page: 'page-companion' },
] as const;

test('@S04 bottom nav taps all five tabs as user A', async ({ page, telegram }) => {
  await telegram('A');
  await page.goto('/');
  await expect(page.getByTestId('user-greeting')).toContainText(USERS.A.first_name);
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

  for (const tab of [...TABS.slice(1), TABS[0]]) {
    await page.getByTestId(`nav-${tab.key}`).click();
    await expect(page.getByTestId(tab.page)).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`${tab.path === '/' ? '/$' : `${tab.path}$`}`));
    await expect(page.getByTestId(`nav-${tab.key}`)).toHaveAttribute('aria-current', 'page');
    await expect(page.locator('nav a[aria-current="page"]')).toHaveCount(1);
  }

  await page.getByTestId('nav-quests').click();
  await expect(page.getByTestId('page-quests')).toBeVisible();
  await page.screenshot({ path: 'docs/screens/S04.png' });
});

test('@S04 unknown routes go home and the Telegram BackButton follows the route', async ({
  page,
  telegram,
}) => {
  await telegram('A');
  await page.goto('/no/such/page');
  await expect(page.getByTestId('page-home')).toBeVisible();
  await expect(page).toHaveURL(/\/$/);

  const calls = () =>
    page.evaluate(() =>
      (window as unknown as { __telegramCalls: { method: string }[] }).__telegramCalls.map((c) => c.method),
    );
  // The redirect passes through a non-root route, so judge by the last BackButton call.
  const lastBackButton = async () => (await calls()).filter((m) => m === 'BackButton.show' || m === 'BackButton.hide').at(-1);
  await expect.poll(lastBackButton).toBe('BackButton.hide');

  await page.getByTestId('nav-shop').click();
  await expect(page.getByTestId('page-shop')).toBeVisible();
  await expect.poll(lastBackButton).toBe('BackButton.show');
});

test('@S04 a start param deeplink opens its screen', async ({ page, telegram }) => {
  await telegram('A', { startParam: 'q_77' });
  await page.goto('/');
  await expect(page).toHaveURL(/\/quests\/77$/);
  await expect(page.getByTestId('page-quest-detail')).toBeVisible();
});

test('@S04 Back after a deeplink goes Home instead of leaving the app', async ({ page, telegram }) => {
  await telegram('A', { startParam: 'q_77' });
  await page.goto('/');
  await expect(page.getByTestId('page-quest-detail')).toBeVisible();
  await page.evaluate(() => (window as unknown as { __telegramClick: (n: string) => void }).__telegramClick('BackButton'));
  await expect(page.getByTestId('page-home')).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
});

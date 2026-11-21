import { USERS, expect, onboardViaApi, signInitData, test } from './fixtures/telegram';

test.use({ viewport: { width: 390, height: 844 } });

test('@S03 user A signs in with Telegram initData and sees their name on home', async ({
  page,
  telegram,
  request,
}) => {
  // A already has a character (S05 onboarding), so the sign-in lands on Home.
  await onboardViaApi(request, 'A');
  const authRequests: string[] = [];
  page.on('request', (req) => {
    if (req.url().includes('/api/')) authRequests.push(req.url());
  });
  await telegram('A');
  const login = page.waitForResponse((r) => r.url().endsWith('/api/auth/telegram'));
  await page.goto('/');

  const response = await login;
  expect(response.status()).toBe(200);
  await expect(page.getByTestId('page-home')).toBeVisible();
  await expect(page.getByTestId('user-greeting')).toContainText(USERS.A.first_name);
  await expect(page.getByRole('heading', { name: 'Modern Life RPG' })).toBeVisible();

  // The JWT stays in memory: nothing in storage, cookies or URLs.
  const jwt = ((await response.json()) as { jwt: string }).jwt;
  const storage = await page.evaluate(() => ({
    local: Object.keys(localStorage).length,
    session: Object.keys(sessionStorage).length,
    cookie: document.cookie,
  }));
  expect(storage).toEqual({ local: 0, session: 0, cookie: '' });
  expect(authRequests.some((url) => url.includes(jwt))).toBe(false);
  // The app told Telegram it is ready.
  const calls = await page.evaluate(
    () => (window as unknown as { __telegramCalls: { method: string }[] }).__telegramCalls,
  );
  expect(calls.map((c) => c.method)).toContain('ready');

  await page.screenshot({ path: 'docs/screens/S03.png' });
});

test('@S03 user B gets their own account with the uk locale', async ({ page, telegram, request }) => {
  await telegram('B');
  const login = page.waitForResponse((r) => r.url().endsWith('/api/auth/telegram'));
  await page.goto('/');
  const body = (await (await login).json()) as { user: { locale: string; tg_user_id: number } };
  expect(body.user).toMatchObject({ locale: 'uk', tg_user_id: USERS.B.id });
  await expect(page.getByTestId('user-greeting')).toContainText(USERS.B.first_name);

  // /auth/me needs the JWT.
  expect((await request.get('/api/auth/me')).status()).toBe(401);
});

test('@S03 forged initData is rejected with an inline error', async ({ page, telegram }) => {
  const forged = signInitData(USERS.A, { botToken: '111:NOT-THE-BOT-TOKEN' });
  await telegram('A', { initData: forged });
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('rejected');
  await expect(page.getByTestId('user-greeting')).toHaveCount(0);
});

test('@S03 a plain browser is asked to open the app from Telegram', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Open this app from Telegram')).toBeVisible();
});

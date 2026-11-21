import { injectTelegram, apiLogin, expect, onboardViaApi, test } from './fixtures/telegram';

const VIEWPORT = { width: 390, height: 844 };
test.use({ viewport: VIEWPORT });

test('@S06 A invites, B opens startapp=invite_<token> before onboarding, accepts, and both see each other', async ({
  page,
  browser,
  request,
  telegram,
}) => {
  await onboardViaApi(request, 'A', { name: 'Aria' });

  // A creates an invite link from the Companion tab.
  await telegram('A');
  await page.goto('/companion');
  await expect(page.getByText('You have no companion yet')).toBeVisible();
  await page.getByTestId('invite-create').click();
  const link = await page.getByTestId('invite-link').inputValue();
  const match = /^https:\/\/t\.me\/[A-Za-z0-9_]+\/[A-Za-z0-9_]+\?startapp=invite_([A-Za-z0-9_-]+)$/.exec(link);
  expect(match, link).not.toBeNull();
  const token = match![1]!;

  // B is brand new and launches the Mini App from the link (second browser context).
  const contextB = await browser.newContext({ viewport: VIEWPORT });
  const pageB = await contextB.newPage();
  try {
    await injectTelegram(pageB, 'B', { startParam: `invite_${token}` });
    await pageB.goto('/');
    await expect(pageB).toHaveURL(new RegExp(`/invite/${token}$`));
    await expect(pageB.getByTestId('invite-inviter')).toContainText('Aria');
    // The token is in this URL: the page must never send it on as a Referer.
    await expect(pageB.locator('meta[name="referrer"]')).toHaveAttribute('content', 'no-referrer');
    // Not onboarded yet: create the character first, then come back to the invitation.
    await expect(pageB.getByTestId('invite-accept')).toHaveCount(0);
    await pageB.getByTestId('invite-onboard').click();
    await expect(pageB).toHaveURL(/\/onboarding$/);
    await pageB.getByTestId('onboarding-next').click();
    await pageB.getByTestId('onboarding-next').click();
    await pageB.getByTestId('onboarding-finish').click();
    await expect(pageB).toHaveURL(new RegExp(`/invite/${token}$`));
    const accepted = pageB.waitForResponse((r) => r.url().endsWith('/api/partnership/invitations/accept'));
    await pageB.getByTestId('invite-accept').click();
    expect((await accepted).status()).toBe(200);

    // B lands on Companion and sees A.
    await expect(pageB).toHaveURL(/\/companion$/);
    await expect(pageB.getByTestId('companion-card').getByTestId('companion-name')).toHaveText('Aria');
    await expect(pageB.getByTestId('companion-attributes').getByRole('listitem')).toHaveCount(6);

    // The token was single-use.
    const jwtB = await apiLogin(request, 'B');
    const again = await request.post('/api/partnership/invitations/accept', {
      headers: { Authorization: `Bearer ${jwtB}` },
      data: { token },
    });
    expect(again.status()).toBe(410);
  } finally {
    await contextB.close();
  }

  // A sees B (name prefilled from Telegram during B's onboarding) and is B's Game Master.
  await page.reload();
  await expect(page.getByTestId('companion-card').getByTestId('companion-name')).toHaveText('Bohdan');
  await expect(page.getByTestId('companion-profile')).toContainText('You are the Game Master');
  await page.screenshot({ path: 'docs/screens/S06.png' });
});

test('@S06 settings: language and timezone, leave with typed confirmation, delete account', async ({
  page,
  request,
  telegram,
}) => {
  await onboardViaApi(request, 'A', { name: 'Aria' });
  await onboardViaApi(request, 'B', { name: 'Bold' });
  const jwtA = await apiLogin(request, 'A');
  const invite = await request.post('/api/partnership/invitations', {
    headers: { Authorization: `Bearer ${jwtA}` },
  });
  const { token } = (await invite.json()) as { token: string };
  const jwtB = await apiLogin(request, 'B');
  const accept = await request.post('/api/partnership/invitations/accept', {
    headers: { Authorization: `Bearer ${jwtB}` },
    data: { token },
  });
  expect(accept.status()).toBe(200);

  await telegram('A');
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();

  // Language: the UI re-renders in Ukrainian.
  await page.getByLabel('App language').selectOption('uk');
  await expect(page.getByRole('heading', { name: 'Налаштування', level: 1 })).toBeVisible();
  // Timezone.
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/character') && r.request().method() === 'PATCH');
  await page.getByLabel('Ваш часовий пояс').selectOption('Europe/Berlin');
  expect((await saved).status()).toBe(200);
  const me = (await (await request.get('/api/character', { headers: { Authorization: `Bearer ${jwtA}` } })).json()) as {
    locale: string;
    timezone: string;
  };
  expect(me).toMatchObject({ locale: 'uk', timezone: 'Europe/Berlin' });
  await page.getByLabel('Мова застосунку').selectOption('en');
  await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();

  // Leave: the confirm button stays disabled until LEAVE is typed.
  await expect(page.getByTestId('settings-companion')).toContainText('Bold');
  await page.getByTestId('settings-leave').click();
  const dialog = page.getByRole('dialog');
  const confirmLeave = dialog.getByRole('button', { name: 'Leave partnership' });
  await expect(confirmLeave).toBeDisabled();
  await dialog.getByLabel('Type "LEAVE" to confirm').fill('LEAVE');
  await confirmLeave.click();
  await expect(page.getByText('You have no companion yet.')).toBeVisible();
  await page.getByTestId('nav-companion').click();
  await expect(page.getByTestId('invite-panel')).toBeVisible();

  // Delete account: typed confirmation, then the session ends.
  await page.goto('/settings');
  await page.getByTestId('settings-delete').click();
  const confirmDelete = page.getByRole('dialog').getByRole('button', { name: 'Delete account' });
  await expect(confirmDelete).toBeDisabled();
  await page.getByRole('dialog').getByLabel('Type "DELETE" to confirm').fill('DELETE');
  await confirmDelete.click();
  await expect(page.getByRole('alert')).toHaveText('This account has been deleted.');
  // The JWT issued before the deletion no longer works.
  const after = await request.get('/api/auth/me', { headers: { Authorization: `Bearer ${jwtA}` } });
  expect(after.status()).toBe(401);
});

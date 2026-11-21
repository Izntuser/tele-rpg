import type { APIRequestContext } from '@playwright/test';

import { apiLogin, expect, injectTelegram, onboardViaApi, test } from './fixtures/telegram';

const VIEWPORT = { width: 390, height: 844 };
test.use({ viewport: VIEWPORT });

/** A invites, B accepts: A is B's Game Master. */
async function pair(request: APIRequestContext): Promise<{ jwtA: string; jwtB: string }> {
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
  return { jwtA, jwtB };
}

test('@S09 A creates a Normal / Physical / 50 Gold quest, B accepts and submits, A confirms, B is paid', async ({
  page,
  browser,
  request,
  telegram,
}) => {
  const { jwtB } = await pair(request);

  // A: create the quest from the sheet.
  await telegram('A');
  await page.goto('/quests');
  await expect(page.getByRole('tablist').getByRole('tab')).toHaveCount(6);
  await page.getByTestId('quest-fab').click();
  await expect(page).toHaveURL(/\/quests\/new$/);
  await expect(page.getByTestId('gm-label')).toHaveText('You are the Game Master');
  await page.getByTestId('quest-title').fill('Morning run');
  await page.getByTestId('attribute-physical').click();
  await page.getByTestId('difficulty-normal').click();
  await expect(page.getByTestId('quest-gold')).toHaveValue('50');
  const created = page.waitForResponse((r) => r.url().endsWith('/api/quests') && r.request().method() === 'POST');
  await page.getByTestId('quest-create').click();
  expect((await created).status()).toBe(201);
  await expect(page).toHaveURL(/\/quests\/\d+$/);
  await expect(page.getByTestId('quest-terms')).toContainText('Morning run');
  await expect(page.getByTestId('quest-cancel')).toBeVisible();
  await expect(page.getByTestId('quest-accept')).toHaveCount(0);

  // B: the offer shows on Home and in Offers; accept, then submit.
  const contextB = await browser.newContext({ viewport: VIEWPORT });
  const pageB = await contextB.newPage();
  try {
    await injectTelegram(pageB, 'B');
    await pageB.goto('/');
    await expect(pageB.getByTestId('today-offers')).toContainText('Morning run');
    await pageB.goto('/quests');
    await pageB.getByTestId('quest-tab-offers').click();
    await pageB.getByTestId('quest-card').filter({ hasText: 'Morning run' }).click();
    await expect(pageB.getByTestId('gm-label')).toHaveCount(0);
    const accepted = pageB.waitForResponse((r) => r.url().endsWith('/accept'));
    await pageB.getByTestId('quest-accept').click();
    expect((await accepted).status()).toBe(200);
    await pageB.getByTestId('submit-comment').fill('Ran 5k');
    const submitted = pageB.waitForResponse((r) => r.url().endsWith('/submit'));
    await pageB.getByTestId('quest-submit').click();
    const submitRequest = (await submitted).request();
    expect((await submitted).status()).toBe(200);
    expect(await submitRequest.headerValue('idempotency-key')).toBeTruthy();
    await expect(pageB.getByTestId('quest-waiting')).toBeVisible();

    // A: confirm from the To confirm tab, see the celebration.
    await page.goto('/quests');
    await page.getByTestId('quest-tab-toConfirm').click();
    await page.getByTestId('quest-card').filter({ hasText: 'Morning run' }).click();
    await expect(page.getByTestId('gm-label')).toBeVisible();
    await page.getByTestId('quest-confirm').click();
    const overlay = page.getByRole('alertdialog', { name: 'Quest complete!' });
    await expect(overlay).toContainText('50 gold');
    await page.screenshot({ path: 'docs/screens/S09.png' });
    await overlay.getByRole('button', { name: 'Continue' }).click();
    await expect(page.getByTestId('quest-actions')).toHaveCount(0);

    // B: 50 Gold and 50 XP on Home and from the API.
    await pageB.goto('/');
    await expect(pageB.getByTestId('character-header')).toContainText('50 / ');
    const me = (await (
      await request.get('/api/character', { headers: { Authorization: `Bearer ${jwtB}` } })
    ).json()) as { gold: number; total_xp: number };
    expect(me).toMatchObject({ gold: 50, total_xp: 50 });
  } finally {
    await contextB.close();
  }
});

test('@S09 presets, the economy estimate and an unpaired user', async ({ page, request, telegram }) => {
  await onboardViaApi(request, 'A', { name: 'Aria' });
  await telegram('A');

  // Unpaired: the invite CTA replaces the tabs and the create button.
  await page.goto('/quests');
  await expect(page.getByText('Quests need a companion')).toBeVisible();
  await expect(page.getByTestId('invite-panel')).toBeVisible();
  await expect(page.getByRole('tablist')).toHaveCount(0);

  await onboardViaApi(request, 'B', { name: 'Bold' });
  const jwtA = await apiLogin(request, 'A');
  const invite = await request.post('/api/partnership/invitations', { headers: { Authorization: `Bearer ${jwtA}` } });
  const { token } = (await invite.json()) as { token: string };
  const jwtB = await apiLogin(request, 'B');
  await request.post('/api/partnership/invitations/accept', {
    headers: { Authorization: `Bearer ${jwtB}` },
    data: { token },
  });

  await page.goto('/quests/new');
  await page.getByTestId('preset-toggle').click();
  await expect(page.getByTestId('preset-option')).toHaveCount(24);
  await page.getByTestId('preset-option').filter({ hasText: 'Read for 30 minutes' }).click();
  await expect(page.getByTestId('quest-title')).toHaveValue('Read for 30 minutes');
  // A daily preset opens the options and shows the estimate: 20 gold a day.
  await expect(page.getByTestId('quest-estimate')).toContainText('140 gold a week');
  await expect(page.getByTestId('quest-estimate')).toContainText('600 gold a month');

  // Save as a template; it is listed under "My templates" and can be deleted.
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/quest-presets') && r.request().method() === 'POST');
  await page.getByTestId('save-template').click();
  expect((await saved).status()).toBe(201);
  await page.getByTestId('preset-toggle').click();
  await expect(page.getByTestId('preset-option')).toHaveCount(25);
  await page.getByRole('button', { name: 'Delete template Read for 30 minutes' }).click();
  await expect(page.getByTestId('preset-option')).toHaveCount(24);
});

import { USERS, apiLogin, injectTelegram, expect, test } from './fixtures/telegram';

const VIEWPORT = { width: 390, height: 844 };
test.use({ viewport: VIEWPORT });

/**
 * The P0 acceptance test (ARCHITECTURE s10): two browser contexts walk the whole core loop
 * through the UI, from first launch to a fulfilled reward.
 */
test('@P0 @S11 the core loop: onboard, pair, quest, gold, reward, fulfilled', async ({
  page,
  browser,
  request,
  telegram,
}) => {
  // 1-2. A authenticates automatically and completes onboarding.
  await telegram('A');
  await page.goto('/');
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByTestId('onboarding-name').fill('Aria');
  await page.getByTestId('onboarding-next').click();
  await page.getByTestId('onboarding-next').click();
  await page.getByTestId('onboarding-finish').click();
  await expect(page.getByTestId('onboarding-step-invite')).toBeVisible();
  await page.getByTestId('onboarding-start').click();
  await expect(page.getByTestId('character-name')).toHaveText('Aria');

  // 3. A creates an invite; B opens startapp=invite_<token>, onboards and accepts.
  await page.goto('/companion');
  await page.getByTestId('invite-create').click();
  const link = await page.getByTestId('invite-link').inputValue();
  const token = /startapp=invite_([A-Za-z0-9_-]+)$/.exec(link)?.[1];
  expect(token, link).toBeTruthy();

  const contextB = await browser.newContext({ viewport: VIEWPORT });
  const pageB = await contextB.newPage();
  try {
    await injectTelegram(pageB, { ...USERS.B, language_code: 'en' }, { startParam: `invite_${token}` });
    await pageB.goto('/');
    await expect(pageB).toHaveURL(new RegExp(`/invite/${token}$`));
    await pageB.getByTestId('invite-onboard').click();
    await pageB.getByTestId('onboarding-name').fill('Bold');
    await pageB.getByTestId('onboarding-next').click();
    await pageB.getByTestId('onboarding-next').click();
    await pageB.getByTestId('onboarding-finish').click();
    await expect(pageB).toHaveURL(new RegExp(`/invite/${token}$`));
    await pageB.getByTestId('invite-accept').click();
    await expect(pageB).toHaveURL(/\/companion$/);
    await expect(pageB.getByTestId('companion-card').getByTestId('companion-name')).toHaveText('Aria');

    // 4. A creates a Normal / Physical / 50 Gold quest; B accepts.
    await page.goto('/quests/new');
    await page.getByTestId('quest-title').fill('Morning run');
    await page.getByTestId('attribute-physical').click();
    await page.getByTestId('difficulty-normal').click();
    await expect(page.getByTestId('quest-gold')).toHaveValue('50');
    await page.getByTestId('quest-create').click();
    await expect(page).toHaveURL(/\/quests\/\d+$/);

    await pageB.goto('/quests');
    await pageB.getByTestId('quest-tab-offers').click();
    await pageB.getByTestId('quest-card').filter({ hasText: 'Morning run' }).click();
    await pageB.getByTestId('quest-accept').click();

    // 5. B submits; A confirms.
    await pageB.getByTestId('quest-submit').click();
    await expect(pageB.getByTestId('quest-waiting')).toBeVisible();
    await page.goto('/quests');
    await page.getByTestId('quest-tab-toConfirm').click();
    await page.getByTestId('quest-card').filter({ hasText: 'Morning run' }).click();
    await page.getByTestId('quest-confirm').click();
    await page.getByRole('alertdialog', { name: 'Quest complete!' }).getByRole('button', { name: 'Continue' }).click();

    // 6. B has 50 Gold, 50 XP and Physical XP 50.
    await pageB.getByTestId('nav-home').click();
    await expect(pageB.getByTestId('character-header')).toContainText('50 / ');
    await expect(pageB.getByLabel('50 gold').first()).toBeVisible();
    const me = (await (
      await request.get('/api/character', { headers: { Authorization: `Bearer ${await apiLogin(request, 'B')}` } })
    ).json()) as { gold: number; total_xp: number; attributes: { attribute: string; xp: number }[] };
    expect(me).toMatchObject({ gold: 50, total_xp: 50 });
    expect(me.attributes.find((a) => a.attribute === 'physical')?.xp).toBe(50);

    // 7. A creates "Movie night" at 40 Gold; B buys it and the balance is 10.
    await page.goto('/shop/manage');
    await page.getByTestId('reward-add').click();
    await page.getByTestId('reward-title').fill('Movie night');
    await page.getByTestId('reward-price').fill('40');
    await page.getByTestId('reward-save').click();
    await expect(page.getByTestId('my-reward')).toContainText('Movie night');

    await pageB.getByTestId('nav-shop').click();
    await expect(pageB.getByTestId('page-shop')).toBeVisible();
    await expect(pageB.getByTestId('shop-balance')).toContainText('50');
    await pageB.getByTestId('reward-card').filter({ hasText: 'Movie night' }).getByTestId('reward-buy').click();
    await pageB.getByRole('dialog', { name: 'Buy Movie night?' }).getByRole('button', { name: 'Buy' }).click();
    const overlay = pageB.getByRole('alertdialog', { name: 'Reward claimed!' });
    await expect(overlay).toBeVisible();
    await overlay.getByRole('button', { name: 'Continue' }).click();
    await expect(pageB.getByTestId('shop-balance')).toContainText('10');

    // 8. B requests it; A schedules and fulfils it.
    await pageB.getByTestId('shop-nav-inventory').click();
    await pageB.getByTestId('voucher-request').click();
    await expect(pageB.getByTestId('voucher-group-requested')).toContainText('Movie night');

    await page.reload();
    const queued = page.getByTestId('request-list').getByTestId('voucher-card');
    await expect(queued).toHaveCount(1);
    await queued.getByTestId('voucher-schedule-open').click();
    await page.getByTestId('schedule-when').fill('2999-01-01T20:00');
    await page.getByTestId('schedule-save').click();
    await queued.getByTestId('voucher-fulfill').click();
    await expect(page.getByTestId('requests-empty')).toBeVisible();

    // B's inventory shows Fulfilled.
    await pageB.reload();
    await expect(pageB.getByTestId('voucher-group-fulfilled')).toContainText('Movie night');
    await expect(pageB.getByTestId('voucher-status')).toHaveText('Fulfilled');
  } finally {
    await contextB.close();
  }
});

import type { APIRequestContext } from '@playwright/test';

import { USERS, apiLogin, expect, injectTelegram, onboardViaApi, test } from './fixtures/telegram';

const VIEWPORT = { width: 390, height: 844 };
test.use({ viewport: VIEWPORT });

const bearer = (jwt: string) => ({ Authorization: `Bearer ${jwt}` });

/** A invites, B accepts; B then earns 50 Gold from a quest A confirms, all through the API. */
async function pairAndPay(request: APIRequestContext): Promise<{ jwtA: string; jwtB: string }> {
  await onboardViaApi(request, 'A', { name: 'Aria' });
  await onboardViaApi(request, 'B', { name: 'Bold' });
  const jwtA = await apiLogin(request, 'A');
  const invite = await request.post('/api/partnership/invitations', { headers: bearer(jwtA) });
  const { token } = (await invite.json()) as { token: string };
  const jwtB = await apiLogin(request, 'B');
  const accept = await request.post('/api/partnership/invitations/accept', {
    headers: bearer(jwtB),
    data: { token },
  });
  expect(accept.status()).toBe(200);

  const created = await request.post('/api/quests', {
    headers: { ...bearer(jwtA), 'Idempotency-Key': 'shop-quest-create' },
    data: {
      title: 'Morning run',
      attribute: 'physical',
      difficulty: 'normal',
      gold: 50,
      recurrence: 'once',
      confirmation: 'manual',
      photo_required: false,
    },
  });
  expect(created.status()).toBe(201);
  const id = ((await created.json()) as { occurrence: { id: number } }).occurrence.id;
  const post = async (jwt: string, path: string, key: string) => {
    const response = await request.post(`/api/quests/${id}/${path}`, {
      headers: { ...bearer(jwt), 'Idempotency-Key': key },
    });
    expect(response.status(), await response.text()).toBe(200);
  };
  await post(jwtB, 'accept', 'shop-quest-accept');
  await post(jwtB, 'submit', 'shop-quest-submit');
  await post(jwtA, 'confirm', 'shop-quest-confirm');
  return { jwtA, jwtB };
}

test('@S11 the shop: manage, buy, request, schedule, fulfil, dispute and refund', async ({
  page,
  browser,
  request,
  telegram,
}) => {
  const { jwtA, jwtB } = await pairAndPay(request);
  // B's Telegram language is Ukrainian; the assertions below read English.
  const locale = await request.patch('/api/character', {
    headers: bearer(jwtB),
    data: { locale: 'en', timezone: 'UTC' },
  });
  expect(locale.status()).toBe(200);
  const wish = await request.post('/api/wishlist', { headers: bearer(jwtB), data: { title: 'Spa day' } });
  expect(wish.status()).toBe(201);
  const trip = await request.post('/api/rewards', {
    headers: bearer(jwtA),
    data: { title: 'Weekend trip', price: 500 },
  });
  expect(trip.status()).toBe(201);

  // A manages the shop: create a reward, then turn B's wish into one.
  await telegram('A');
  await page.goto('/shop/manage');
  await expect(page.getByTestId('my-reward')).toHaveCount(1);
  await page.getByTestId('reward-add').click();
  await expect(page.getByTestId('reward-save')).toBeDisabled();
  await page.getByTestId('reward-title').fill('Movie night');
  await page.getByTestId('reward-price').fill('40');
  await page.getByTestId('reward-quantity-limit').fill('2');
  await page.getByTestId('reward-save').click();
  await expect(page.getByTestId('my-reward')).toHaveCount(2);
  await expect(page.getByTestId('wish-option')).toContainText('Spa day');
  await page.getByTestId('wish-make-reward').click();
  await expect(page.getByTestId('reward-title')).toHaveValue('Spa day');
  await page.getByTestId('reward-price').fill('20');
  await page.getByTestId('reward-save').click();
  await expect(page.getByTestId('my-reward')).toHaveCount(3);
  await expect(page.getByTestId('wish-option')).toHaveCount(0);
  // Hide the wish reward again: the companion's shop must not list it.
  await page
    .getByTestId('my-reward')
    .filter({ hasText: 'Spa day' })
    .getByTestId('reward-toggle')
    .click();
  await expect(page.getByTestId('my-reward').filter({ hasText: 'Spa day' })).toHaveAttribute('data-status', 'hidden');

  const contextB = await browser.newContext({ viewport: VIEWPORT });
  const pageB = await contextB.newPage();
  try {
    await injectTelegram(pageB, { ...USERS.B, language_code: 'en' });
    await pageB.goto('/shop');
    await expect(pageB.getByTestId('shop-balance')).toContainText('50');
    await expect(pageB.getByTestId('reward-card')).toHaveCount(2);
    const tripCard = pageB.getByTestId('reward-card').filter({ hasText: 'Weekend trip' });
    await expect(tripCard.getByTestId('reward-buy')).toBeDisabled();
    await expect(tripCard.getByTestId('reward-reason')).toContainText('Not enough gold: 450 more needed.');

    // Buy through the confirm sheet; the balance updates without a reload.
    const movie = pageB.getByTestId('reward-card').filter({ hasText: 'Movie night' });
    await expect(movie.getByTestId('reward-quantity')).toHaveText('Left: 2');
    await movie.getByTestId('reward-buy').click();
    const bought = pageB.waitForResponse((r) => r.url().endsWith('/purchase'));
    await pageB.getByRole('dialog', { name: 'Buy Movie night?' }).getByRole('button', { name: 'Buy' }).click();
    const purchase = await bought;
    expect(purchase.status()).toBe(201);
    expect(await purchase.request().headerValue('idempotency-key')).toBeTruthy();
    const overlay = pageB.getByRole('alertdialog', { name: 'Reward claimed!' });
    await expect(overlay).toContainText('Balance: 10 gold.');
    await overlay.getByRole('button', { name: 'Continue' }).click();
    await expect(pageB.getByTestId('shop-balance')).toContainText('10');
    await expect(movie.getByTestId('reward-quantity')).toHaveText('Left: 1');
    await expect(movie.getByTestId('reward-buy')).toBeDisabled();
    // Let the confetti canvas finish so the screenshot is clean.
    await expect(pageB.locator('canvas')).toHaveCount(0, { timeout: 10_000 });
    await pageB.screenshot({ path: 'docs/screens/S11.png' });

    // B requests it; A schedules and fulfils from the queue.
    await pageB.getByTestId('shop-nav-inventory').click();
    await expect(pageB.getByTestId('voucher-group-purchased')).toContainText('Movie night');
    await pageB.getByTestId('voucher-request').click();
    await expect(pageB.getByTestId('voucher-group-requested')).toContainText('Movie night');

    await page.goto('/shop/manage');
    const queued = page.getByTestId('request-list').getByTestId('voucher-card');
    await expect(queued).toHaveCount(1);
    await queued.getByTestId('voucher-schedule-open').click();
    await page.getByTestId('schedule-when').fill('2999-01-01T20:00');
    await page.getByTestId('schedule-note').fill('Popcorn on me');
    await page.getByTestId('schedule-save').click();
    await expect(queued.getByTestId('voucher-schedule')).toContainText('Popcorn on me');
    await queued.getByTestId('voucher-fulfill').click();
    await expect(page.getByTestId('requests-empty')).toBeVisible();

    // B sees it Fulfilled, disputes it (back to Requested), and A refunds: the Gold returns.
    await pageB.reload();
    await expect(pageB.getByTestId('voucher-group-fulfilled')).toContainText('Movie night');
    await pageB.getByTestId('voucher-dispute').click();
    await pageB.getByRole('dialog', { name: 'Dispute this reward?' }).getByRole('button', { name: 'Dispute' }).click();
    await expect(pageB.getByTestId('voucher-group-requested')).toContainText('Movie night');
    await expect(pageB.getByTestId('voucher-group-fulfilled')).toHaveCount(0);

    await page.reload();
    await page.getByTestId('voucher-refund').click();
    await page.getByRole('dialog', { name: 'Refund this reward?' }).getByRole('button', { name: 'Refund' }).click();
    await expect(page.getByTestId('requests-empty')).toBeVisible();
    await pageB.reload();
    await expect(pageB.getByTestId('voucher-group-refunded')).toContainText('Movie night');
    await expect(pageB.getByTestId('shop-balance')).toContainText('50');
  } finally {
    await contextB.close();
  }
});

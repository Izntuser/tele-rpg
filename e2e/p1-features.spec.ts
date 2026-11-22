import type { APIRequestContext } from '@playwright/test';

import { apiLogin, expect, injectTelegram, onboardViaApi, test } from './fixtures/telegram';

const VIEWPORT = { width: 390, height: 844 };
test.use({ viewport: VIEWPORT });

const PHOTO = 'e2e/fixtures/proof.jpg';

async function post(request: APIRequestContext, jwt: string, path: string, data?: object) {
  const response = await request.post(`/api${path}`, { headers: { Authorization: `Bearer ${jwt}` }, data });
  expect(response.status(), `${path}: ${await response.text()}`).toBeLessThan(300);
  return response;
}

/**
 * The P1 acceptance test (ARCHITECTURE s10): A is the Game Master (English UI), B the player
 * (Telegram language uk). Covers the achievement toast, the notification inbox, photo submit,
 * goals, wishlist -> reward, life balance (mine and the companion's), the journal and the
 * language switch to uk.
 */
test('@P1 @S15 P1 features: toast, inbox, photo, goals, wishlist reward, life balance, journal, uk', async ({
  page,
  browser,
  request,
  telegram,
}) => {
  await onboardViaApi(request, 'A', { name: 'Aria' });
  await onboardViaApi(request, 'B', { name: 'Bold' });
  const jwtA = await apiLogin(request, 'A');
  const jwtB = await apiLogin(request, 'B');
  const { token } = (await (await post(request, jwtA, '/partnership/invitations')).json()) as { token: string };
  await post(request, jwtB, '/partnership/invitations/accept', { token });

  // Achievement toast: A's first quest offer unlocks "Quest giver".
  await telegram('A');
  await page.goto('/');
  await expect(page.getByTestId('character-name')).toHaveText('Aria');
  await page.goto('/quests/new');
  await page.getByTestId('quest-title').fill('Gym session');
  await page.getByTestId('attribute-physical').click();
  await page.getByTestId('difficulty-normal').click();
  await page.getByTestId('quest-create').click();
  await expect(page).toHaveURL(/\/quests\/\d+$/);
  const toast = page.getByTestId('achievement-toast');
  await expect(toast).toBeVisible();
  await expect(toast).toHaveAttribute('data-code', 'quest_giver');
  await expect(toast).toContainText('Achievement unlocked!');
  await expect(toast).toContainText('Quest giver');
  const occurrenceId = Number(/\/quests\/(\d+)$/.exec(page.url())?.[1]);

  // A also offers a photo-required quest (API); B accepts it below.
  const created = await post(request, jwtA, '/quests', {
    title: 'Sketch a tree',
    attribute: 'creativity',
    difficulty: 'easy',
    gold: 20,
    photo_required: true,
  });
  const photoQuest = ((await created.json()) as { occurrence: { id: number } }).occurrence.id;

  const contextB = await browser.newContext({ viewport: VIEWPORT });
  const pageB = await contextB.newPage();
  try {
    await injectTelegram(pageB, 'B');
    // Notification inbox: B has two unread offers.
    await pageB.goto('/');
    const bell = pageB.getByTestId('notification-bell');
    await expect(bell.getByTestId('notification-badge')).toHaveText('2');
    await bell.click();
    await expect(pageB).toHaveURL(/\/notifications$/);
    await expect(pageB.getByTestId('notification-item')).toHaveCount(2);
    await pageB.getByTestId('notification-item').filter({ hasText: 'Gym session' }).click();
    await expect(pageB).toHaveURL(new RegExp(`/quests/${occurrenceId}$`));
    await pageB.getByTestId('quest-accept').click();
    await pageB.getByTestId('quest-submit').click();
    await expect(pageB.getByTestId('quest-waiting')).toBeVisible();

    // Photo submit.
    await post(request, jwtB, `/quests/${photoQuest}/accept`);
    await pageB.goto(`/quests/${photoQuest}`);
    await expect(pageB.getByTestId('quest-submit')).toBeDisabled();
    const uploaded = pageB.waitForResponse((r) => r.url().endsWith('/api/files') && r.request().method() === 'POST');
    await pageB.getByTestId('submit-photo').setInputFiles(PHOTO);
    expect((await uploaded).status()).toBe(201);
    await expect(pageB.getByTestId('submit-photo-preview')).toBeVisible();
    await pageB.getByTestId('quest-submit').click();
    await expect(pageB.getByTestId('quest-waiting')).toBeVisible();

    // Goals and wishlist (B's UI is Ukrainian; test ids keep this language-neutral).
    await pageB.goto('/me/goals');
    await pageB.getByTestId('goal-title-input').fill('Draw every week');
    await pageB.getByTestId('goal-add').click();
    await expect(pageB.getByTestId('goal-list')).toContainText('Draw every week');
    await pageB.goto('/me/wishlist');
    await pageB.getByTestId('wish-title-input').fill('Pottery class');
    await pageB.getByTestId('wish-add').click();
    await expect(pageB.getByTestId('wish-item')).toContainText('Pottery class');

    // A confirms both quests in the UI.
    for (const id of [occurrenceId, photoQuest]) {
      await page.goto(`/quests/${id}`);
      await page.getByTestId('quest-confirm').click();
      await page.getByRole('alertdialog', { name: 'Quest complete!' }).getByRole('button', { name: 'Continue' }).click();
    }

    // Wishlist -> reward: A turns B's wish into a shop reward; B sees it in the shop.
    await page.goto('/shop/manage');
    await page.getByTestId('wish-option').filter({ hasText: 'Pottery class' }).getByTestId('wish-make-reward').click();
    await expect(page.getByTestId('reward-title')).toHaveValue('Pottery class');
    await page.getByTestId('reward-price').fill('60');
    await page.getByTestId('reward-save').click();
    await expect(page.getByTestId('my-reward')).toContainText('Pottery class');
    await pageB.goto('/shop');
    await expect(pageB.getByTestId('reward-card').filter({ hasText: 'Pottery class' })).toBeVisible();

    // Life balance, companion view: A sees B's radar, goal and an encouraging suggestion.
    await page.goto('/companion');
    const companionBalance = page.getByTestId('companion-life-balance');
    await expect(companionBalance.getByTestId('life-balance-radar')).toBeVisible();
    await expect(companionBalance.getByTestId('balance-score-physical')).toHaveAttribute('data-score', '50');
    await expect(companionBalance.getByTestId('balance-score-creativity')).toHaveAttribute('data-score', '20');
    await expect(companionBalance.getByTestId('life-balance-suggestion').first()).toContainText('Your companion');
    await expect(page.getByTestId('companion-goals')).toContainText('Draw every week');

    // Life balance, my own: B's Stats page shows the scores and the first achievements.
    await pageB.goto('/stats');
    await expect(pageB.getByTestId('life-balance-radar')).toBeVisible();
    await expect(pageB.getByTestId('balance-score-physical')).toHaveAttribute('data-score', '50');
    await expect(pageB.getByTestId('stat-quests')).toContainText('2');
    await expect(pageB.locator('[data-testid="achievement"][data-code="first_quest"]')).toHaveAttribute('data-unlocked', 'true');

    // Journal: B's journal has the completions and the unlock; the shared scope has A's offers.
    await pageB.getByTestId('stats-journal-link').click();
    await expect(pageB).toHaveURL(/\/stats\/journal$/);
    await expect(pageB.locator('[data-testid="journal-event"][data-type="quest_completed"]')).toHaveCount(2);
    await expect(pageB.locator('[data-testid="journal-event"][data-type="achievement_unlocked"]').first()).toBeVisible();
    await pageB.getByTestId('journal-scope-shared').click();
    await expect(
      pageB.locator('[data-testid="journal-event"][data-type="quest_offered"][data-actor="companion"]'),
    ).toHaveCount(2);
  } finally {
    await contextB.close();
  }

  // Language switch: A switches to Ukrainian and Stats re-renders in it.
  await page.goto('/settings');
  await page.getByLabel('App language').selectOption('uk');
  await expect(page.getByRole('heading', { name: 'Налаштування', level: 1 })).toBeVisible();
  await page.getByTestId('nav-stats').click();
  await expect(page.getByRole('heading', { name: 'Статистика', level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Баланс життя' })).toBeVisible();
  await page.goto('/stats/journal');
  await expect(page.getByRole('heading', { name: 'Журнал пригод', level: 1 })).toBeVisible();
});

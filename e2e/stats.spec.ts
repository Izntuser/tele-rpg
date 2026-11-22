import type { APIRequestContext } from '@playwright/test';

import { apiLogin, expect, onboardViaApi, test } from './fixtures/telegram';

test.use({ viewport: { width: 390, height: 844 } });

async function post(request: APIRequestContext, jwt: string, path: string, data?: object) {
  const response = await request.post(`/api${path}`, { headers: { Authorization: `Bearer ${jwt}` }, data });
  expect(response.status(), `${path}: ${await response.text()}`).toBeLessThan(300);
  return response;
}

/** B (Game Master) gives A (player) three quests; A completes them all. */
async function seed(request: APIRequestContext) {
  await onboardViaApi(request, 'A', { name: 'Aria' });
  await onboardViaApi(request, 'B', { name: 'Bold' });
  const jwtA = await apiLogin(request, 'A');
  const jwtB = await apiLogin(request, 'B');
  const { token } = (await (await post(request, jwtB, '/partnership/invitations')).json()) as { token: string };
  await post(request, jwtA, '/partnership/invitations/accept', { token });
  const quests = [
    { title: 'Morning run', attribute: 'physical', difficulty: 'hard', gold: 60 },
    { title: 'Read a chapter', attribute: 'intellectual', difficulty: 'normal', gold: 30 },
    { title: 'Call a friend', attribute: 'social', difficulty: 'easy', gold: 20 },
  ];
  for (const quest of quests) {
    const created = (await (await post(request, jwtB, '/quests', quest)).json()) as { occurrence: { id: number } };
    const id = created.occurrence.id;
    await post(request, jwtA, `/quests/${id}/accept`);
    await post(request, jwtA, `/quests/${id}/submit`);
    await post(request, jwtB, `/quests/${id}/confirm`);
  }
}

test('@S15 Stats shows the summary, charts, life balance with targets and achievements', async ({
  page,
  request,
  telegram,
}) => {
  await seed(request);
  await telegram('A');
  await page.goto('/stats');

  await expect(page.getByRole('heading', { name: 'Stats', level: 1 })).toBeVisible();
  await expect(page.getByTestId('stat-quests')).toContainText('3');
  await expect(page.getByTestId('stat-xp')).toContainText('170');
  await expect(page.getByTestId('stat-gold-earned')).toContainText('110');
  await expect(page.getByTestId('chart-xp')).toHaveAttribute('data-total', '170');
  await expect(page.getByTestId('chart-quests')).toHaveAttribute('data-total', '3');

  const radar = page.getByTestId('life-balance-radar');
  await expect(radar).toBeVisible();
  await expect(page.getByTestId('balance-score-physical')).toHaveAttribute('data-score', '100');
  await expect(page.getByTestId('balance-score-intellectual')).toHaveAttribute('data-score', '50');
  await expect(page.getByTestId('balance-score-social')).toHaveAttribute('data-score', '20');
  const tips = page.getByTestId('life-balance-suggestion');
  await expect(tips).toHaveCount(3);
  await expect(tips.first()).toHaveAttribute('data-attribute', 'discipline');

  await expect(page.locator('[data-testid="achievement"][data-code="first_quest"]')).toHaveAttribute(
    'data-unlocked',
    'true',
  );
  await expect(page.locator('[data-testid="achievement"][data-code="gold_100"]')).toHaveAttribute(
    'data-unlocked',
    'true',
  );
  await page.screenshot({ path: 'docs/screens/S15.png', fullPage: true });

  // Targets: lowering Social to 20 XP a week makes it 100%.
  await page.getByTestId('targets-edit').click();
  await page.getByTestId('target-social').fill('20');
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/stats/life-balance/targets') && r.request().method() === 'PUT');
  await page.getByTestId('targets-save').click();
  expect((await saved).status()).toBe(200);
  await expect(page.getByTestId('balance-score-social')).toHaveAttribute('data-score', '100');

  // 30 days: the targets scale up (100/week -> 429), so Physical drops below 100.
  await page.getByTestId('life-balance-period-30d').click();
  await expect(page.getByTestId('balance-score-physical')).toHaveAttribute('data-score', '23');

  // The period switch for the summary.
  await page.getByTestId('stats-period-all').click();
  await expect(page.getByTestId('stats-period-all')).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('stat-quests-total')).toContainText('3');
});

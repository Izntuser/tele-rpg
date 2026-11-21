import type { APIRequestContext } from '@playwright/test';

import { apiLogin, expect, onboardViaApi, test } from './fixtures/telegram';

test.use({ viewport: { width: 390, height: 844 } });

async function post(request: APIRequestContext, jwt: string, path: string, data?: object) {
  const response = await request.post(`/api${path}`, { headers: { Authorization: `Bearer ${jwt}` }, data });
  expect(response.status(), `${path}: ${await response.text()}`).toBeLessThan(300);
  return response;
}

test('@S13 A pauses and resumes a daily quest in the Recurring tab, which shows the streak', async ({
  page,
  request,
  telegram,
}) => {
  await onboardViaApi(request, 'A', { name: 'Aria' });
  await onboardViaApi(request, 'B', { name: 'Bold' });
  const jwtA = await apiLogin(request, 'A');
  const invite = await post(request, jwtA, '/partnership/invitations');
  const { token } = (await invite.json()) as { token: string };
  const jwtB = await apiLogin(request, 'B');
  await post(request, jwtB, '/partnership/invitations/accept', { token });

  // A offers a daily quest, B accepts, submits, A confirms: a streak of one day.
  const created = await post(request, jwtA, '/quests', {
    title: 'Morning run',
    attribute: 'physical',
    difficulty: 'normal',
    gold: 20,
    recurrence: 'daily',
  });
  const { template } = (await created.json()) as { template: { id: number } };
  await post(request, jwtB, `/quest-templates/${template.id}/accept`);
  const occurrences = await request.get('/api/quests', { headers: { Authorization: `Bearer ${jwtB}` } });
  const [occurrence] = (await occurrences.json()) as { id: number }[];
  await post(request, jwtB, `/quests/${occurrence!.id}/submit`);
  await post(request, jwtA, `/quests/${occurrence!.id}/confirm`);

  await telegram('A');
  await page.goto('/quests');
  await page.getByTestId('quest-tab-recurring').click();
  const item = page.getByTestId('recurring-item').filter({ hasText: 'Morning run' });
  await expect(item).toBeVisible();
  await expect(item.getByTestId('recurring-streak')).toContainText('1 day streak');

  const paused = page.waitForResponse((r) => r.url().endsWith(`/quest-templates/${template.id}/pause`));
  await item.getByTestId('recurring-pause').click();
  expect((await paused).status()).toBe(200);
  await expect(item).toHaveAttribute('data-status', 'paused');
  await expect(item.getByTestId('recurring-resume')).toBeVisible();
  await expect(item.getByTestId('recurring-streak')).toContainText('1 day streak');
  await page.screenshot({ path: 'docs/screens/S13.png' });

  const resumed = page.waitForResponse((r) => r.url().endsWith(`/quest-templates/${template.id}/resume`));
  await item.getByTestId('recurring-resume').click();
  expect((await resumed).status()).toBe(200);
  await expect(item).toHaveAttribute('data-status', 'active');
  await expect(item.getByTestId('recurring-pause')).toBeVisible();

  const detail = await request.get(`/api/quest-templates/${template.id}`, {
    headers: { Authorization: `Bearer ${jwtA}` },
  });
  expect(((await detail.json()) as { status: string }).status).toBe('active');
});

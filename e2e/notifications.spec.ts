import type { APIRequestContext } from '@playwright/test';

import { apiLogin, expect, onboardViaApi, test } from './fixtures/telegram';

test.use({ viewport: { width: 390, height: 844 } });

async function post(request: APIRequestContext, jwt: string, path: string, data?: object) {
  const response = await request.post(`/api${path}`, { headers: { Authorization: `Bearer ${jwt}` }, data });
  expect(response.status(), `${path}: ${await response.text()}`).toBeLessThan(300);
  return response;
}

test('@S14 B sees A\'s quest offer in the inbox, taps it and lands on the quest', async ({
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

  // A offers a quest.
  const created = await post(request, jwtA, '/quests', {
    title: 'Evening walk',
    attribute: 'physical',
    difficulty: 'normal',
    gold: 30,
  });
  const { occurrence } = (await created.json()) as { occurrence: { id: number } };

  // B opens the app: the header bell shows the unread offer.
  await telegram('B');
  await page.goto('/');
  const bell = page.getByTestId('notification-bell');
  await expect(bell.getByTestId('notification-badge')).toHaveText('1');
  await bell.click();
  await expect(page).toHaveURL(/\/notifications$/);

  const item = page.getByTestId('notification-item').filter({ hasText: 'Evening walk' });
  await expect(item).toBeVisible();
  await expect(item).toHaveAttribute('data-type', 'quest_offered');
  await expect(item).toHaveAttribute('data-unread', 'true');
  await page.screenshot({ path: 'docs/screens/S14.png' });

  const read = page.waitForResponse((r) => r.url().includes('/read') && r.request().method() === 'POST');
  await item.click();
  expect((await read).status()).toBe(200);
  await expect(page).toHaveURL(new RegExp(`/quests/${occurrence.id}$`));
  await expect(page.getByTestId('page-quest-detail')).toContainText('Evening walk');

  // The badge is gone once the offer is read.
  await expect(page.getByTestId('notification-bell').getByTestId('notification-badge')).toHaveCount(0);
});

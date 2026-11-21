import { USERS, expect, test } from './fixtures/telegram';

test.use({ viewport: { width: 390, height: 844 } });

test('@S01 placeholder home renders', async ({ page, telegram }) => {
  // Since S03 the home sits behind Telegram auth, so sign in as user A to reach it.
  await telegram('A');
  await page.goto('/');
  // "Placeholder home" exists only on the home screen, not on the auth status screens.
  await expect(page.getByText('Placeholder home')).toBeVisible();
  await expect(page.getByTestId('user-greeting')).toContainText(USERS.A.first_name);
  await expect(page.getByRole('heading', { name: 'Modern Life RPG' })).toBeVisible();
  await page.screenshot({ path: 'docs/screens/S01.png' });
});

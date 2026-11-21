import { USERS, expect, onboardViaApi, test } from './fixtures/telegram';

test.use({ viewport: { width: 390, height: 844 } });

test('@S01 home renders', async ({ page, telegram, request }) => {
  // Since S03 the home sits behind Telegram auth, and since S05 behind onboarding: create user
  // A's character through the API, then sign in as A to reach Home.
  await onboardViaApi(request, 'A');
  await telegram('A');
  await page.goto('/');
  // The character header exists only on the home screen (not on auth or onboarding screens).
  const home = page.getByTestId('page-home');
  await expect(home.getByTestId('character-header')).toBeVisible();
  await expect(home.getByTestId('character-name')).toHaveText(USERS.A.first_name);
  await expect(page.getByTestId('user-greeting')).toContainText(USERS.A.first_name);
  await expect(page.getByRole('heading', { name: 'Modern Life RPG' })).toBeVisible();
  await page.screenshot({ path: 'docs/screens/S01.png' });
});

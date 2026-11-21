import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 390, height: 844 } });

test('@S01 placeholder home renders', async ({ page }) => {
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'Modern Life RPG' }),
  ).toBeVisible();
  await page.screenshot({ path: 'docs/screens/S01.png' });
});

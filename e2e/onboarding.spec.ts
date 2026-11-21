import { USERS, apiLogin, expect, test } from './fixtures/telegram';

test.use({ viewport: { width: 390, height: 844 }, timezoneId: 'Asia/Tokyo' });

test('@S05 user A onboards, adds a goal and a wish, and Home shows the character', async ({
  page,
  telegram,
  request,
}) => {
  await telegram('A');
  await page.goto('/');

  // A new user is redirected to onboarding. Step 1: the character, name prefilled from Telegram.
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByTestId('onboarding-step-character')).toBeVisible();
  const name = page.getByLabel('Character name');
  await expect(name).toHaveValue(`${USERS.A.first_name} ${USERS.A.last_name}`);
  await name.fill('');
  await page.getByTestId('onboarding-next').click();
  await expect(page.getByRole('alert')).toContainText('Enter a name');
  await name.fill('Aria');
  await page.getByLabel('Nickname (optional)').fill('The Brave');
  await page.getByTestId('onboarding-next').click();

  // Step 2: pick a preset and type a custom goal.
  await expect(page.getByTestId('onboarding-step-goals')).toBeVisible();
  await page.getByTestId('goal-preset-read').click();
  await expect(page.getByTestId('goal-preset-read')).toHaveAttribute('aria-pressed', 'true');
  await page.getByLabel('Your own goal').fill('Learn to juggle');
  await page.getByTestId('onboarding-add-goal').click();
  await page.getByTestId('onboarding-next').click();

  // Step 3: the timezone comes from the browser and can be changed.
  const timezone = page.getByLabel('Timezone');
  await expect(timezone).toHaveValue('Asia/Tokyo');
  await timezone.selectOption('Europe/Berlin');
  const done = page.waitForResponse((r) => r.url().endsWith('/api/character/onboarding/complete'));
  await page.getByTestId('onboarding-finish').click();
  expect((await done).status()).toBe(200);

  // Home: avatar, name, level, XP bar and gold.
  await expect(page).toHaveURL(/\/$/);
  const header = page.getByTestId('character-header');
  await expect(header.getByTestId('character-name')).toHaveText('Aria');
  await expect(header.getByTestId('character-nickname')).toHaveText('The Brave');
  await expect(header.getByRole('img', { name: 'Aria' })).toBeVisible();
  await expect(header.getByText('Level 1')).toBeVisible();
  await expect(header.getByRole('progressbar')).toHaveAttribute('aria-valuemax', '100');
  await expect(header.getByLabel('0 gold')).toBeVisible();
  await expect(page.getByTestId('attribute-grid').getByRole('listitem')).toHaveCount(6);

  // Goals: the onboarding goals are there; add one more.
  await page.getByTestId('home-goals-link').click();
  await expect(page.getByTestId('page-goals')).toBeVisible();
  await expect(page.getByTestId('goal-item')).toHaveCount(2);
  await page.getByLabel('New goal').fill('Run 5k');
  await page.getByRole('button', { name: 'Physical' }).click();
  await page.getByTestId('goal-add').click();
  await expect(page.getByTestId('goal-item')).toHaveCount(3);
  await expect(page.getByTestId('goal-list')).toContainText('Run 5k');

  // Back to Home with Telegram's BackButton, then the wishlist.
  await page.evaluate(() => (window as unknown as { __telegramClick: (n: string) => void }).__telegramClick('BackButton'));
  await expect(page.getByTestId('page-home')).toBeVisible();
  await page.getByTestId('home-wishlist-link').click();
  await expect(page.getByTestId('page-wishlist')).toBeVisible();
  await page.getByLabel('New wish').fill('Breakfast in bed');
  await page.getByTestId('wish-add').click();
  await expect(page.getByTestId('wish-item')).toHaveCount(1);
  await expect(page.getByTestId('wish-item')).toContainText('Breakfast in bed');

  // The server agrees.
  const jwt = await apiLogin(request, 'A');
  const headers = { Authorization: `Bearer ${jwt}` };
  const character = (await (await request.get('/api/character', { headers })).json()) as {
    name: string;
    level: number;
    gold: number;
    timezone: string;
    attributes: unknown[];
  };
  expect(character).toMatchObject({ name: 'Aria', level: 1, gold: 0, timezone: 'Europe/Berlin' });
  expect(character.attributes).toHaveLength(6);
  const goals = (await (await request.get('/api/goals', { headers })).json()) as { title: string }[];
  expect(goals.map((g) => g.title)).toEqual(['Read more books', 'Learn to juggle', 'Run 5k']);
  const wishes = (await (await request.get('/api/wishlist', { headers })).json()) as { title: string }[];
  expect(wishes.map((w) => w.title)).toEqual(['Breakfast in bed']);

  await page.getByTestId('nav-home').click();
  await expect(page.getByTestId('character-header')).toBeVisible();
  await page.screenshot({ path: 'docs/screens/S05.png' });
});

test('@S05 an onboarded user is not sent back to onboarding', async ({ page, telegram }) => {
  await telegram('A');
  await page.goto('/');
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByTestId('onboarding-next').click();
  await page.getByTestId('onboarding-next').click();
  await page.getByTestId('onboarding-finish').click();
  await expect(page.getByTestId('character-header')).toBeVisible();

  await page.goto('/onboarding');
  await expect(page.getByTestId('page-home')).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
});

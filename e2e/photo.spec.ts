import type { APIRequestContext } from '@playwright/test';

import { apiLogin, expect, injectTelegram, onboardViaApi, test } from './fixtures/telegram';

const VIEWPORT = { width: 390, height: 844 };
test.use({ viewport: VIEWPORT });

/** A JPEG with GPS coordinates and a camera make in its EXIF (both must be stripped). */
const FIXTURE = 'e2e/fixtures/proof.jpg';

async function post(request: APIRequestContext, jwt: string, path: string, data?: object) {
  const response = await request.post(`/api${path}`, { headers: { Authorization: `Bearer ${jwt}` }, data });
  expect(response.status(), `${path}: ${await response.text()}`).toBeLessThan(300);
  return response;
}

test('@S12 B submits a photo-required quest with a photo and A sees it on the quest detail', async ({
  page,
  browser,
  request,
  telegram,
}) => {
  await onboardViaApi(request, 'A', { name: 'Aria' });
  await onboardViaApi(request, 'B', { name: 'Bold' });
  const jwtA = await apiLogin(request, 'A');
  const jwtB = await apiLogin(request, 'B');
  const invite = await post(request, jwtA, '/partnership/invitations');
  const { token } = (await invite.json()) as { token: string };
  await post(request, jwtB, '/partnership/invitations/accept', { token });

  const created = await post(request, jwtA, '/quests', {
    title: 'Gym session',
    attribute: 'physical',
    difficulty: 'normal',
    gold: 30,
    photo_required: true,
  });
  const { occurrence } = (await created.json()) as { occurrence: { id: number } };
  await post(request, jwtB, `/quests/${occurrence.id}/accept`);

  // B: the quest cannot be submitted without a photo; B attaches the fixture and submits.
  const contextB = await browser.newContext({ viewport: VIEWPORT });
  const pageB = await contextB.newPage();
  let photoId = 0;
  try {
    await injectTelegram(pageB, 'B');
    await pageB.goto(`/quests/${occurrence.id}`);
    await expect(pageB.getByTestId('quest-submit')).toBeDisabled();
    await expect(pageB.getByTestId('submit-photo-required')).toBeVisible();

    const uploaded = pageB.waitForResponse((r) => r.url().endsWith('/api/files') && r.request().method() === 'POST');
    await pageB.getByTestId('submit-photo').setInputFiles(FIXTURE);
    const upload = await uploaded;
    expect(upload.status(), await upload.text()).toBe(201);
    photoId = ((await upload.json()) as { id: number }).id;
    await expect(pageB.getByTestId('submit-photo-preview')).toBeVisible();

    await pageB.getByTestId('submit-comment').fill('Leg day done');
    const submitted = pageB.waitForResponse((r) => r.url().endsWith(`/quests/${occurrence.id}/submit`));
    await pageB.getByTestId('quest-submit').click();
    expect((await submitted).status()).toBe(200);
    await expect(pageB.getByTestId('quest-waiting')).toBeVisible();
  } finally {
    await contextB.close();
  }

  // A (the GM) sees B's photo on the quest detail, served through the authorized endpoint.
  await telegram('A');
  await page.goto(`/quests/${occurrence.id}`);
  const image = page.getByTestId('submission-photo');
  await expect(image).toBeVisible();
  await expect(image).toHaveAttribute('data-file-id', String(photoId));
  await expect
    .poll(() => image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0))
    .toBe(true);
  await expect(page.getByTestId('quest-confirm')).toBeVisible();
  await page.screenshot({ path: 'docs/screens/S12.png' });

  // The stored bytes carry no EXIF (camera make / GPS) and need the bearer token.
  const asA = await request.get(`/api/files/${photoId}`, { headers: { Authorization: `Bearer ${jwtA}` } });
  expect(asA.status()).toBe(200);
  const bytes = await asA.body();
  expect(bytes.includes('E2ECam')).toBe(false);
  expect(bytes.includes('Exif')).toBe(false);
  expect((await request.get(`/api/files/${photoId}`)).status()).toBe(401);
});

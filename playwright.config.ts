// Used only if the project has a web UI (site, admin panel, Telegram Mini App).
// S01 installs @playwright/test and adds "e2e": "playwright test" to package.json.
// Convention: tag @<id> in the test title, screenshot to docs/screens/<id>.png.
// init.sh starts the dev server, so no webServer block here.
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:3000',
    headless: true,
    trace: 'retain-on-failure',
  },
});

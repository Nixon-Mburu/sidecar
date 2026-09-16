import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/ui',
  use: { baseURL: 'http://127.0.0.1:5173', browserName: 'chromium', launchOptions: { executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox'] } },
  webServer: { command: 'npm run dev -- --port 5173', url: 'http://127.0.0.1:5173', reuseExistingServer: true },
});

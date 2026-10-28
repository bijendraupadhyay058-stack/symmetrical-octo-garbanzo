import { defineConfig, devices } from '@playwright/test'

const PORT = Number(process.env.E2E_PORT ?? 3100)

export default defineConfig({
  testDir: 'e2e',
  timeout: 60_000,
  retries: 0,
  use: { baseURL: `http://localhost:${PORT}`, trace: 'retain-on-failure' },
  projects: [
    { name: 'android-chrome', use: { ...devices['Pixel 7'], locale: 'en-IN', timezoneId: 'Asia/Kolkata' } },
    { name: 'desktop-chrome', use: { ...devices['Desktop Chrome'], locale: 'en-IN', timezoneId: 'Asia/Kolkata' } },
  ],
  webServer: {
    // Runs without Supabase variables, i.e. in on-device mode.
    command: `npx next start -p ${PORT}`,
    port: PORT,
    reuseExistingServer: true,
    timeout: 60_000,
  },
})

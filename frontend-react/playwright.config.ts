import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

const acceptancePython = fileURLToPath(
  new URL('../.venv_acceptance/Scripts/python.exe', import.meta.url)
);
const python = process.env.E2E_PYTHON || (existsSync(acceptancePython) ? `"${acceptancePython}"` : 'python');

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4175',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `${python} -m uvicorn tests.e2e_backend:app --host 127.0.0.1 --port 8010`,
      cwd: '..',
      url: 'http://127.0.0.1:8010/api/v1/health',
      reuseExistingServer: false,
    },
    {
      command: 'npx vite --host 127.0.0.1 --port 4175',
      env: { VITE_API_PROXY_TARGET: 'http://127.0.0.1:8010' },
      url: 'http://127.0.0.1:4175',
      reuseExistingServer: false,
    },
  ],
});

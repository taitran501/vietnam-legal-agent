import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

const acceptancePython = fileURLToPath(
  new URL('../.venv_acceptance/Scripts/python.exe', import.meta.url)
);
const frontendRoot = fileURLToPath(new URL('.', import.meta.url));
const python = process.env.E2E_PYTHON || (existsSync(acceptancePython) ? `"${acceptancePython}"` : 'python');
const reuseLocalServer = process.env.CI !== 'true';

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
      reuseExistingServer: reuseLocalServer,
    },
    {
      // Do not invoke `npx` here: on Windows it can walk out of the frontend
      // workspace while resolving Vite.  The project-local binary and an
      // absolute workspace root make the browser acceptance host repeatable.
      command: 'node ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4175',
      cwd: frontendRoot,
      env: { VITE_API_PROXY_TARGET: 'http://127.0.0.1:8010' },
      url: 'http://127.0.0.1:4175',
      reuseExistingServer: reuseLocalServer,
    },
  ],
});

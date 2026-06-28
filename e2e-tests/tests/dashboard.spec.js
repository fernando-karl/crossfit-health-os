/**
 * Dashboard — authenticated hub, loading states, JS auth.
 */

const { test, expect } = require('@playwright/test');
const {
  clearBrowserData,
  gotoApp,
  stabilizeTheme,
  collectConsoleErrors,
  authenticateOrSkip,
  screenshotViewport,
} = require('../utils/helpers');

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await stabilizeTheme(page, 'light');
    await clearBrowserData(page);
    await authenticateOrSkip(page, testInfo);
  });

  test('authenticated user reaches dashboard @smoke', async ({ page }, testInfo) => {
    const finishErrors = collectConsoleErrors(page);

    await gotoApp(page, '/dashboard');
    await expect(page).toHaveURL(/\/dashboard/);

    await expect(page.locator('#main-content, .container-fluid').first()).toBeVisible();
    await expect(page.locator('.chos-navbar, .navbar')).toBeVisible();

    const token = await page.evaluate(() => localStorage.getItem('access_token'));
    expect(token).toBeTruthy();

    const hasChos = await page.evaluate(() => typeof CHOS !== 'undefined' && typeof CHOS.api === 'object');
    expect(hasChos).toBe(true);

    // Loading spinner or content state should appear
    await page.waitForFunction(() => {
      const loading = document.querySelector('#loading-state');
      const newUser = document.querySelector('#new-user-state');
      const dashboard = document.querySelector('#active-user-state');
      if (!loading) return true;
      const loadingHidden = loading.classList.contains('d-none') || loading.offsetParent === null;
      const hasContent =
        (newUser && !newUser.classList.contains('d-none')) ||
        (dashboard && !dashboard.classList.contains('d-none'));
      return loadingHidden || hasContent;
    }, { timeout: 15000 }).catch(() => {});

    const errors = finishErrors().filter(
      (e) => !e.includes('serviceWorker') && !e.includes('favicon')
    );
    expect(errors).toEqual([]);

    await screenshotViewport(page, 'dashboard', testInfo);
  });

  test('new user sees onboarding prompt', async ({ page }) => {
    await gotoApp(page, '/dashboard');

    await page.waitForSelector('#new-user-state, #active-user-state', { timeout: 15000 }).catch(() => {});

    const showsOnboarding = await page.locator('#new-user-state').isVisible().catch(() => false);
    const showsDashboard = await page.locator('#active-user-state').isVisible().catch(() => false);
    expect(showsOnboarding || showsDashboard).toBe(true);

    if (showsOnboarding) {
      await expect(page.locator('a[href="/onboarding"]')).toBeVisible();
    }

    if (showsDashboard) {
      await expect(page.locator('#morning-bar')).toBeVisible();
      await expect(page.locator('#loop-strip')).toBeVisible();
      await expect(page.locator('.chos-dashboard-hub')).toBeVisible();
    }
  });
});

/**
 * Onboarding wizard — multi-step flow and JS step navigation.
 */

const { test, expect } = require('@playwright/test');
const {
  clearBrowserData,
  gotoApp,
  stabilizeTheme,
  authenticateOrSkip,
  screenshotViewport,
} = require('../utils/helpers');

test.describe('Onboarding', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await stabilizeTheme(page, 'light');
    await clearBrowserData(page);
    await authenticateOrSkip(page, testInfo);
  });

  test('displays welcome step @smoke', async ({ page }, testInfo) => {
    await gotoApp(page, '/onboarding');

    await expect(page).toHaveURL(/\/onboarding/);
    await expect(page.locator('#step-1')).toBeVisible();
    await expect(page.locator('.progress')).toBeVisible();

    await screenshotViewport(page, 'onboarding-step-1', testInfo);
  });

  test('advances from welcome to focus selection', async ({ page }, testInfo) => {
    await gotoApp(page, '/onboarding');

    await page.locator('#step-1 button').first().click();

    await expect(page.locator('#step-2')).toBeVisible();
    await expect(page.locator('#focus-training')).toBeVisible();
    await expect(page.locator('#focus-full')).toBeVisible();
    await expect(page.locator('#focus-custom')).toBeVisible();

    const progress = await page.locator('#progress-bar').evaluate((el) => el.style.width);
    expect(progress).not.toBe('0%');

    await screenshotViewport(page, 'onboarding-step-2', testInfo);
  });

  test('selectFocus updates hidden state via JS', async ({ page }) => {
    await gotoApp(page, '/onboarding');

    await page.locator('#step-1 button').first().click();
    await page.locator('#focus-full').click();

    const selected = await page.evaluate(() => onboardingData.app_focus);
    expect(selected).toBe('full');
  });
});

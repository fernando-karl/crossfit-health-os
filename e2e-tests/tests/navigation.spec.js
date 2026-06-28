/**
 * Navigation — desktop navbar vs mobile bottom tabs.
 */

const { test, expect } = require('@playwright/test');
const {
  clearBrowserData,
  gotoApp,
  stabilizeTheme,
  authenticateOrSkip,
  isMobileProject,
  screenshotViewport,
  openNavbarIfCollapsed,
} = require('../utils/helpers');

test.describe('Navigation', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await stabilizeTheme(page, 'light');
    await clearBrowserData(page);
    await authenticateOrSkip(page, testInfo);
  });

  test('primary navigation is reachable @smoke', async ({ page }, testInfo) => {
    await gotoApp(page, '/dashboard');

    if (isMobileProject(testInfo)) {
      const tabs = page.locator('.chos-bottom-tabs');
      await expect(tabs).toBeVisible();
      await expect(tabs.locator('a[href="/dashboard"]')).toBeVisible();
      await expect(tabs.locator('a[href="/dashboard/workouts"]')).toBeVisible();
      await expect(tabs.locator('a[href="/dashboard/nutrition"]')).toBeVisible();
      await expect(tabs.locator('a[href="/dashboard/health"]')).toBeVisible();
      await screenshotViewport(page, 'nav-mobile-tabs', testInfo);
    } else {
      const nav = page.locator('.chos-navbar');
      await expect(nav).toBeVisible();
      await expect(nav.locator('.nav-link[href="/dashboard"]')).toBeVisible();
      await expect(nav.locator('#trainDropdown')).toBeVisible();
      await nav.locator('#trainDropdown').click();
      await expect(nav.locator('a[href="/dashboard/workouts"]')).toBeVisible();
      await expect(nav.locator('a[href="/dashboard/schedule"]')).toBeVisible();
      await expect(nav.locator('a[href="/dashboard/nutrition"]')).toBeVisible();
      await screenshotViewport(page, 'nav-desktop', testInfo);
    }
  });

  test('bottom tabs navigate on mobile', async ({ page }, testInfo) => {
    test.skip(!isMobileProject(testInfo), 'Mobile project only');

    await gotoApp(page, '/dashboard');
    await page.locator('.chos-bottom-tabs a[href="/dashboard/workouts"]').click();
    await expect(page).toHaveURL(/\/dashboard\/workouts/);

    await gotoApp(page, '/dashboard');
    await page.locator('.chos-bottom-tabs a[href="/dashboard/nutrition"]').click();
    await expect(page).toHaveURL(/\/dashboard\/nutrition/);

    await page.locator('.chos-bottom-tabs a[href="/dashboard/health"]').click();
    await expect(page).toHaveURL(/\/dashboard\/health/);
  });

  test('navbar navigates to workouts', async ({ page }, testInfo) => {
    await gotoApp(page, '/dashboard');

    if (isMobileProject(testInfo)) {
      await openNavbarIfCollapsed(page);
      await page.locator('#trainDropdown').click();
      await page.locator('#navbarNav a[href="/dashboard/workouts"]').click();
    } else {
      await page.locator('#trainDropdown').click();
      await page.locator('.chos-navbar a[href="/dashboard/workouts"]').click();
    }

    await expect(page).toHaveURL(/\/dashboard\/workouts/);
    await expect(page.locator('#generate-workout-btn, #workouts-container').first()).toBeVisible();
  });
});

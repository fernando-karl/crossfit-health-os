/**
 * Public pages — landing, auth forms, legal pages.
 * Desktop + mobile layout, JS globals, screenshots.
 */

const { test, expect } = require('@playwright/test');
const {
  clearBrowserData,
  gotoApp,
  stabilizeTheme,
  collectConsoleErrors,
  screenshotViewport,
} = require('../utils/helpers');

test.describe('Public pages', () => {
  test.beforeEach(async ({ page }) => {
    await stabilizeTheme(page, 'light');
    await clearBrowserData(page);
  });

  test('landing page loads with hero and CTAs @smoke', async ({ page }, testInfo) => {
    const finishErrors = collectConsoleErrors(page);
    await gotoApp(page, '/');

    await expect(page.locator('.lp-hero__title')).toBeVisible();
    await expect(page.locator('a[href="/register"]').first()).toBeVisible();
    await expect(page.locator('a[href="/login"]').first()).toBeVisible();

    const errors = finishErrors().filter((e) => !e.includes('serviceWorker'));
    expect(errors).toEqual([]);

    await screenshotViewport(page, 'landing', testInfo);
  });

  test('login page structure and FormValidator @smoke', async ({ page }, testInfo) => {
    await gotoApp(page, '/login');

    await expect(page.locator('h1.lp-auth__title')).toContainText('Sign In');
    await expect(page.locator('#email')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.locator('#login-btn')).toBeVisible();
    await expect(page.locator('a[href="/forgot-password"]')).toBeVisible();

    const hasChos = await page.evaluate(() => typeof window.CHOS !== 'undefined');
    expect(hasChos).toBe(true);

    const validation = await page.evaluate(() => {
      const $form = $('#login-form');
      return FormValidator.validateForm($form);
    });
    expect(validation.valid).toBe(false);

    await screenshotViewport(page, 'login', testInfo);
  });

  test('register page structure @smoke', async ({ page }, testInfo) => {
    await gotoApp(page, '/register');

    await expect(page.locator('h1, h2').first()).toContainText('Create Your Account');
    await expect(page.locator('#name')).toBeVisible();
    await expect(page.locator('#email')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.locator('#accepted_terms')).toBeVisible();
    await expect(page.locator('#register-btn')).toBeVisible();

    await screenshotViewport(page, 'register', testInfo);
  });

  test('forgot password page loads', async ({ page }) => {
    await gotoApp(page, '/forgot-password');
    await expect(page.locator('#form-view .lp-auth__title')).toContainText('Reset Password');
    await expect(page.locator('#email')).toBeVisible();
    await expect(page.locator('#reset-btn')).toBeVisible();
  });

  test('terms and privacy pages load', async ({ page }) => {
    await gotoApp(page, '/terms');
    await expect(page.locator('body')).toContainText(/terms|termos/i);

    await gotoApp(page, '/privacy');
    await expect(page.locator('body')).toContainText(/privacy|privacidade/i);
  });

  test('help page loads', async ({ page }) => {
    await gotoApp(page, '/help');
    await expect(page.locator('body')).toBeVisible();
    await expect(page).toHaveURL(/\/help/);
  });

  test('protected routes redirect to login', async ({ page }) => {
    await gotoApp(page, '/dashboard');
    await expect(page).toHaveURL(/\/login/);
  });
});

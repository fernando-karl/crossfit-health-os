/**
 * Authenticated feature pages — training, nutrition, health, schedule, reviews, profile.
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

const FEATURE_PAGES = [
  {
    path: '/dashboard/workouts',
    assert: async (page) => {
      await expect(page.locator('h1').first()).toContainText(/training/i);
      await expect(page.locator('#generate-workout-btn')).toBeVisible();
    },
    screenshot: 'training',
  },
  {
    path: '/dashboard/nutrition',
    assert: async (page) => {
      await expect(page.locator('h5').first()).toContainText(/macro/i);
      await expect(page.locator('#protein-ring')).toBeVisible();
      await expect(page.locator('#add-meal-form')).toBeVisible();
    },
    screenshot: 'nutrition',
  },
  {
    path: '/dashboard/health',
    assert: async (page) => {
      await expect(page.locator('h1').first()).toContainText(/health|recovery/i);
      await expect(page.locator('#readiness-card')).toBeVisible();
    },
    screenshot: 'health',
  },
  {
    path: '/dashboard/schedule',
    assert: async (page) => {
      await expect(page.locator('h1').first()).toContainText(/calendar|schedule/i);
      await expect(page.locator('button[onclick="showCreateMacrocycle()"]').first()).toBeVisible();
    },
    screenshot: 'schedule',
  },
  {
    path: '/dashboard/reviews',
    assert: async (page) => {
      await expect(page.locator('h1, h2').first()).toContainText(/review/i);
      await expect(page.locator('#reviews-list')).toBeVisible();
    },
    screenshot: 'reviews',
  },
  {
    path: '/dashboard/profile',
    assert: async (page) => {
      await expect(page.locator('h1').first()).toContainText(/profile|settings/i);
      await expect(page.locator('#profile-name')).toBeVisible();
    },
    screenshot: 'profile',
  },
  {
    path: '/dashboard/integrations',
    assert: async (page) => {
      await expect(page.locator('body')).toContainText(/integration|connect|calendar|recovery/i);
    },
    screenshot: 'integrations',
  },
];

test.describe('Feature pages', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await stabilizeTheme(page, 'light');
    await clearBrowserData(page);
    await authenticateOrSkip(page, testInfo);
  });

  for (const feature of FEATURE_PAGES) {
    test(`${feature.path} loads @smoke`, async ({ page }, testInfo) => {
      const finishErrors = collectConsoleErrors(page);
      await gotoApp(page, feature.path);

      await expect(page).toHaveURL(new RegExp(feature.path.replace(/\//g, '\\/')));
      await feature.assert(page);

      const errors = finishErrors().filter(
        (e) =>
          !e.includes('serviceWorker') &&
          !e.includes('favicon') &&
          !e.includes('Failed to load resource') &&
          !e.includes('Biomarker trends error')
      );
      expect(errors).toEqual([]);

      await screenshotViewport(page, feature.screenshot, testInfo);
    });
  }

  test('profile form fields are editable except email', async ({ page }) => {
    await gotoApp(page, '/dashboard/profile');

    const nameInput = page.locator('#profile-name');
    await expect(nameInput).toBeEditable();
    await nameInput.fill('E2E Athlete');
    await expect(nameInput).toHaveValue('E2E Athlete');

    await expect(page.locator('#profile-email')).toBeDisabled();
  });

  test('training page exposes generate workout control', async ({ page }) => {
    await gotoApp(page, '/dashboard/workouts');
    await expect(page.locator('#generate-workout-btn')).toBeEnabled();
  });

  test('health page has recovery check-in modal', async ({ page }) => {
    await gotoApp(page, '/dashboard/health');
    await expect(page.locator('#readiness-card')).toBeVisible();
    await expect(page.locator('[data-bs-target="#healthRecoveryModal"]')).toBeVisible();
    await expect(page.locator('#healthRecoveryModal')).toBeAttached();
  });
});

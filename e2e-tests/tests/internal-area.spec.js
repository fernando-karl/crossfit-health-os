/**
 * Internal area — authenticated flows, API wiring, and interactive UI.
 */

const { test, expect } = require('@playwright/test');
const {
  gotoApp,
  collectConsoleErrors,
  authenticateOrSkip,
  screenshotViewport,
  isMobileProject,
  prepareAuthenticatedPage,
  authApiGet,
  openNavbarIfCollapsed,
  openUserMenu,
  scrollIntoView,
} = require('../utils/helpers');

const API = process.env.API_BASE_URL || 'http://127.0.0.1:8003/api/v1';

test.describe('Internal area — APIs', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await authenticateOrSkip(page, testInfo);
  });

  test('core authenticated APIs respond successfully @smoke', async ({ page }) => {
    const endpoints = [
      '/users/me',
      '/onboarding/progress',
      '/gamification/stats',
      '/today/window',
      '/health/recovery/latest',
      '/training/sessions?limit=5',
      '/training/prs',
    ];

    for (const path of endpoints) {
      const res = await authApiGet(page, path);
      expect(res.status(), `${path} should not 401/500`).toBeLessThan(500);
      expect(res.status(), `${path} should be authorized`).not.toBe(401);
    }
  });
});

test.describe('Internal area — dashboard', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await prepareAuthenticatedPage(page);
    await authenticateOrSkip(page, testInfo);
  });

  test('dashboard hydrates after API load @smoke', async ({ page }, testInfo) => {
    const finishErrors = collectConsoleErrors(page);
    await gotoApp(page, '/dashboard');

    await page.waitForFunction(() => {
      const loading = document.querySelector('#loading-state');
      const newUser = document.querySelector('#new-user-state');
      const active = document.querySelector('#active-user-state');
      if (!loading) return true;
      const loadingDone =
        loading.classList.contains('d-none') || loading.offsetParent === null;
      const hasState =
        (newUser && !newUser.classList.contains('d-none')) ||
        (active && !active.classList.contains('d-none'));
      return loadingDone && hasState;
    }, { timeout: 20000 });

    const token = await page.evaluate(() => localStorage.getItem('access_token'));
    expect(token).toBeTruthy();

    const errors = finishErrors().filter(
      (e) => !e.includes('serviceWorker') && !e.includes('favicon')
    );
    expect(errors).toEqual([]);

    await screenshotViewport(page, 'internal-dashboard-hydrated', testInfo);
  });

  test('recovery modal opens from dashboard quick action', async ({ page }, testInfo) => {
    await gotoApp(page, '/dashboard');
    await page.waitForFunction(() => {
      const loading = document.querySelector('#loading-state');
      return !loading || loading.classList.contains('d-none') || loading.offsetParent === null;
    }, { timeout: 20000 });

    await page.evaluate(() => {
      if (typeof openRecoveryModal === 'function') openRecoveryModal();
    });
    await expect(page.locator('#recoveryModal')).toBeVisible();
    await expect(page.locator('#recovery-sleep')).toBeVisible();
    await expect(page.locator('#recovery-soreness')).toBeVisible();

    if (isMobileProject(testInfo)) {
      await page.locator('#recoveryModal .btn-close').click();
      await page.waitForFunction(() => {
        const modal = document.getElementById('recoveryModal');
        return modal && !modal.classList.contains('show');
      });

      await page.locator('#chos-fab-btn').click();
      await expect(page.locator('#chos-sheet.is-open')).toBeVisible();
      await expect(page.locator('[data-quick-action="recovery"]')).toHaveAttribute('href', /log-recovery/);

      const recoveryCard = page.locator('a[onclick*="openRecoveryModal"]').first();
      if (await recoveryCard.isVisible().catch(() => false)) {
        await page.locator('#chos-sheet-backdrop').click({ force: true });
        await scrollIntoView(recoveryCard);
        await recoveryCard.click();
        await expect(page.locator('#recoveryModal')).toBeVisible();
      }
    }
  });
});

test.describe('Internal area — training', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await prepareAuthenticatedPage(page);
    await authenticateOrSkip(page, testInfo);
  });

  test('generate workout triggers API without page crash @smoke', async ({ page }) => {
    await gotoApp(page, '/dashboard/workouts');
    await expect(page.locator('#generate-workout-btn')).toBeEnabled();

    const responsePromise = page.waitForResponse(
      (res) => res.url().includes('/api/v1/training/generate') && res.request().method() === 'POST',
      { timeout: 30000 }
    ).catch(() => null);

    await page.locator('#generate-workout-btn').click();
    const response = await responsePromise;

    if (response) {
      expect(response.status()).toBeLessThan(500);
    }

    await expect(page.locator('body')).toBeVisible();
    await expect(page.locator('#workouts-container')).toBeVisible();
  });

  test('workouts list loads from API', async ({ page }) => {
    await gotoApp(page, '/dashboard/workouts');

    await page.waitForFunction(() => {
      const container = document.querySelector('#workouts-container');
      return container && !container.querySelector('.spinner-border');
    }, { timeout: 15000 }).catch(() => {});

    const hasContent = await page.locator('#workouts-container').textContent();
    expect(hasContent?.length).toBeGreaterThan(0);
  });
});

test.describe('Internal area — profile & nutrition', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await prepareAuthenticatedPage(page);
    await authenticateOrSkip(page, testInfo);
  });

  test('profile loads user email from API', async ({ page }) => {
    await gotoApp(page, '/dashboard/profile');

    await page.waitForFunction(() => {
      const email = document.querySelector('#profile-email');
      return email && email.value && email.value.includes('@');
    }, { timeout: 10000 });

    const email = await page.locator('#profile-email').inputValue();
    expect(email).toMatch(/@/);
  });

  test('profile save calls PATCH /users/me', async ({ page }) => {
    await gotoApp(page, '/dashboard/profile');
    await page.waitForFunction(() => {
      const email = document.querySelector('#profile-email');
      return email && email.value && email.value.includes('@');
    }, { timeout: 15000 });

    const patchPromise = page.waitForResponse(
      (res) => res.url().includes('/api/v1/users/me') && res.request().method() === 'PATCH',
      { timeout: 15000 }
    );

    await page.locator('#profile-name').fill('E2E Internal Test');
    await page.locator('#btn-save-profile').click();

    const patch = await patchPromise;
    expect(patch.status()).toBeLessThan(500);
    expect(patch.status()).not.toBe(401);
  });

  test('nutrition add-meal form accepts input', async ({ page }) => {
    await gotoApp(page, '/dashboard/nutrition');

    await page.locator('#add-meal-cals').fill('450');
    await page.locator('#add-meal-protein').fill('30');
    await expect(page.locator('#add-meal-form button[type="submit"], #add-meal-form .chos-btn').first()).toBeEnabled();
  });
});

test.describe('Internal area — schedule, programs, reviews', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await prepareAuthenticatedPage(page);
    await authenticateOrSkip(page, testInfo);
  });

  test('schedule shows calendar or empty macrocycle state', async ({ page }) => {
    await gotoApp(page, '/dashboard/schedule');

    const hasMacro = await page.locator('#macro-banner').isVisible().catch(() => false);
    const hasEmpty = await page.locator('body').textContent();
    expect(hasMacro || /macrocycle|calendar/i.test(hasEmpty || '')).toBe(true);
  });

  test('programs generation form is interactive', async ({ page }) => {
    await gotoApp(page, '/dashboard/programs');

    await expect(page.locator('#program-form')).toBeVisible();
    await expect(page.locator('#prog-composer')).toBeVisible();
    await expect(page.locator('#btn-program-submit')).toBeEnabled();
    await page.locator('#prog-name').fill('E2E Test Macro');
    await expect(page.locator('#prog-name')).toHaveValue('E2E Test Macro');
  });

  test('reviews page generate button is wired', async ({ page }) => {
    await gotoApp(page, '/dashboard/reviews');

    await expect(page.locator('#btn-generate-review')).toBeVisible();
    await expect(page.locator('#reviews-list')).toBeVisible();
  });
});

test.describe('Internal area — account & secondary pages', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await prepareAuthenticatedPage(page);
    await authenticateOrSkip(page, testInfo);
  });

  const SECONDARY_PAGES = [
    { path: '/dashboard/billing', pattern: /billing|subscription|trial/i },
    { path: '/dashboard/badges', pattern: /badge|achievement|streak/i },
    { path: '/dashboard/referrals', pattern: /refer|friend|code/i },
  ];

  for (const { path, pattern } of SECONDARY_PAGES) {
    test(`${path} loads for authenticated user`, async ({ page }) => {
      await gotoApp(page, path);
      await expect(page).toHaveURL(new RegExp(path.replace(/\//g, '\\/')));
      await expect(page.locator('body')).toContainText(pattern);
    });
  }

  test('user menu exposes profile and logout', async ({ page }, testInfo) => {
    await gotoApp(page, '/dashboard');

    if (isMobileProject(testInfo)) {
      // Mobile: hamburger menu + bottom tab profile
      await openUserMenu(page);
      await expect(page.locator('.dropdown-menu a[href="/dashboard/profile"]')).toBeVisible();
      await expect(page.locator('#logout-btn')).toBeVisible();

      await gotoApp(page, '/dashboard/profile');
      await expect(page).toHaveURL(/\/dashboard\/profile/);
      await expect(page.locator('#profile-email, #profile-name').first()).toBeVisible();
    } else {
      await page.locator('#userDropdown').click();
      await expect(page.locator('.dropdown-menu a[href="/dashboard/profile"]')).toBeVisible();
      await expect(page.locator('#logout-btn')).toBeVisible();
    }
  });

  test('integrations calendar buttons respond without crash', async ({ page }) => {
    await gotoApp(page, '/dashboard/integrations');

    await expect(page.locator('#btn-calendar-connect')).toBeVisible();
    await page.locator('#btn-calendar-sync').click();
    await expect(page.locator('body')).toBeVisible();
  });

  test('theme toggle switches data-theme', async ({ page }, testInfo) => {
    await gotoApp(page, '/dashboard');

    const toggle = page.locator('[data-action="toggle-theme"]');
    if (!(await toggle.isVisible())) {
      await page.locator('.navbar-toggler').click();
      await expect(toggle).toBeVisible({ timeout: 5000 });
    }

    const before = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    await toggle.click();
    const after = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    expect(after).not.toBe(before);
  });
});

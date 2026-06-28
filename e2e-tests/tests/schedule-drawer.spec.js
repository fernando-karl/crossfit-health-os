/**
 * Schedule drawer — visual pickers (shift, type, duration, stimulus).
 */

const { test, expect } = require('@playwright/test');
const {
  gotoApp,
  authenticateOrSkip,
  prepareAuthenticatedPage,
  seedActiveProgramForSchedule,
  screenshotViewport,
} = require('../utils/helpers');

test.describe('Schedule drawer pickers', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await prepareAuthenticatedPage(page);
    await authenticateOrSkip(page, testInfo);
  });

  test('day drawer shows chip pickers and filters stimulus by type @smoke', async ({ page }, testInfo) => {
    const { today } = await seedActiveProgramForSchedule(page);
    await gotoApp(page, '/dashboard/schedule');
    await expect(page.locator('#calendar-grid')).toBeVisible({ timeout: 15000 });

    const dayCard = page.locator(`.chos-day-card[onclick*="${today}"]`).first();
    await expect(dayCard).toBeVisible({ timeout: 10000 });
    await dayCard.click();

    const drawer = page.locator('#dayDrawer');
    await expect(drawer).toBeVisible();
    await expect(page.locator('.chos-session-shift').first()).toBeVisible();
    await expect(drawer.locator('.chos-shift-chip')).toHaveCount(4);
    await expect(drawer.locator('.chos-type-chip')).toHaveCount(5);
    await expect(drawer.locator('.chos-duration-chip')).toHaveCount(6, { timeout: 5000 });
    await expect(page.locator('.chos-session-shift').first()).toBeVisible();
    await expect(drawer.locator('.chos-stimulus-chip[data-stimulus]').first()).toBeVisible();

    const sessionCard = drawer.locator('[data-idx]').first();
    await sessionCard.locator('.chos-type-chip[data-workout-type="strength"]').click();
    await expect(sessionCard.locator('.chos-type-chip.is-selected')).toHaveCount(1);
    await expect(drawer.getByText(/compatíveis|compatible/i)).toBeVisible();

    await sessionCard.locator('.chos-duration-chip[data-duration="90"]').click();
    await expect(sessionCard.locator('.chos-duration-chip[data-duration="90"]')).toHaveClass(/is-selected/);

    await sessionCard.locator('.chos-shift-chip[data-shift="evening"]').click();
    await expect(sessionCard.locator('.chos-shift-chip[data-shift="evening"]')).toHaveClass(/is-selected/);
    await expect(sessionCard.locator('[data-field="start_time"]')).toHaveValue('18:00');

    await screenshotViewport(page, 'schedule-drawer-pickers', testInfo);
  });

  test('day drawer pickers work on mobile @smoke', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const { today } = await seedActiveProgramForSchedule(page);
    await gotoApp(page, '/dashboard/schedule');
    await page.locator(`.chos-day-card[onclick*="${today}"]`).first().click();
    await expect(page.locator('#dayDrawer')).toBeVisible();
    await expect(page.locator('.chos-shift-chip').first()).toBeVisible();
    await expect(page.locator('.chos-type-chip').first()).toBeVisible();
    await screenshotViewport(page, 'schedule-drawer-mobile', testInfo);
  });
});

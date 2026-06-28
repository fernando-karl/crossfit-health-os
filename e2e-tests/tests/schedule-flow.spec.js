/**
 * Schedule flow — calendar → start planned session → complete → "Done" badge.
 */

const { test, expect } = require('@playwright/test');
const {
  gotoApp,
  authenticateOrSkip,
  prepareAuthenticatedPage,
  seedActiveProgramForSchedule,
  findSchedulablePlannedSession,
  completeWorkoutModal,
  screenshotViewport,
  authApiGet,
} = require('../utils/helpers');

test.describe('Schedule training flow', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await prepareAuthenticatedPage(page);
    await authenticateOrSkip(page, testInfo);
  });

  test('schedule page shows timeline and week strip @smoke', async ({ page }, testInfo) => {
    await seedActiveProgramForSchedule(page);
    await gotoApp(page, '/dashboard/schedule');

    await expect(page.locator('#phase-timeline')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('#week-strip')).toBeVisible();
    await expect(page.locator('#calendar-grid')).toBeVisible();

    await expect(page.locator('#nav-train-now-item')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#nav-train-now')).toContainText(/Treinar agora|Train now/i);

    await screenshotViewport(page, 'schedule-loaded', testInfo);
  });

  test('grid shortcuts start workout without opening drawer @smoke', async ({ page }) => {
    test.setTimeout(90000);

    const { today } = await seedActiveProgramForSchedule(page);
    const { session, micro } = await findSchedulablePlannedSession(page, today);
    const schedulable = (micro.sessions || []).filter(
      (s) => s.generated_template_id && s.status !== 'skipped' && !s.completed
    );
    const alt = schedulable.find((s) => s.id !== session.id) || session;

    await gotoApp(page, '/dashboard/schedule');
    await expect(page.locator('#calendar-grid')).toBeVisible({ timeout: 15000 });

    const playBtn = page.locator(
      `.chos-session-item[data-session-id="${session.id}"] [data-action="quickstart"]`
    );
    await expect(playBtn).toBeVisible({ timeout: 10000 });
    await playBtn.scrollIntoViewIfNeeded();

    await Promise.all([
      page.waitForURL(/\/dashboard\/workouts/, { timeout: 15000 }),
      playBtn.click(),
    ]);
    await expect(page.locator('#dayDrawer.show')).toHaveCount(0);

    await gotoApp(page, '/dashboard/schedule');
    await expect(page.locator('#calendar-grid')).toBeVisible({ timeout: 15000 });

    const card = page.locator(`.chos-session-item[data-session-id="${alt.id}"]`);
    await expect(card).toBeVisible({ timeout: 10000 });
    await card.scrollIntoViewIfNeeded();
    await page.keyboard.press('Escape');

    const dblTarget = card.locator('.chos-session-item__body');
    await expect(dblTarget).toBeVisible({ timeout: 10000 });
    await dblTarget.scrollIntoViewIfNeeded();

    await Promise.all([
      page.waitForURL(/\/dashboard\/workouts/, { timeout: 15000 }),
      dblTarget.dblclick(),
    ]);
    await expect(page.locator('#dayDrawer.show')).toHaveCount(0);
  });

  test('calendar → train → complete → shows Done badge @smoke', async ({ page }) => {
    test.setTimeout(90000);

    const { today } = await seedActiveProgramForSchedule(page);
    const { session, micro } = await findSchedulablePlannedSession(page, today);

    await gotoApp(page, '/dashboard/schedule');
    await expect(page.locator('#calendar-grid')).toBeVisible({ timeout: 15000 });

    // Open the day drawer for the planned session.
    const dayCard = page.locator(`.chos-day-card[onclick*="${session.date}"]`).first();
    await expect(dayCard).toBeVisible({ timeout: 10000 });
    await dayCard.click();
    await expect(page.locator('#dayDrawer')).toBeVisible();
    await expect(page.locator('#drawer-sessions')).toBeVisible();

    const startBtn = page.locator('#dayDrawer button.chos-btn-primary').first();
    await expect(startBtn).toBeVisible({ timeout: 10000 });

    await Promise.all([
      page.waitForURL(/\/dashboard\/workouts/, { timeout: 15000 }),
      startBtn.click(),
    ]);

    const { created, postData } = await completeWorkoutModal(page);
    expect(postData?.planned_session_id || created.planned_session_id).toBe(session.id);

    // Banner when workout came from the schedule plan.
    await expect(page.locator('#schedule-complete-banner')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#schedule-complete-banner')).toContainText(/schedule|calendário/i);

    // Return to calendar — session should refresh and show Done.
    await gotoApp(page, '/dashboard/schedule');
    await expect(page.locator('#calendar-grid .chos-day-card').first()).toBeVisible({ timeout: 15000 });
    await page.waitForResponse(
      (res) => res.url().includes('/api/v1/schedule/microcycles/') && res.status() === 200,
      { timeout: 15000 }
    ).catch(() => {});

    const microRes = await authApiGet(page, `/schedule/microcycles/${micro.id}`);
    expect(microRes.status()).toBe(200);
    const microFresh = await microRes.json();
    const updated = (microFresh.sessions || []).find((s) => String(s.id) === String(session.id));
    expect(updated?.completed).toBe(true);

    const doneDayCard = page.locator(`.chos-day-card[onclick*="${session.date}"]`).first();
    await expect(doneDayCard).toBeVisible({ timeout: 15000 });
    await expect(doneDayCard).toHaveClass(/chos-day-done/, { timeout: 15000 });
    await expect(doneDayCard.locator('.chos-session-status.is-completed')).toContainText(/done|feito/i, {
      timeout: 15000,
    });
  });
});

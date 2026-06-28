/**
 * Full training flow — generate → track → complete → list.
 */

const { test, expect } = require('@playwright/test');
const {
  gotoApp,
  authenticateOrSkip,
  prepareAuthenticatedPage,
  authApiGet,
} = require('../utils/helpers');

test.describe('Training flow', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await prepareAuthenticatedPage(page);
    await authenticateOrSkip(page, testInfo);
  });

  test('API: generate → session → complete → feedback @smoke', async ({ page }) => {
    const gen = await page.request.post(
      `${process.env.API_BASE_URL || 'http://127.0.0.1:8003/api/v1'}/training/generate`,
      {
        headers: {
          Authorization: `Bearer ${(await page.evaluate(() => localStorage.getItem('access_token')))}`,
          'Content-Type': 'application/json',
        },
        data: { force_rest: false },
      }
    );
    expect(gen.status()).toBe(200);
    const workout = await gen.json();
    expect(workout.template).toBeTruthy();

    const create = await page.request.post(
      `${process.env.API_BASE_URL || 'http://127.0.0.1:8003/api/v1'}/training/sessions`,
      {
        headers: {
          Authorization: `Bearer ${(await page.evaluate(() => localStorage.getItem('access_token')))}`,
          'Content-Type': 'application/json',
        },
        data: {
          workout_type: workout.template.workout_type || 'mixed',
          template_id: workout.template.id,
          movements: (workout.adjusted_movements || []).slice(0, 3).map((m) => ({
            movement: m.movement || 'movement',
            sets: m.sets,
            reps: m.reps,
          })),
          duration_minutes: 42,
          rpe_score: 7,
          notes: 'E2E training flow',
        },
      }
    );
    expect(create.status()).toBe(201);
    const session = await create.json();
    expect(session.id).toBeTruthy();

    const patch = await page.request.patch(
      `${process.env.API_BASE_URL || 'http://127.0.0.1:8003/api/v1'}/training/sessions/${session.id}`,
      {
        headers: {
          Authorization: `Bearer ${(await page.evaluate(() => localStorage.getItem('access_token')))}`,
          'Content-Type': 'application/json',
        },
        data: {
          completed_at: new Date().toISOString(),
          duration_minutes: 42,
          rpe_score: 7,
        },
      }
    );
    expect(patch.status()).toBe(200);
    const completed = await patch.json();
    expect(completed.completed_at).toBeTruthy();

    const feedback = await page.request.post(
      `${process.env.API_BASE_URL || 'http://127.0.0.1:8003/api/v1'}/review/feedback`,
      {
        headers: {
          Authorization: `Bearer ${(await page.evaluate(() => localStorage.getItem('access_token')))}`,
          'Content-Type': 'application/json',
        },
        data: {
          session_id: session.id,
          date: new Date().toISOString().split('T')[0],
          rpe_score: 7,
          difficulty: 'moderate',
          technique_quality: 7,
          pacing: 'good',
          energy_level_pre: 7,
          energy_level_post: 6,
          would_repeat: true,
          notes: 'E2E flow',
          movements_feedback: [],
        },
      }
    );
    expect(feedback.status()).toBe(201);

    const list = await authApiGet(page, '/training/sessions?limit=5');
    expect(list.status()).toBe(200);
    const sessions = await list.json();
    expect(sessions.some((s) => s.id === session.id)).toBe(true);
  });

  test('UI: generate workout opens tracking modal and completes @smoke', async ({ page }) => {
    await gotoApp(page, '/dashboard/workouts');

    await page.locator('#generate-workout-btn').click();

    await expect(page.locator('#workoutTrackingModal')).toBeVisible({ timeout: 30000 });
    await expect(page.locator('#complete-workout-btn')).toBeVisible();

    // Start timer briefly so duration > 0
    await page.locator('#timer-start').click();
    await page.waitForTimeout(1500);

    const patchPromise = page.waitForResponse(
      (res) =>
        res.url().includes('/api/v1/training/sessions/') &&
        res.request().method() === 'PATCH' &&
        res.status() < 500,
      { timeout: 30000 }
    );
    const createPromise = page.waitForResponse(
      (res) =>
        res.url().includes('/api/v1/training/sessions') &&
        res.request().method() === 'POST' &&
        res.status() < 500,
      { timeout: 30000 }
    );

    await page.locator('#complete-workout-btn').click();

    const createRes = await createPromise;
    expect(createRes.status()).toBe(201);

    const patchRes = await patchPromise;
    expect(patchRes.status()).toBe(200);

    await expect(page.locator('#workoutTrackingModal')).toBeHidden({ timeout: 15000 });

    // Session should appear in recent list
    await page.waitForFunction(() => {
      const container = document.querySelector('#workouts-container');
      return container && !container.querySelector('.spinner-border');
    }, { timeout: 15000 });

    const listText = await page.locator('#workouts-container').textContent();
    expect(listText?.length).toBeGreaterThan(10);
  });
});

/**
 * Helper functions for Playwright tests
 */

const { expect } = require('@playwright/test');

/**
 * Generate random email for unique test users
 */
function generateRandomEmail(prefix = 'test') {
  const timestamp = Date.now();
  const random = Math.floor(Math.random() * 10000);
  return `${prefix}+${timestamp}+${random}@example.com`;
}

/**
 * Generate random password
 */
function generatePassword(length = 12) {
  const charset = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%';
  let password = '';
  for (let i = 0; i < length; i++) {
    password += charset.charAt(Math.floor(Math.random() * charset.length));
  }
  return password;
}

/**
 * Clear all browser storage
 */
async function clearBrowserData(page, options = {}) {
  const keepAuth = options.keepAuth === true;
  try {
    if (!keepAuth) {
      await page.context().clearCookies();
    }
    await page.evaluate((preserve) => {
      try {
        if (preserve) {
          const token = localStorage.getItem('access_token');
          const refresh = localStorage.getItem('refresh_token');
          const user = localStorage.getItem('user');
          const theme = localStorage.getItem('chos-theme');
          localStorage.clear();
          sessionStorage.clear();
          if (token) localStorage.setItem('access_token', token);
          if (refresh) localStorage.setItem('refresh_token', refresh);
          if (user) localStorage.setItem('user', user);
          if (theme) localStorage.setItem('chos-theme', theme);
        } else {
          localStorage.clear();
          sessionStorage.clear();
        }
      } catch (e) {
        // Ignore - may not be accessible yet
      }
    }, keepAuth);
  } catch (e) {
    // Ignore errors during cleanup
  }
}

/**
 * Wait for network idle
 */
async function waitForNetworkIdle(page, timeout = 5000) {
  await page.waitForLoadState('networkidle', { timeout });
}

/**
 * Take screenshot with name
 */
async function takeScreenshot(page, name) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  await page.screenshot({ 
    path: `screenshots/${name}-${timestamp}.png`,
    fullPage: true 
  });
}

/**
 * Check if element is visible
 */
async function isVisible(page, selector) {
  const element = page.locator(selector);
  return await element.isVisible().catch(() => false);
}

/**
 * Get alert message text
 */
async function getAlertText(page) {
  const alert = page.locator('.lp-notice, .alert');
  if (await alert.first().isVisible()) {
    return alert.first().textContent();
  }
  return null;
}

/**
 * Fill form with data object
 */
async function fillForm(page, data) {
  for (const [field, value] of Object.entries(data)) {
    const input = page.locator(`[name="${field}"], [id="${field}"]`).first();
    if (await input.isVisible()) {
      await input.fill(value);
    }
  }
}

/**
 * Click checkbox by ID
 */
async function checkCheckbox(page, checkboxId) {
  const checkbox = page.locator(`#${checkboxId}`);
  if (await checkbox.isVisible() && !(await checkbox.isChecked())) {
    await checkbox.check();
  }
}

/**
 * Wait for redirect to URL
 */
async function waitForRedirect(page, urlPattern, timeout = 10000) {
  await page.waitForURL(urlPattern, { timeout });
}

/**
 * Get validation error message for a field
 */
async function getFieldError(page, fieldId) {
  const errorLocator = page.locator(`#${fieldId}`).locator('..').locator('.invalid-feedback');
  if (await errorLocator.isVisible()) {
    return errorLocator.textContent();
  }
  return null;
}

/**
 * Check if form has validation error
 */
async function hasValidationError(page, fieldId) {
  const input = page.locator(`#${fieldId}`);
  return await input.evaluate(el => el.classList.contains('is-invalid'));
}

/**
 * Get all form validation errors
 */
async function getAllValidationErrors(page) {
  const errors = [];
  const errorLocators = page.locator('.invalid-feedback:visible');
  const count = await errorLocators.count();
  for (let i = 0; i < count; i++) {
    errors.push(await errorLocators.nth(i).textContent());
  }
  return errors;
}

/**
 * Login via API and set localStorage
 */
async function loginViaAPI(page, email, password) {
  const apiBase = process.env.API_BASE_URL || 'http://localhost:8000/api/v1';
  const response = await page.request.post(`${apiBase}/auth/login`, {
    data: { email, password },
  });

  if (response.ok()) {
    const data = await response.json();
    await applyAuthToPage(page, data);
    return data;
  }
  return null;
}

/**
 * Register via API
 */
async function registerViaAPI(page, userData) {
  const response = await page.request.post(`${process.env.API_BASE_URL || 'http://localhost:8000/api/v1'}/auth/register`, {
    data: {
      accepted_terms: true,
      accepted_health_data: true,
      ...userData,
    }
  });
  
  if (response.ok()) {
    const data = await response.json();
    return data;
  }
  return null;
}

/**
 * Apply JWT tokens to browser localStorage (requires same-origin page).
 */
async function applyAuthToPage(page, data) {
  const baseUrl = process.env.BASE_URL || 'http://localhost:8000';
  await page.goto(baseUrl);
  await page.evaluate((tokens) => {
    localStorage.setItem('access_token', tokens.access_token);
    if (tokens.refresh_token) {
      localStorage.setItem('refresh_token', tokens.refresh_token);
    }
    if (tokens.user) {
      localStorage.setItem('user', JSON.stringify(tokens.user));
    }
  }, data);
}

/** Reuse one E2E user per worker to avoid auth rate limits. */
let sharedE2EUser = null;

/**
 * Create a test user and login - returns tokens or null if fails
 */
async function createAndLoginTestUser(page) {
  if (sharedE2EUser) {
    await applyAuthToPage(page, sharedE2EUser);
    return sharedE2EUser;
  }

  const email = generateRandomEmail('e2e');
  const password = 'SecurePass123';
  const apiBase = process.env.API_BASE_URL || 'http://localhost:8000/api/v1';

  try {
    // Prefer env credentials to avoid register rate limits
    const envEmail = process.env.TEST_EMAIL;
    const envPassword = process.env.TEST_PASSWORD;
    if (envEmail && envPassword) {
      const envLogin = await page.request.post(`${apiBase}/auth/login`, {
        data: { email: envEmail, password: envPassword },
      });
      if (envLogin.ok()) {
        const data = await envLogin.json();
        sharedE2EUser = { email: envEmail, password: envPassword, ...data };
        await applyAuthToPage(page, data);
        return sharedE2EUser;
      }
    }

    const regResponse = await page.request.post(`${apiBase}/auth/register`, {
      data: {
        email,
        password,
        confirm_password: password,
        name: 'E2E Test User',
        accepted_terms: true,
        accepted_health_data: true,
      },
    });

    if (!regResponse.ok()) {
      const regError = await regResponse.text();
      console.log('Registration failed:', regError.substring(0, 100));
    }

    const loginResponse = await page.request.post(`${apiBase}/auth/login`, {
      data: { email, password },
    });

    if (loginResponse.ok()) {
      const data = await loginResponse.json();
      sharedE2EUser = { email, password, ...data };
      await applyAuthToPage(page, data);
      return sharedE2EUser;
    }

    const loginError = await loginResponse.text();
    console.log('Login failed:', loginError.substring(0, 100));

    return null;
  } catch (e) {
    console.error('createAndLoginTestUser failed:', e.message);
    return null;
  }
}

/**
 * Complete onboarding via API
 */
async function completeOnboardingViaAPI(page, onboardingData) {
  // First login
  await loginViaAPI(page, onboardingData.email, onboardingData.password);
  
  // Then complete onboarding
  const response = await page.request.post(`${process.env.API_BASE_URL || 'http://localhost:8000/api/v1'}/onboarding/complete`, {
    data: {
      name: onboardingData.name,
      app_focus: onboardingData.appFocus || 'full',
      primary_goal: onboardingData.primaryGoal || 'both',
      fitness_level: onboardingData.fitnessLevel || 'intermediate',
      available_days: onboardingData.availableDays || ['monday', 'wednesday', 'friday'],
      preferred_time: onboardingData.preferredTime || 'morning',
      methodologies: onboardingData.methodologies || ['hwpo'],
      nutrition_enabled: onboardingData.appFocus !== 'training'
    }
  });
  
  return response.ok();
}

/**
 * Assert element contains text
 */
async function assertContains(page, selector, text) {
  const element = page.locator(selector);
  await expect(element).toContainText(text);
}

/**
 * Assert URL matches pattern
 */
async function assertURL(page, pattern) {
  await expect(page).toHaveURL(pattern);
}

/**
 * Navigate with stable locale (default en for predictable copy in assertions).
 */
async function gotoApp(page, path, options = {}) {
  const locale = options.locale ?? 'en';
  const hashIndex = path.indexOf('#');
  let url;
  if (hashIndex !== -1) {
    const base = path.slice(0, hashIndex);
    const hash = path.slice(hashIndex);
    const sep = base.includes('?') ? '&' : '?';
    url = `${base}${sep}lang=${locale}${hash}`;
  } else {
    url = path.includes('?') ? `${path}&lang=${locale}` : `${path}?lang=${locale}`;
  }
  await page.goto(url);
  await page.waitForLoadState('domcontentloaded');
}

/**
 * Auth pages with English copy for stable assertions.
 */
async function gotoAuthPage(page, path) {
  await gotoApp(page, path, { locale: 'en' });
  await page.waitForSelector('#alert-container, form', { state: 'attached' });
}

/**
 * Scroll element into view before interaction (mobile viewports).
 */
async function scrollIntoView(locator) {
  await locator.scrollIntoViewIfNeeded();
}

/**
 * Fill an input after scrolling it into view.
 */
async function fillInput(page, selector, value) {
  const input = page.locator(selector);
  await scrollIntoView(input);
  await input.fill(value);
}

/**
 * Click a button after scrolling it into view.
 */
async function clickButton(page, selector) {
  const btn = page.locator(selector);
  await scrollIntoView(btn);
  await btn.click();
}

/**
 * Fill minimal register form (current single-password UX + LGPD checkboxes).
 */
async function fillMinimalRegister(page, data = {}) {
  const email = data.email ?? generateRandomEmail('reg');
  await fillInput(page, '#name', data.name ?? 'Test User');
  await fillInput(page, '#email', email);
  await fillInput(page, '#password', data.password ?? 'SecurePass123');

  if (data.acceptTerms !== false) {
    await scrollIntoView(page.locator('#accepted_terms'));
    await page.locator('#accepted_terms').check({ force: true });
    await scrollIntoView(page.locator('#accepted_health_data'));
    await page.locator('#accepted_health_data').check({ force: true });
  }

  return { email, password: data.password ?? 'SecurePass123' };
}

/**
 * Submit register form (scrolls button into view on mobile).
 */
async function submitRegister(page) {
  await clickButton(page, '#register-btn');
}

/**
 * Pin theme before navigation to stabilize visual snapshots.
 */
async function stabilizeTheme(page, theme = 'light') {
  await page.addInitScript((value) => {
    localStorage.setItem('chos-theme', value);
  }, theme);
}

/**
 * Returns true when running a mobile Playwright project.
 */
function isMobileProject(testInfo) {
  return /mobile/i.test(testInfo.project.name);
}

/**
 * Expand collapsed Bootstrap navbar (mobile / narrow viewport).
 */
async function openNavbarIfCollapsed(page) {
  const toggler = page.locator('.navbar-toggler');
  const nav = page.locator('#navbarNav');
  if (await toggler.isVisible().catch(() => false)) {
    const expanded = await nav.evaluate((el) => el.classList.contains('show')).catch(() => false);
    if (!expanded) {
      await toggler.click();
      await expect(nav).toHaveClass(/show/, { timeout: 5000 });
    }
  }
}

/**
 * Open user dropdown from navbar (expands hamburger on mobile first).
 */
async function openUserMenu(page) {
  await openNavbarIfCollapsed(page);
  await page.locator('#userDropdown').click();
  await expect(page.locator('#userDropdown + .dropdown-menu, .dropdown-menu:visible').first()).toBeVisible({
    timeout: 5000,
  });
}

/**
 * Attach console error collector; call returned fn() to get errors.
 */
function collectConsoleErrors(page) {
  const errors = [];
  const handler = (msg) => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  };
  page.on('console', handler);
  return () => {
    page.off('console', handler);
    return errors;
  };
}

/**
 * Prepare page for authenticated internal tests without re-login.
 */
async function prepareAuthenticatedPage(page, theme = 'light') {
  await stabilizeTheme(page, theme);
  await clearBrowserData(page, { keepAuth: true });
}

/**
 * Authenticated API GET using Bearer token (not cookies).
 */
async function authApiGet(page, path) {
  const apiBase = process.env.API_BASE_URL || 'http://localhost:8000/api/v1';
  const token =
    sharedE2EUser?.access_token ||
    (await page.evaluate(() => localStorage.getItem('access_token')));
  return page.request.get(`${apiBase}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
}

async function authApiPost(page, path, data = {}) {
  const apiBase = process.env.API_BASE_URL || 'http://localhost:8000/api/v1';
  const token =
    sharedE2EUser?.access_token ||
    (await page.evaluate(() => localStorage.getItem('access_token')));
  return page.request.post(`${apiBase}${path}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'Content-Type': 'application/json',
    },
    data,
  });
}

async function authApiPatch(page, path, data = {}) {
  const apiBase = process.env.API_BASE_URL || 'http://localhost:8000/api/v1';
  const token =
    sharedE2EUser?.access_token ||
    (await page.evaluate(() => localStorage.getItem('access_token')));
  return page.request.patch(`${apiBase}${path}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'Content-Type': 'application/json',
    },
    data,
  });
}

/**
 * Generate + activate a one-week program so the schedule has planned sessions.
 */
async function seedActiveProgramForSchedule(page) {
  const today = new Date().toISOString().split('T')[0];
  const gen = await authApiPost(page, '/programs/generate', {
    composer: 'heuristic',
    weeks: ['build'],
    deload_weeks: [],
    primary_focus: ['squat_volume'],
    sessions_per_week: 5,
    start_date: today,
    name: 'E2E Schedule Flow',
  });
  if (!gen.ok()) {
    const body = await gen.text();
    throw new Error(`programs/generate failed (${gen.status()}): ${body.slice(0, 200)}`);
  }
  const program = await gen.json();

  const activate = await authApiPost(page, `/programs/${program.id}/activate`, {});
  if (!activate.ok()) {
    const body = await activate.text();
    throw new Error(`programs/activate failed (${activate.status()}): ${body.slice(0, 200)}`);
  }

  return { program, today };
}

/**
 * Return the first non-rest planned session with a generated template in the active week.
 */
async function findSchedulablePlannedSession(page, dateIso) {
  const macroRes = await authApiGet(page, '/schedule/macrocycles/active');
  if (!macroRes.ok()) {
    throw new Error('No active macrocycle after program activation');
  }
  const macro = await macroRes.json();
  const microcycles = macro.microcycles || [];
  let micro =
    microcycles.find((m) => m.start_date <= dateIso && m.end_date >= dateIso) ||
    microcycles[0];
  if (!micro) {
    throw new Error('Active macrocycle has no microcycles');
  }

  const res = await authApiGet(page, `/schedule/microcycles/${micro.id}`);
  if (!res.ok()) {
    throw new Error(`Could not load microcycle (${res.status()})`);
  }
  const microData = await res.json();
  const session = (microData.sessions || []).find(
    (s) => s.generated_template_id && s.status !== 'skipped' && !s.completed
  );
  if (!session) {
    throw new Error('No schedulable planned session with template in active microcycle');
  }
  return { session, micro: microData };
}

/**
 * Complete the workout tracking modal (assumes modal is open).
 * Returns { created, postData } from the session POST.
 */
async function completeWorkoutModal(page) {
  await expect(page.locator('#workoutTrackingModal')).toBeVisible({ timeout: 30000 });
  await expect(page.locator('#complete-workout-btn')).toBeVisible();

  let postData = null;
  const onRequest = (req) => {
    if (
      req.method() === 'POST' &&
      /\/api\/v1\/training\/sessions\/?$/.test(new URL(req.url()).pathname)
    ) {
      try {
        postData = req.postDataJSON();
      } catch (_) {
        postData = null;
      }
    }
  };
  page.on('request', onRequest);

  await page.locator('#timer-start').click();
  await page.waitForTimeout(800);

  const createPromise = page.waitForResponse(
    (res) =>
      res.url().includes('/api/v1/training/sessions') &&
      res.request().method() === 'POST' &&
      res.status() < 500,
    { timeout: 30000 }
  );
  const patchPromise = page.waitForResponse(
    (res) =>
      res.url().includes('/api/v1/training/sessions/') &&
      res.request().method() === 'PATCH' &&
      res.status() < 500,
    { timeout: 30000 }
  );

  await page.locator('#complete-workout-btn').click();

  const createRes = await createPromise;
  expect(createRes.status()).toBe(201);
  const created = await createRes.json();
  const patchRes = await patchPromise;
  expect(patchRes.status()).toBe(200);

  page.off('request', onRequest);

  await expect(page.locator('#workoutTrackingModal')).toBeHidden({ timeout: 15000 });
  return { created, postData };
}

/**
 * Create authenticated session or skip the test.
 */
async function authenticateOrSkip(page, testInfo) {
  const user = await createAndLoginTestUser(page);
  if (!user) {
    testInfo.skip(true, 'Could not create test user — check backend on BASE_URL');
  }
  return user;
}

/**
 * Screenshot with viewport suffix (desktop / mobile).
 */
async function screenshotViewport(page, name, testInfo) {
  const suffix = isMobileProject(testInfo) ? 'mobile' : 'desktop';
  await takeScreenshot(page, `${name}-${suffix}`);
}

module.exports = {
  generateRandomEmail,
  generatePassword,
  clearBrowserData,
  waitForNetworkIdle,
  takeScreenshot,
  isVisible,
  getAlertText,
  fillForm,
  checkCheckbox,
  waitForRedirect,
  getFieldError,
  hasValidationError,
  getAllValidationErrors,
  loginViaAPI,
  registerViaAPI,
  applyAuthToPage,
  createAndLoginTestUser,
  completeOnboardingViaAPI,
  assertContains,
  assertURL,
  gotoApp,
  gotoAuthPage,
  scrollIntoView,
  fillInput,
  clickButton,
  fillMinimalRegister,
  submitRegister,
  stabilizeTheme,
  isMobileProject,
  openNavbarIfCollapsed,
  openUserMenu,
  collectConsoleErrors,
  authenticateOrSkip,
  screenshotViewport,
  prepareAuthenticatedPage,
  authApiGet,
  authApiPost,
  authApiPatch,
  seedActiveProgramForSchedule,
  findSchedulablePlannedSession,
  completeWorkoutModal,
};

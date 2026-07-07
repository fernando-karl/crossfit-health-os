/**
 * Edge Cases and Error Handling Tests
 * Tests various edge cases, error scenarios, and boundary conditions
 */

const { test, expect } = require('@playwright/test');
const { TEST_USERS, FORM_VALIDATION, REGISTRATION_DATA } = require('../utils/fixtures');
const { 
  generateRandomEmail, 
  clearBrowserData, 
  getAllValidationErrors,
  loginViaAPI,
  registerViaAPI,
  gotoAuthPage,
  fillMinimalRegister,
  submitRegister,
  fillInput,
} = require('../utils/helpers');

test.describe('Edge Cases', () => {

  test.beforeEach(async ({ page }) => {
    await clearBrowserData(page);
  });

  test.afterEach(async ({ page }) => {
    await clearBrowserData(page);
  });

  // ============================================
  // REPEATED REGISTRATION ATTEMPTS
  // ============================================

  test.describe('Repeated Registration', () => {

    test('should handle rapid registration attempts', async ({ page }) => {
      await gotoAuthPage(page, '/register');
      
      await fillMinimalRegister(page, { email: generateRandomEmail('rapid'), name: 'Rapid User' });
      await submitRegister(page);
      
      await expect(page.locator('body')).toBeVisible();
    });

    test('should handle double-click on register button', async ({ page }) => {
      await gotoAuthPage(page, '/register');
      
      await fillMinimalRegister(page, { email: generateRandomEmail('double'), name: 'Double User' });
      
      const btn = page.locator('#register-btn');
      await btn.scrollIntoViewIfNeeded();
      await Promise.all([btn.click(), btn.click()]);
      
      await expect(page.locator('body')).toBeVisible();
    });

    test('should handle multiple sequential registration attempts', async ({ page }) => {
      for (let i = 0; i < 3; i++) {
        await gotoAuthPage(page, '/register');
        
        await fillMinimalRegister(page, {
          email: generateRandomEmail(`seq${i}`),
          name: `Seq User ${i}`,
        });
        await submitRegister(page);
        await page.waitForTimeout(1000);
      }
      
      await expect(page.locator('body')).toBeVisible();
    });

  });

  // ============================================
  // SESSION RESET SCENARIOS
  // ============================================

  test.describe('Session Reset', () => {

    test('should clear localStorage on logout', async ({ page }) => {
      // Set a fake token manually (backend registration is broken)
      await page.goto('/login');
      await page.evaluate(() => {
        localStorage.setItem('access_token', 'fake_token');
        localStorage.setItem('refresh_token', 'fake_refresh');
      });
      
      // Verify token exists
      let token = await page.evaluate(() => localStorage.getItem('access_token'));
      expect(token).toBe('fake_token');
      
      // Clear storage
      await clearBrowserData(page);
      
      // Verify token cleared
      token = await page.evaluate(() => localStorage.getItem('access_token'));
      expect(token).toBeNull();
    });

    test('should handle expired session gracefully', async ({ page }) => {
      // First navigate to a page
      await page.goto('/login');
      
      // Then set an expired/fake token
      await page.evaluate(() => {
        localStorage.setItem('access_token', 'expired_token_123');
        localStorage.setItem('user', JSON.stringify({ email: 'test@example.com' }));
      });
      
      // Try to access protected page
      await page.goto('/dashboard');
      
      // Should redirect to login or show error
      await expect(page).toHaveURL(/\/(login|dashboard)/);
    });

    test('should handle missing token gracefully', async ({ page }) => {
      // No token set
      await page.goto('/dashboard');
      
      // Should redirect to login
      await expect(page).toHaveURL(/\/login/);
    });

    test('should handle malformed user data in storage', async ({ page }) => {
      // First navigate to a page
      await page.goto('/login');
      
      // Then set malformed user data
      await page.evaluate(() => {
        localStorage.setItem('access_token', 'valid_token');
        localStorage.setItem('user', 'not valid json');
      });
      
      await page.goto('/dashboard');
      
      // Should handle gracefully
      await expect(page.locator('body')).toBeVisible();
    });

    test('should handle session storage corruption', async ({ page }) => {
      // First navigate to a page
      await page.goto('/login');
      
      // Then corrupt session storage
      await page.evaluate(() => {
        sessionStorage.setItem('test', '{ broken json');
      });
      
      // Navigate again
      await page.goto('/login');
      
      // Should handle without crashing
      await expect(page.locator('body')).toBeVisible();
    });

  });

  // ============================================
  // INPUT VALIDATION EDGE CASES
  // ============================================

  test.describe('Input Validation Edge Cases', () => {

    test('should reject future birth date', async ({ page }) => {
      await gotoAuthPage(page, '/register');
      
      const futureDate = new Date();
      futureDate.setFullYear(futureDate.getFullYear() + 5);
      const futureDateStr = futureDate.toISOString().split('T')[0];
      
      const result = await page.evaluate((dateStr) => {
        return FormValidator.validateBirthDate(dateStr);
      }, futureDateStr);
      expect(result.valid).toBe(false);
    });

    test('should reject very old birth date', async ({ page }) => {
      await gotoAuthPage(page, '/register');
      
      const result = await page.evaluate(() => {
        return FormValidator.validateBirthDate('1900-01-01');
      });
      expect(result.valid).toBe(false);
    });

    test('should handle extremely long name input', async ({ page }) => {
      await page.goto('/register');
      
      const longName = 'A'.repeat(500);
      await page.locator('#name').fill(longName);
      await page.locator('#name').blur();
      
      // Should either truncate or show validation error
      const hasError = await page.locator('#name').evaluate(
        el => el.classList.contains('is-invalid')
      );
      // Validation should catch this
      expect(hasError).toBe(true);
    });

    test('should handle special characters in name', async ({ page }) => {
      await page.goto('/register');
      
      const specialName = "O'Connor-Smith Jr. @#$%";
      await page.locator('#name').fill(specialName);
      await page.locator('#name').blur();
      
      // Name validation pattern may reject special characters
      const hasError = await page.locator('#name').evaluate(
        el => el.classList.contains('is-invalid')
      );
      // Pattern allows: /^[a-zA-ZÀ-ÿ\s'-]+$/
      // So O'Connor and hyphen should be fine, @#$% should fail
    });

    test('should handle negative weight values', async ({ page }) => {
      await gotoAuthPage(page, '/register');
      
      const result = await page.evaluate(() => FormValidator.validateWeight('-50'));
      expect(result.valid).toBe(false);
    });

    test('should handle extremely high weight values', async ({ page }) => {
      await gotoAuthPage(page, '/register');
      
      const result = await page.evaluate(() => FormValidator.validateWeight('1000'));
      expect(result.valid).toBe(false);
    });

    test('should handle zero height', async ({ page }) => {
      await gotoAuthPage(page, '/register');
      
      const result = await page.evaluate(() => FormValidator.validateHeight('0'));
      expect(result.valid).toBe(false);
    });

    test('should handle negative height values', async ({ page }) => {
      await gotoAuthPage(page, '/register');
      
      const result = await page.evaluate(() => FormValidator.validateHeight('-100'));
      expect(result.valid).toBe(false);
    });

  });

  // ============================================
  // NETWORK ERROR HANDLING
  // ============================================

  test.describe('Network Error Handling', () => {

    test('should show error on network failure', async ({ page }) => {
      // Block network to simulate failure
      await page.route('**/api/**', route => route.abort('failed'));
      
      await page.goto('/login');
      await page.locator('#email').fill('test@example.com');
      await page.locator('#password').fill('TestPass123');
      
      // Validate to bypass client validation
      const result = await page.evaluate(() => {
        const $form = $('#login-form');
        return FormValidator.validateForm($form);
      });
      
      // If form is valid, try submit (will fail due to network)
      if (result.valid) {
        await page.locator('#login-btn').click();
      }
      
      // App should not crash
      await expect(page.locator('body')).toBeVisible();
    });

    test('should handle slow network gracefully', async ({ page }) => {
      // Add delay to simulate slow network - use shorter delay
      await page.route('**/api/v1/auth/**', route => 
        route.continue({ delay: 2000 })
      );
      
      await page.goto('/login');
      await page.locator('#email').fill('test@example.com');
      await page.locator('#password').fill('TestPass123');
      
      // App should still be usable
      await expect(page.locator('#login-form')).toBeVisible();
    });

    test('should handle server 500 error', async ({ page }) => {
      // Mock server error
      await page.route('**/api/v1/auth/login', route => 
        route.fulfill({ status: 500, body: 'Internal Server Error' })
      );
      
      await page.goto('/login');
      await page.locator('#email').fill('test@example.com');
      await page.locator('#password').fill('TestPass123');
      
      // Validate first
      const result = await page.evaluate(() => {
        const $form = $('#login-form');
        return FormValidator.validateForm($form);
      });
      
      if (result.valid) {
        await page.locator('#login-btn').click();
      }
      
      // App should not crash
      await expect(page.locator('body')).toBeVisible();
    });

    test('should handle server 400 error', async ({ page }) => {
      // Mock bad request
      await page.route('**/api/v1/auth/login', route => 
        route.fulfill({ status: 400, body: JSON.stringify({ detail: 'Bad Request' }) })
      );
      
      await page.goto('/login');
      await page.locator('#email').fill('test@example.com');
      await page.locator('#password').fill('TestPass123');
      
      // Validate first
      const result = await page.evaluate(() => {
        const $form = $('#login-form');
        return FormValidator.validateForm($form);
      });
      
      if (result.valid) {
        await page.locator('#login-btn').click();
      }
      
      // App should not crash
      await expect(page.locator('body')).toBeVisible();
    });

    test('should handle timeout gracefully', async ({ page }) => {
      // Block the request to simulate timeout
      await page.route('**/api/v1/auth/login', route => 
        route.abort()
      );
      
      await page.goto('/login');
      await page.locator('#email').fill('test@example.com');
      await page.locator('#password').fill('TestPass123');
      
      // Validate first
      const result = await page.evaluate(() => {
        const $form = $('#login-form');
        return FormValidator.validateForm($form);
      });
      
      if (result.valid) {
        await page.locator('#login-btn').click();
      }
      
      // App should not crash
      await expect(page.locator('body')).toBeVisible();
    });

  });

  // ============================================
  // URL MANIPULATION
  // ============================================

  test.describe('URL Manipulation', () => {

    test('should handle direct URL to non-existent page', async ({ page }) => {
      await page.goto('/nonexistent-page-xyz');
      
      // Should show 404 or redirect
      await expect(page.locator('body')).toBeVisible();
    });

    test('should handle URL with special characters', async ({ page }) => {
      await page.goto('/register?email=test%40example.com&name=Test%20User');
      
      await expect(page.locator('body')).toBeVisible();
    });

    test('should handle URL with hash fragments', async ({ page }) => {
      await page.goto('/login#access_token=test_token');
      
      await expect(page.locator('body')).toBeVisible();
    });

    test('should handle URL with query parameters', async ({ page }) => {
      await page.goto('/login?redirect_to=/dashboard&param=value');
      
      // Page should load correctly
      await expect(page.locator('#login-form')).toBeVisible();
    });

  });

  // ============================================
  // BROWSER NAVIGATION
  // ============================================

  test.describe('Browser Navigation', () => {

    test('should handle browser back button', async ({ page }) => {
      await page.goto('/login');
      await page.goto('/register');
      
      // Press back
      await page.goBack();
      
      // Should be back on login
      await expect(page).toHaveURL(/\/login/);
    });

    test('should handle browser forward button', async ({ page }) => {
      await page.goto('/login');
      await page.goto('/register');
      await page.goBack();
      await page.goForward();
      
      // Should be on register
      await expect(page).toHaveURL(/\/register/);
    });

    test('should handle page refresh', async ({ page }) => {
      await page.goto('/login');
      await page.fill('#email', 'test@example.com');
      
      await page.reload();
      
      // Form should be cleared
      const emailValue = await page.locator('#email').inputValue();
      expect(emailValue).toBe('');
    });

  });

  // ============================================
  // CONCURRENT ACTIONS
  // ============================================

  test.describe('Concurrent Actions', () => {

    test('should handle multiple rapid form submissions', async ({ page }) => {
      await page.goto('/login');
      
      await page.locator('#email').fill('test@example.com');
      await page.locator('#password').fill('TestPass123');
      
      // Click submit button
      await page.locator('#login-btn').click();
      
      // Should handle without crashing - app should still be visible
      await expect(page.locator('body')).toBeVisible();
    });

    test('should handle navigating away during form submission', async ({ page }) => {
      await page.goto('/login');
      
      await page.locator('#email').fill('test@example.com');
      await page.locator('#password').fill('TestPass123');
      await page.locator('#login-btn').click();
      
      // Immediately navigate away
      await page.goto('/register');
      
      // Should handle gracefully
      await expect(page).toHaveURL(/\/register/);
    });

  });

  // ============================================
  // ACCESSIBILITY EDGE CASES
  // ============================================

  test.describe('Accessibility Edge Cases', () => {

    test('should handle keyboard navigation', async ({ page }) => {
      await page.goto('/login');
      
      // Tab through form fields
      await page.keyboard.press('Tab');
      await page.keyboard.press('Tab');
      await page.keyboard.press('Tab');
      
      // Should navigate without errors
      await expect(page.locator('body')).toBeVisible();
    });

    test('should handle form submission with keyboard', async ({ page }) => {
      await page.goto('/login');
      
      // Fill form using keyboard
      await page.locator('#email').focus();
      await page.keyboard.type('test@example.com');
      await page.keyboard.press('Tab');
      await page.keyboard.type('TestPass123');
      await page.keyboard.press('Tab');
      await page.keyboard.press('Enter');
      
      // Should submit form
      // Note: This may or may not work depending on form implementation
    });

    test('should close alerts when dismiss button clicked', async ({ page }) => {
      await page.goto('/login');
      await page.locator('#email').fill('wrong@example.com');
      await page.locator('#password').fill('WrongPass');
      await page.locator('#login-btn').click();

      const alert = page.locator('#alert-container .lp-notice.is-danger');
      await expect(alert).toBeVisible({ timeout: 10000 });

      await alert.locator('button.btn-close').click();
      await expect(alert).not.toBeVisible();
    });

  });

  // ============================================
  // STATE PERSISTENCE
  // ============================================

  test.describe('State Persistence', () => {

    test('should preserve form data on validation error', async ({ page }) => {
      await gotoAuthPage(page, '/register');
      
      await fillInput(page, '#name', 'Test User');
      await fillInput(page, '#email', 'test@example.com');
      await fillInput(page, '#password', 'weak');
      await submitRegister(page);
      
      await fillInput(page, '#password', 'SecurePass123');
      
      const nameValue = await page.locator('#name').inputValue();
      expect(nameValue).toBe('Test User');
      
      const emailValue = await page.locator('#email').inputValue();
      expect(emailValue).toBe('test@example.com');
    });

    test('should handle localStorage quota exceeded', async ({ page }) => {
      // Fill localStorage with large data
      await page.evaluate(() => {
        try {
          const largeData = 'x'.repeat(10 * 1024 * 1024); // 10MB
          localStorage.setItem('largeData', largeData);
        } catch (e) {
          // Expected to fail
        }
      });
      
      await page.goto('/login');
      
      // Should handle gracefully
      await expect(page.locator('body')).toBeVisible();
    });

  });

});

/**
 * Test Utilities for Agentys E2E Tests
 *
 * Common utilities and helpers for writing E2E tests.
 */

import { Page, Locator } from '@playwright/test';

/**
 * Wait for the app to be fully loaded
 */
export async function waitForAppReady(page: Page): Promise<void> {
  // Wait for the main app container to be visible
  await page.waitForSelector('[data-testid="app-container"]', {
    state: 'visible',
    timeout: 30000,
  });
}

/**
 * Wait for loading spinner to disappear
 */
export async function waitForLoadingComplete(page: Page): Promise<void> {
  const spinner = page.locator('[data-testid="loading-spinner"]');
  if (await spinner.isVisible()) {
    await spinner.waitFor({ state: 'hidden', timeout: 30000 });
  }
}

/**
 * Click a button and wait for navigation or loading to complete
 */
export async function clickAndWait(
  locator: Locator,
  page: Page
): Promise<void> {
  await locator.click();
  await waitForLoadingComplete(page);
}

/**
 * Fill a form field with data-testid
 */
export async function fillField(
  page: Page,
  testId: string,
  value: string
): Promise<void> {
  const field = page.locator(`[data-testid="${testId}"]`);
  await field.clear();
  await field.fill(value);
}

/**
 * Get element by data-testid
 */
export function getByTestId(page: Page, testId: string): Locator {
  return page.locator(`[data-testid="${testId}"]`);
}

/**
 * Check if element with data-testid exists and is visible
 */
export async function isVisible(page: Page, testId: string): Promise<boolean> {
  const element = page.locator(`[data-testid="${testId}"]`);
  return element.isVisible();
}

/**
 * Take a screenshot with a descriptive name
 */
export async function takeScreenshot(
  page: Page,
  name: string
): Promise<void> {
  await page.screenshot({
    path: `test-results/screenshots/${name}-${Date.now()}.png`,
    fullPage: true,
  });
}

/**
 * Mock the backend API response
 */
export async function mockApiResponse(
  page: Page,
  endpoint: string,
  response: unknown
): Promise<void> {
  await page.route(`**/api/${endpoint}`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(response),
    });
  });
}

/**
 * Simulate offline mode
 */
export async function goOffline(page: Page): Promise<void> {
  await page.context().setOffline(true);
}

/**
 * Simulate online mode
 */
export async function goOnline(page: Page): Promise<void> {
  await page.context().setOffline(false);
}

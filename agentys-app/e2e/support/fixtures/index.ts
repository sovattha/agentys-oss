/* eslint-disable react-hooks/rules-of-hooks */
/**
 * Agentys E2E Test Fixtures
 *
 * This module exports extended test fixtures with auto-cleanup capabilities.
 * Use these fixtures for consistent test setup and teardown.
 *
 * @example
 * import { test, expect } from '../support/fixtures';
 *
 * test('should do something', async ({ page, apiHelper }) => {
 *   // Your test code here
 * });
 */

import { test as base, expect } from '@playwright/test';
import { ApiHelper } from '../helpers/api-helper';

/**
 * Custom test fixtures for Agentys
 */
type TestFixtures = {
  /** API helper for backend interactions */
  apiHelper: ApiHelper;
};

/**
 * Extended test with Agentys fixtures
 */
export const test = base.extend<TestFixtures>({
  // eslint-disable-next-line no-empty-pattern
  apiHelper: async ({}, use) => {
    const helper = new ApiHelper();
    await use(helper);
    // Auto-cleanup after each test
    await helper.cleanup();
  },
});

export { expect };

// Re-export mock data for convenience
export * from './mock-data';

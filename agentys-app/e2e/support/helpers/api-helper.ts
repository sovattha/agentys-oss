/**
 * API Helper for E2E Tests
 *
 * Provides utilities for interacting with the Agentys backend API
 * during E2E tests. Includes auto-cleanup of created resources.
 */

const API_URL = process.env.API_URL || 'http://localhost:5050';

export class ApiHelper {
  private createdResources: Array<{ type: string; id: string }> = [];

  /**
   * Check if the backend API is healthy
   */
  async checkHealth(): Promise<boolean> {
    try {
      const response = await fetch(`${API_URL}/api/health`);
      return response.ok;
    } catch {
      return false;
    }
  }

  /**
   * Wait for the backend to be ready
   * @param timeout Maximum time to wait in milliseconds
   */
  async waitForBackend(timeout = 30000): Promise<void> {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      if (await this.checkHealth()) {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error(`Backend not ready after ${timeout}ms`);
  }

  /**
   * Trigger email sync
   */
  async triggerSync(): Promise<void> {
    const response = await fetch(`${API_URL}/api/sync/trigger`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      throw new Error(`Sync failed: ${response.statusText}`);
    }
  }

  /**
   * Get list of emails
   */
  async getEmails(limit = 10): Promise<unknown[]> {
    const response = await fetch(`${API_URL}/api/emails?limit=${limit}`);
    if (!response.ok) {
      throw new Error(`Failed to get emails: ${response.statusText}`);
    }
    return response.json();
  }

  /**
   * Create a draft email (for testing)
   */
  async createDraft(data: {
    to: string;
    subject: string;
    body: string;
  }): Promise<{ id: string }> {
    const response = await fetch(`${API_URL}/api/drafts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      throw new Error(`Failed to create draft: ${response.statusText}`);
    }

    const result = await response.json();
    this.createdResources.push({ type: 'draft', id: result.id });
    return result;
  }

  /**
   * Delete a draft by ID
   */
  async deleteDraft(id: string): Promise<void> {
    const response = await fetch(`${API_URL}/api/drafts/${id}`, {
      method: 'DELETE',
    });

    if (!response.ok && response.status !== 404) {
      throw new Error(`Failed to delete draft: ${response.statusText}`);
    }
  }

  /**
   * Cleanup all resources created during the test
   */
  async cleanup(): Promise<void> {
    for (const resource of this.createdResources) {
      try {
        if (resource.type === 'draft') {
          await this.deleteDraft(resource.id);
        }
      } catch (error) {
        console.warn(`Failed to cleanup ${resource.type} ${resource.id}:`, error);
      }
    }
    this.createdResources = [];
  }
}

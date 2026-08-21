import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  ACCOUNT_INVALID_EVENT,
  fetchEmailDetail,
  fetchEmails,
  generateDraft,
  markEmailRead,
  markEmailUnread,
  markEmailsBulk,
  setActiveAccountId,
} from "../api/emails";
import {
  _resetEmailBodyCacheForTests,
  writeEmailBodyCache,
} from "../api/emailBodyCache";

const mockFetch = vi.fn();

describe("Email Read Status API", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  describe("fetchEmails force refresh", () => {
    it("queues a sync job instead of sending force_refresh to the list endpoint", async () => {
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ success: true, job: { id: "job-1" } }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            count: 0,
            offset: 0,
            has_more: false,
            filter: "all",
            source: "syncing",
            emails: [],
          }),
        });

      const result = await fetchEmails({
        forceRefresh: true,
        skipCache: true,
        folder: "inbox",
        limit: 50,
      });

      expect(mockFetch).toHaveBeenNthCalledWith(
        1,
        expect.stringContaining("/api/sync/jobs"),
        expect.objectContaining({ method: "POST" })
      );
      expect(mockFetch).toHaveBeenNthCalledWith(
        2,
        expect.not.stringContaining("force_refresh=true"),
        expect.any(Object)
      );
      expect(result.source).toBe("syncing");
    });

    it("dispatches account-invalid when the backend rejects X-Account-Id", async () => {
      const onInvalid = vi.fn();
      window.addEventListener(ACCOUNT_INVALID_EVENT, onInvalid);
      setActiveAccountId("13");
      try {
        mockFetch.mockResolvedValueOnce({
          ok: false,
          status: 404,
          json: async () => ({
            error: "Account not found or not owned by caller",
            code: "INVALID_ACCOUNT_HEADER",
          }),
        });

        await expect(fetchEmails({ skipCache: true })).rejects.toThrow("Failed to fetch emails: 404");

        expect(onInvalid).toHaveBeenCalledOnce();
        expect(onInvalid.mock.calls[0][0]).toMatchObject({
          detail: {
            activeAccountId: "13",
            status: 404,
          },
        });
      } finally {
        window.removeEventListener(ACCOUNT_INVALID_EVENT, onInvalid);
        setActiveAccountId("default");
      }
    });
  });

  describe("fetchEmailDetail cache", () => {
    beforeEach(async () => {
      vi.stubGlobal("indexedDB", undefined);
      await _resetEmailBodyCacheForTests();
      setActiveAccountId("account-detail-cache");
    });

    afterEach(async () => {
      await _resetEmailBodyCacheForTests();
      setActiveAccountId("default");
    });

    it("serves a second detail load from the local body cache without backend refetch", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: "email-123",
          sender: "alex@example.com",
          sender_name: "Alex",
          subject: "Question",
          received_at: "2026-05-18T08:00:00Z",
          body: "Local cached body",
          body_html: "<p>Local cached body</p>",
          body_text: "Local cached body",
          is_read: false,
          has_attachments: false,
          to: ["nat@example.com"],
          cc: [],
        }),
      });

      const first = await fetchEmailDetail("email-123");
      const second = await fetchEmailDetail("email-123");

      expect(first.body).toBe("Local cached body");
      expect(second.body).toBe("Local cached body");
      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(mockFetch.mock.calls[0][0]).toEqual(expect.stringContaining("/emails/email-123"));
    });
  });

  describe("generateDraft", () => {
    beforeEach(async () => {
      vi.stubGlobal("indexedDB", undefined);
      await _resetEmailBodyCacheForTests();
      setActiveAccountId("account-draft-cache");
    });

    afterEach(async () => {
      await _resetEmailBodyCacheForTests();
      setActiveAccountId("default");
    });

    it("sends the cached local email body with on-demand draft generation", async () => {
      await writeEmailBodyCache("account-draft-cache", "email-123", {
        id: "email-123",
        sender: "alex@example.com",
        sender_name: "Alex",
        subject: "Question",
        received_at: "2026-05-18T08:00:00Z",
        body: "Local cached body",
        body_html: "<p>Local cached body</p>",
        body_text: "Local cached body",
        is_read: false,
        has_attachments: false,
        to: ["nat@example.com"],
        cc: [],
      });
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          email_id: "email-123",
          status: "processing",
        }),
      });

      await generateDraft("email-123", { instructions: "Réponds court" });

      const [, request] = mockFetch.mock.calls[0];
      const body = JSON.parse((request as RequestInit).body as string);
      expect(body).toMatchObject({
        instructions: "Réponds court",
        force: true,
        cached_email: {
          id: "email-123",
          sender: "alex@example.com",
          subject: "Question",
          body: "Local cached body",
          source: "local_email_body_cache",
        },
      });
    });
  });

  describe("markEmailRead", () => {
    it("marks an email as read", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          email_id: "email-123",
          is_read: true,
        }),
      });

      const result = await markEmailRead("email-123");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/emails/email-123/read"),
        expect.objectContaining({
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_read: true }),
        })
      );
      expect(result.success).toBe(true);
      expect(result.email_id).toBe("email-123");
      expect(result.is_read).toBe(true);
    });

    it("throws error on failure", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
      });

      await expect(markEmailRead("non-existent")).rejects.toThrow(
        "Failed to mark email as read: 404"
      );
    });

    it("throws error on network failure", async () => {
      mockFetch.mockRejectedValueOnce(new Error("Network error"));

      await expect(markEmailRead("email-123")).rejects.toThrow("Network error");
    });
  });

  describe("markEmailUnread", () => {
    it("marks an email as unread", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          email_id: "email-123",
          is_read: false,
        }),
      });

      const result = await markEmailUnread("email-123");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/emails/email-123/read"),
        expect.objectContaining({
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_read: false }),
        })
      );
      expect(result.success).toBe(true);
      expect(result.email_id).toBe("email-123");
      expect(result.is_read).toBe(false);
    });

    it("throws error on failure", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
      });

      await expect(markEmailUnread("email-123")).rejects.toThrow(
        "Failed to mark email as unread: 500"
      );
    });
  });

  describe("markEmailsBulk", () => {
    it("marks multiple emails as read", async () => {
      const emailIds = ["email-1", "email-2", "email-3"];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          updated_count: 3,
          email_ids: emailIds,
          is_read: true,
        }),
      });

      const result = await markEmailsBulk(emailIds, true);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/emails/bulk-read"),
        expect.objectContaining({
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email_ids: emailIds, is_read: true }),
        })
      );
      expect(result.success).toBe(true);
      expect(result.updated_count).toBe(3);
      expect(result.email_ids).toEqual(emailIds);
      expect(result.is_read).toBe(true);
    });

    it("marks multiple emails as unread", async () => {
      const emailIds = ["email-1", "email-2"];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          updated_count: 2,
          email_ids: emailIds,
          is_read: false,
        }),
      });

      const result = await markEmailsBulk(emailIds, false);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/emails/bulk-read"),
        expect.objectContaining({
          body: JSON.stringify({ email_ids: emailIds, is_read: false }),
        })
      );
      expect(result.is_read).toBe(false);
    });

    it("handles empty array", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          updated_count: 0,
          email_ids: [],
          is_read: true,
        }),
      });

      const result = await markEmailsBulk([], true);

      expect(result.updated_count).toBe(0);
      expect(result.email_ids).toEqual([]);
    });

    it("throws error on failure", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
      });

      await expect(markEmailsBulk(["email-1"], true)).rejects.toThrow(
        "Failed to bulk update emails: 400"
      );
    });
  });
});

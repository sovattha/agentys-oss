/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ApiClient, ApiError, resetApiClient } from "../services/api";

const mockFetch = vi.fn();

// Helper: create a mock Response with both .json() and .text() (API now uses text() first)
function mockResponse(data: unknown, opts: { ok?: boolean; status?: number } = {}) {
  const jsonStr = JSON.stringify(data);
  return {
    ok: opts.ok !== false,
    status: opts.status ?? (opts.ok === false ? 400 : 200),
    json: async () => data,
    text: async () => jsonStr,
  };
}

describe("ApiClient", () => {
  let client: ApiClient;

  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
    resetApiClient();
    client = new ApiClient("http://localhost:5000");
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  describe("health", () => {
    it("retourne le status healthy quand le backend est up", async () => {
      mockFetch.mockResolvedValueOnce(
        mockResponse({
          status: "healthy",
          version: "1.0.0",
          services: { email: "connected", llm: "connected" },
          timestamp: "2026-01-04T12:00:00Z",
        })
      );

      const result = await client.health();

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:5000/api/health",
        expect.objectContaining({
          method: "GET",
          headers: expect.objectContaining({ "Content-Type": "application/json" }),
        })
      );
      expect(result.status).toBe("healthy");
      expect(result.services.email).toBe("connected");
    });

    it("retourne degraded quand un service est down", async () => {
      mockFetch.mockResolvedValueOnce(
        mockResponse({
          status: "degraded",
          version: "1.0.0",
          services: { email: "disconnected", llm: "connected" },
          timestamp: "2026-01-04T12:00:00Z",
        })
      );

      const result = await client.health();

      expect(result.status).toBe("degraded");
      expect(result.services.email).toBe("disconnected");
    });

    it("lance une erreur si le backend est injoignable", async () => {
      mockFetch.mockRejectedValueOnce(new Error("Network error"));

      await expect(client.health()).rejects.toThrow("Network error");
    });
  });

  describe("listEmails", () => {
    it("retourne la liste des emails non lus", async () => {
      const mockEmails = [
        {
          id: "email-1",
          subject: "Test subject",
          sender: "test@example.com",
          received_at: "2026-01-04T10:00:00Z",
        },
        {
          id: "email-2",
          subject: "Another subject",
          sender: "other@example.com",
          received_at: "2026-01-04T11:00:00Z",
        },
      ];

      mockFetch.mockResolvedValueOnce(
        mockResponse({ count: 2, emails: mockEmails })
      );

      const result = await client.listEmails();

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:5000/api/emails?limit=50",
        expect.anything()
      );
      expect(result.count).toBe(2);
      expect(result.emails).toHaveLength(2);
      expect(result.emails[0].id).toBe("email-1");
    });

    it("respecte le parametre limit", async () => {
      mockFetch.mockResolvedValueOnce(
        mockResponse({ count: 0, emails: [] })
      );

      await client.listEmails(10);

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:5000/api/emails?limit=10",
        expect.anything()
      );
    });

    it("lance ApiError pour erreur 400", async () => {
      mockFetch.mockResolvedValueOnce(
        mockResponse({ error: "Invalid limit" }, { ok: false, status: 400 })
      );

      await expect(client.listEmails(-1)).rejects.toThrow(ApiError);
    });
  });

  describe("getEmail", () => {
    it("retourne le detail d'un email", async () => {
      const mockEmail = {
        id: "email-1",
        subject: "Test subject",
        sender: "test@example.com",
        body: "Email body content",
        received_at: "2026-01-04T10:00:00Z",
      };

      mockFetch.mockResolvedValueOnce(mockResponse(mockEmail));

      const result = await client.getEmail("email-1");

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:5000/api/emails/email-1",
        expect.anything()
      );
      expect(result.body).toBe("Email body content");
    });

    it("lance ApiError pour email non trouve", async () => {
      mockFetch.mockResolvedValueOnce(
        mockResponse({ error: "Email not found" }, { ok: false, status: 404 })
      );

      await expect(client.getEmail("non-existent")).rejects.toThrow(ApiError);
    });
  });

  describe("generatePreview", () => {
    it("genere un brouillon de reponse", async () => {
      mockFetch.mockResolvedValueOnce(
        mockResponse({
          draft: {
            id: "draft-1",
            content: "Bonjour, merci pour votre message...",
            confidence: 0.85,
          },
        })
      );

      const result = await client.generatePreview("email-1");

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:5000/api/emails/email-1/preview",
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({ "Content-Type": "application/json" }),
        })
      );
      expect(result.draft.confidence).toBe(0.85);
    });
  });

  describe("createDraft", () => {
    it("cree un brouillon dans le client email", async () => {
      mockFetch.mockResolvedValueOnce(
        mockResponse({ success: true, draft_id: "draft-created-1" })
      );

      const result = await client.createDraft("email-1", "Re: Test Subject", "Reply content");

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:5000/api/emails/email-1/draft",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ subject: "Re: Test Subject", body: "Reply content" }),
        })
      );
      expect(result.success).toBe(true);
    });
  });

  describe("sendDraft", () => {
    it("envoie le brouillon directement", async () => {
      mockFetch.mockResolvedValueOnce(
        mockResponse({ success: true, message_id: "sent-1" })
      );

      const result = await client.sendDraft("draft-1");

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:5000/api/emails/draft-1/send",
        expect.objectContaining({ method: "POST" })
      );
      expect(result.success).toBe(true);
    });
  });

  describe("submitFeedback", () => {
    it("envoie un feedback pour ameliorer l'IA", async () => {
      mockFetch.mockResolvedValueOnce(
        mockResponse({ success: true })
      );

      await client.submitFeedback("draft-1", "accepted");

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:5000/api/drafts/draft-1/feedback",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ feedback: "accepted" }),
        })
      );
    });

    it("accepte un commentaire optionnel", async () => {
      mockFetch.mockResolvedValueOnce(
        mockResponse({ success: true })
      );

      await client.submitFeedback("draft-1", "rejected", "Ton trop formel");

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:5000/api/drafts/draft-1/feedback",
        expect.objectContaining({
          body: JSON.stringify({
            feedback: "rejected",
            comment: "Ton trop formel",
          }),
        })
      );
    });
  });

  describe("skipEmail", () => {
    it("ignore un email", async () => {
      mockFetch.mockResolvedValueOnce(
        mockResponse({ success: true })
      );

      const result = await client.skipEmail("email-1");

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:5000/api/emails/email-1/skip",
        expect.objectContaining({ method: "POST" })
      );
      expect(result.success).toBe(true);
    });
  });

  describe("connection-lost cause tagging (audit connectivité 2026-06-13)", () => {
    // The api:connection-lost event now carries the failure cause so
    // useConnectionHealth can tag the Sentry episode event and distinguish
    // backend-down from client-offline. POST is used to bypass the
    // GET-only silent retry and surface the signal on the first failure.
    function captureLostCause(): { value: () => string | undefined; dispose: () => void } {
      let cause: string | undefined
      const onLost = (e: Event) => {
        cause = (e as CustomEvent<{ cause?: string }>).detail?.cause
      }
      window.addEventListener("api:connection-lost", onLost)
      return {
        value: () => cause,
        dispose: () => window.removeEventListener("api:connection-lost", onLost),
      }
    }

    it("tags cause=gateway on a 502 HTML body (Railway edge during deploy)", async () => {
      const captured = captureLostCause()
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 502,
        text: async () => "<html>Bad Gateway</html>",
      })

      await expect(
        client.request("/anything", { method: "POST" })
      ).rejects.toThrow(ApiError)
      expect(captured.value()).toBe("gateway")
      captured.dispose()
    })

    it("tags cause=timeout when the request aborts on the client deadline", async () => {
      const captured = captureLostCause()
      mockFetch.mockRejectedValueOnce(
        Object.assign(new Error("aborted"), { name: "AbortError" })
      )

      await expect(
        client.request("/anything", { method: "POST" })
      ).rejects.toThrow("Request timeout")
      expect(captured.value()).toBe("timeout")
      captured.dispose()
    })

    it("tags cause=network on a connectivity TypeError", async () => {
      const captured = captureLostCause()
      mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"))

      await expect(
        client.request("/anything", { method: "POST" })
      ).rejects.toThrow("Failed to fetch")
      expect(captured.value()).toBe("network")
      captured.dispose()
    })
  })

  describe("network-error retry (audit 2026-05-18)", () => {
    it("retries a GET once when fetch throws TypeError 'Failed to fetch'", async () => {
      // First call simulates the brief Railway-edge blip (CORS-blocked → TypeError).
      mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
      // Second call succeeds.
      mockFetch.mockResolvedValueOnce(
        mockResponse({ status: "healthy", version: "1.0.0", services: {}, timestamp: "" })
      );

      const result = await client.health();
      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(result.status).toBe("healthy");
    });

    it("does NOT retry on TypeError when method is POST (idempotency)", async () => {
      mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
      await expect(
        client.skipEmail("email-1"),
      ).rejects.toThrow(/failed to fetch/i);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it("gives up after one retry", async () => {
      mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
      mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
      await expect(client.health()).rejects.toThrow(/failed to fetch/i);
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });

  describe("passive request deduplication", () => {
    it("shares concurrent listPendingDrafts calls for the same limit", async () => {
      let resolveFetch: (value: ReturnType<typeof mockResponse>) => void = () => {};
      mockFetch.mockReturnValueOnce(
        new Promise((resolve) => {
          resolveFetch = resolve;
        })
      );

      const first = client.listPendingDrafts(100);
      const second = client.listPendingDrafts(100);

      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:5000/api/pending-drafts?limit=100",
        expect.anything()
      );

      resolveFetch(mockResponse({ count: 0, pending_count: 0, drafts: [] }));
      const [firstResult, secondResult] = await Promise.all([first, second]);

      expect(firstResult.drafts).toEqual([]);
      expect(secondResult.drafts).toEqual([]);

      mockFetch.mockResolvedValueOnce(
        mockResponse({ count: 1, pending_count: 1, drafts: [{ id: "next" }] })
      );

      await client.listPendingDrafts(100);
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });
});

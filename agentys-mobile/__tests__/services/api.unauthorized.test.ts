/**
 * Politique 401 (#1121) : un 401 isolé ne purge plus le token — l'invalidité
 * doit être confirmée par un probe GET /api/auth/me. Erreur réseau ou réponse
 * non-401 du probe ⇒ bénéfice du doute, token conservé.
 */

import * as SecureStore from "expo-secure-store";
import { getDrafts } from "../../src/services/api";

const mockFetch = global.fetch as jest.Mock;

function apiResponse(status: number, data: unknown = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: jest.fn().mockResolvedValue(data),
  };
}

function probeCalls(): number {
  return mockFetch.mock.calls.filter(([url]) =>
    String(url).includes("/api/auth/me")
  ).length;
}

beforeEach(() => {
  jest.clearAllMocks();
  (SecureStore.getItemAsync as jest.Mock).mockResolvedValue("jwt-abc");
});

describe("401 → confirmation avant purge", () => {
  it("401 + probe 200 → token CONSERVÉ, erreur propagée", async () => {
    mockFetch.mockResolvedValueOnce(apiResponse(401)); // l'appel API
    mockFetch.mockResolvedValueOnce(apiResponse(200)); // le probe /api/auth/me

    await expect(getDrafts()).rejects.toThrow("Unauthorized");

    expect(probeCalls()).toBe(1);
    expect(SecureStore.deleteItemAsync).not.toHaveBeenCalled();
  });

  it("401 + probe 401 → token purgé une seule fois", async () => {
    mockFetch.mockResolvedValueOnce(apiResponse(401));
    mockFetch.mockResolvedValueOnce(apiResponse(401));

    await expect(getDrafts()).rejects.toThrow("Unauthorized");

    expect(probeCalls()).toBe(1);
    expect(SecureStore.deleteItemAsync).toHaveBeenCalledTimes(1);
    expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith("agentys_auth_token");
  });

  it("401 + probe en erreur réseau → token CONSERVÉ (bénéfice du doute hors ligne)", async () => {
    mockFetch.mockResolvedValueOnce(apiResponse(401));
    mockFetch.mockRejectedValueOnce(new TypeError("Network request failed"));

    await expect(getDrafts()).rejects.toThrow("Unauthorized");

    expect(SecureStore.deleteItemAsync).not.toHaveBeenCalled();
  });

  it("401 + probe 5xx → token CONSERVÉ (le backend est malade, pas le token)", async () => {
    mockFetch.mockResolvedValueOnce(apiResponse(401));
    mockFetch.mockResolvedValueOnce(apiResponse(503));

    await expect(getDrafts()).rejects.toThrow("Unauthorized");

    expect(SecureStore.deleteItemAsync).not.toHaveBeenCalled();
  });

  it("deux 401 concurrents → un SEUL probe partagé", async () => {
    mockFetch
      .mockResolvedValueOnce(apiResponse(401))
      .mockResolvedValueOnce(apiResponse(401))
      .mockResolvedValueOnce(apiResponse(401)); // probe unique

    const [a, b] = await Promise.allSettled([getDrafts(), getDrafts()]);

    expect(a.status).toBe("rejected");
    expect(b.status).toBe("rejected");
    expect(probeCalls()).toBe(1);
    expect(SecureStore.deleteItemAsync).toHaveBeenCalledTimes(2); // 1 par chemin 401, purge idempotente
  });

  it("le probe part avec le token courant en Authorization", async () => {
    mockFetch.mockResolvedValueOnce(apiResponse(401));
    mockFetch.mockResolvedValueOnce(apiResponse(200));

    await expect(getDrafts()).rejects.toThrow("Unauthorized");

    const probe = mockFetch.mock.calls.find(([url]) =>
      String(url).includes("/api/auth/me")
    );
    expect(probe?.[1]?.headers).toEqual({ Authorization: "Bearer jwt-abc" });
  });
});

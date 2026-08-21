import { Readable } from "node:stream";
import { beforeEach, describe, expect, it, vi } from "vitest";
import handler, { isAllowedEnvelope, parseSentryDsn } from "./sentry-tunnel.js";

const TEST_DSN = "https://public-key@example.ingest.sentry.io/12345";

function makeEnvelope(dsn = TEST_DSN) {
  return Buffer.from(`${JSON.stringify({ dsn })}\n${JSON.stringify({ type: "event" })}\n{}\n`);
}

function makeReq(method, body = makeEnvelope()) {
  const req = Readable.from([body]);
  req.method = method;
  return req;
}

function makeRes() {
  return {
    body: undefined,
    headers: {},
    jsonBody: undefined,
    statusCode: 200,
    setHeader(key, value) {
      this.headers[key.toLowerCase()] = value;
    },
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(payload) {
      this.jsonBody = payload;
      this.body = JSON.stringify(payload);
      return this;
    },
    send(payload) {
      this.body = payload;
      return this;
    },
  };
}

describe("api/sentry-tunnel", () => {
  beforeEach(() => {
    process.env.VITE_SENTRY_DSN = TEST_DSN;
    delete process.env.SENTRY_DSN;
    vi.restoreAllMocks();
  });

  it("valide le DSN public configuré", () => {
    expect(parseSentryDsn(TEST_DSN)).toEqual({
      host: "example.ingest.sentry.io",
      projectId: "12345",
      publicKey: "public-key",
    });
  });

  it("accepte uniquement les envelopes du projet configuré", () => {
    const expectedDsn = parseSentryDsn(TEST_DSN);
    expect(isAllowedEnvelope(makeEnvelope(), expectedDsn)).toBe(true);
    expect(
      isAllowedEnvelope(makeEnvelope("https://public-key@example.ingest.sentry.io/99999"), expectedDsn),
    ).toBe(false);
  });

  it("forward l'envelope vers Sentry sans exposer le host ingest au navigateur", async () => {
    const fetchMock = vi.fn(async () => ({
      status: 200,
      text: async () => "ok",
    }));
    vi.stubGlobal("fetch", fetchMock);

    const res = makeRes();
    await handler(makeReq("POST"), res);

    expect(res.statusCode).toBe(200);
    expect(res.body).toBe("ok");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.ingest.sentry.io/api/12345/envelope/",
      expect.objectContaining({
        method: "POST",
        headers: { "content-type": "application/x-sentry-envelope" },
      }),
    );
  });

  it("refuse les envelopes d'un autre projet", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = makeRes();
    await handler(makeReq("POST", makeEnvelope("https://public-key@example.ingest.sentry.io/99999")), res);

    expect(res.statusCode).toBe(403);
    expect(res.jsonBody).toEqual({ error: "forbidden_sentry_dsn" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuse les méthodes non-POST", async () => {
    const res = makeRes();
    await handler(makeReq("GET"), res);

    expect(res.statusCode).toBe(405);
    expect(res.headers.allow).toBe("POST");
  });
});

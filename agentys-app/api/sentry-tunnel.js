const MAX_ENVELOPE_BYTES = 1_000_000;

function parseSentryDsn(rawDsn) {
  const dsn = new URL(rawDsn);
  const projectId = dsn.pathname.replace(/^\/+|\/+$/g, "");

  if (dsn.protocol !== "https:" || !dsn.username || !dsn.host || !projectId) {
    throw new Error("invalid_sentry_dsn");
  }

  return {
    host: dsn.host,
    projectId,
    publicKey: dsn.username,
  };
}

function getConfiguredDsn() {
  const rawDsn = process.env.VITE_SENTRY_DSN || process.env.SENTRY_DSN || "";
  if (!rawDsn) return null;

  try {
    return parseSentryDsn(rawDsn);
  } catch {
    return null;
  }
}

function getEnvelopeDsn(envelope) {
  const firstNewline = envelope.indexOf(10);
  const headerLine = (firstNewline === -1 ? envelope : envelope.subarray(0, firstNewline)).toString("utf8");
  const header = JSON.parse(headerLine);

  if (typeof header.dsn !== "string") {
    throw new Error("missing_envelope_dsn");
  }

  return parseSentryDsn(header.dsn);
}

function isAllowedEnvelope(envelope, expectedDsn) {
  try {
    const envelopeDsn = getEnvelopeDsn(envelope);
    return (
      envelopeDsn.host === expectedDsn.host &&
      envelopeDsn.projectId === expectedDsn.projectId &&
      envelopeDsn.publicKey === expectedDsn.publicKey
    );
  } catch {
    return false;
  }
}

async function readRequestBody(req) {
  const chunks = [];
  let totalBytes = 0;

  for await (const chunk of req) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    totalBytes += buffer.byteLength;

    if (totalBytes > MAX_ENVELOPE_BYTES) {
      const error = new Error("envelope_too_large");
      error.statusCode = 413;
      throw error;
    }

    chunks.push(buffer);
  }

  return Buffer.concat(chunks, totalBytes);
}

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const expectedDsn = getConfiguredDsn();
  if (!expectedDsn) {
    return res.status(503).json({ error: "sentry_tunnel_not_configured" });
  }

  let envelope;
  try {
    envelope = await readRequestBody(req);
  } catch (error) {
    return res.status(error.statusCode || 400).json({ error: error.message || "invalid_envelope" });
  }

  if (!isAllowedEnvelope(envelope, expectedDsn)) {
    return res.status(403).json({ error: "forbidden_sentry_dsn" });
  }

  try {
    const sentryResponse = await fetch(
      `https://${expectedDsn.host}/api/${expectedDsn.projectId}/envelope/`,
      {
        method: "POST",
        headers: {
          "content-type": "application/x-sentry-envelope",
        },
        body: envelope,
      },
    );

    const body = await sentryResponse.text();
    res.setHeader("cache-control", "no-store");
    return res.status(sentryResponse.status).send(body);
  } catch {
    return res.status(502).json({ error: "sentry_forward_failed" });
  }
}

export {
  getConfiguredDsn,
  getEnvelopeDsn,
  isAllowedEnvelope,
  parseSentryDsn,
  readRequestBody,
};

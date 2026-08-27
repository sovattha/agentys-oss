# Agentys

**An AI assistant that drafts your email replies in your own writing voice.**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)

Agentys connects to your Gmail, Outlook, or IMAP mailbox, classifies what arrives,
and prepares reply drafts that wait for your review before anything is sent.

Sending is manual by default. The one exception is the FAQ auto-reply agent, which
can answer known questions on its own — it is opt-in and ships disabled
(`FAQ_AUTO_REPLY_ENABLED=false`, see `app/config.py`). Turn it on deliberately or
not at all.

> **Status.** Agentys grew as a single-maintainer product before being opened up.
> It works and is covered by a large test suite, but expect rough edges in setup
> and French-language comments throughout the source.

---

## How it works

Two agents in a loop. A **Drafter** writes a reply; a **Critic** scores it against
your writing style and the thread context. If the Critic rejects, the Drafter tries
again with the feedback. Only a draft that passes reaches your inbox.

```
┌──────────────────────────────────────────────────────────┐
│  Desktop app (Tauri + React)          localhost:1420     │
│  Mobile app  (React Native / Expo)                       │
└───────────────┬──────────────────────┬───────────────────┘
                │ HTTP /api/*          │ WebSocket (Socket.IO)
                ▼                      ▼
┌──────────────────────────────────────────────────────────┐
│  Backend (Python / Flask)             localhost:5050     │
├──────────────────────────────────────────────────────────┤
│  Drafter ──► Critic ──[accepted]──► draft awaiting you   │
│      ▲            │                                       │
│      └──[rejected]┘                                       │
├──────────────────────────────────────────────────────────┤
│  Sync · Classification · Recap · Reminders · Learning    │
└───────────────┬──────────────────────────────────────────┘
                ▼
     Gmail API · Microsoft Graph · IMAP/SMTP
```

**Mail providers:** Gmail, Outlook (Microsoft Graph), generic IMAP/SMTP.
**LLM providers:** Anthropic Claude (default), OpenAI, or Ollama for local models.
**Storage:** SQLite (encrypted via SQLCipher) locally, PostgreSQL when deployed.

---

## Quick start

### Requirements

- Python 3.11
- Node.js 20+ with Yarn 4 (the desktop app uses Yarn Berry, vendored in-repo)
- Rust toolchain — only if you want to build the native Tauri window
- An API key for your chosen LLM provider, or a local Ollama install

### Backend

```bash
git clone https://github.com/<your-org>/agentys.git
cd agentys

python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env       # then fill in the values below
python run_api.py          # serves on http://localhost:5050
```

The minimum viable `.env` is smaller than the example file suggests. To boot with
Claude and a generic IMAP mailbox you need:

```bash
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...

EMAIL_PROVIDER_TYPE=IMAP_SMTP
IMAP_HOST=imap.example.com
IMAP_USER=you@example.com
IMAP_PASSWORD=...
SMTP_HOST=smtp.example.com
SMTP_USER=you@example.com
SMTP_PASSWORD=...
```

Gmail and Outlook use OAuth instead and need an app registration on the provider
side — see [`.env.example`](.env.example), which documents all 113 settings with
their defaults.

### Desktop app

```bash
cd agentys-app
yarn install
yarn dev          # browser-based dev server on http://localhost:1420
yarn tauri dev    # same, inside the native window (needs Rust)
```

### Mobile app

```bash
cd agentys-mobile
yarn install
yarn start        # Expo; press i for iOS, a for Android
```

Set your own Expo account and project id in `agentys-mobile/app.json` before
building — the published values are placeholders.

---

## Running your own instance

The repository ships with the original project's deployment settings. If you are
running Agentys yourself rather than contributing to it, change these first —
otherwise your build will still be pointed at someone else's infrastructure:

| File | What to change |
|------|----------------|
| `agentys-mobile/app.json` | `owner` and `extra.eas.projectId` — placeholders, set your own Expo account |
| `agentys-app/src-tauri/tauri.conf.json` | `csp` → `connect-src`, which allowlists the original backend host |
| `agentys-app/vercel.json` | same `connect-src` allowlist for the web build |
| `.env` | OAuth redirect URIs must match what you registered with Google / Microsoft |

## Running the tests

```bash
pytest                                  # full backend suite
pytest tests/api -q                     # one area
cd agentys-app && yarn test             # desktop unit tests
cd agentys-mobile && yarn test          # mobile unit tests
```

Database migrations are managed with Alembic:

```bash
alembic upgrade head
```

---

## Repository layout

| Path | What lives there |
|------|------------------|
| `app/` | Flask backend: API routes, agents, providers, domain logic |
| `app/api/` | HTTP endpoints and WebSocket handlers |
| `app/providers/` | Gmail, Outlook, IMAP/SMTP adapters |
| `app/domain/`, `app/application/` | Entities and use cases (hexagonal-ish layering) |
| `app/prompts/` | Prompt construction for the Drafter and Critic |
| `agentys-app/` | Tauri + React desktop client |
| `agentys-mobile/` | React Native / Expo mobile client |
| `tests/` | Backend test suite |
| `scripts/` | Maintenance, evaluation, and migration scripts |
| `docs/` | Architecture notes, ADRs, runbooks |

---

## A note on the code

This codebase was written quickly and in the open only after the fact. Two things
are worth saying plainly rather than letting you discover them:

- **Comments and docstrings are largely in French.** The identifiers are English.
- **A few modules are far too large.** `app/api/routes_emails.py` is over 10,000
  lines and `app/smart_routing.py` over 8,000. Both are on the refactoring list;
  neither is a good place to start reading.

Good entry points instead: `app/domain/`, `app/application/`, and the tests, which
double as the most reliable documentation of intended behaviour.

---

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow
and [SECURITY.md](SECURITY.md) for reporting vulnerabilities privately.

---

## Contributors

- Alexandre Sauvageau

---

## License

Agentys is released under the **GNU Affero General Public License v3.0 or later**.

In short: you may use, study, modify, and redistribute it. If you run a modified
version as a network service, the AGPL requires you to offer that modified source
to its users. See [LICENSE](LICENSE) for the full text.

"Agentys" and its logo are not covered by the AGPL grant; please use your own name
and branding for redistributed builds.

### Commercial licensing

The AGPL requires anyone running a modified Agentys as a network service to
publish their modifications. If that does not work for your organisation, a
commercial license is available that lifts the source-sharing obligation.
Contact the maintainers at the address in [SECURITY.md](SECURITY.md).

This dual-licensing is possible because contributors accept the
[CLA](CLA.md), which keeps the copyright consolidated with the maintainers.

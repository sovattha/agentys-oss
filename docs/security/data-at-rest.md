# Data at Rest — SQLCipher (Tauri) + PostgreSQL (Railway) (CASA V6.2 / V7)

## Status (as of 2026-05-16)

- **Local desktop installs (Tauri)** — SQLite encrypted via SQLCipher 3.51.1, key stored in OS Keychain (macOS Keychain / Windows Credential Manager / Linux Secret Service). Code path: `app/db/encryption.py` + `app/db/database.py`.
- **Railway production backend** — **PostgreSQL 18** on Railway managed Postgres (AWS RDS, EBS AES-256 at the volume level). On top of the volume-level encryption, sensitive columns use application-layer Fernet encryption via the `EncryptedString` SQLAlchemy `TypeDecorator` (`app/db/types/encrypted.py`). The Fernet key is held in Railway env var `OAUTH_TOKEN_ENCRYPTION_KEY`.
- **Email content policy** — the cloud backend runs `AGENTYS_EMAIL_CONTENT_STORAGE_MODE=metadata_only` by default. Email bodies, HTML, long snippets, attachment contents and raw free-form headers are provider-fetched only when needed, processed in memory, and not persisted in PostgreSQL, files, logs or Sentry. Durable cloud storage is limited to metadata and minimized AI artifacts described in [`email-data-inventory.md`](email-data-inventory.md).
- **AI Team containers (Hetzner)** — out of scope (no PII storage on Hetzner; the workers operate on issue/PR metadata only).

> Historical note: the production backend was originally SQLite+SQLCipher (issue #206, migration on 2026-04-29). It was migrated to PostgreSQL in commit `8433eafd` (May 2026). The SQLCipher details below remain accurate for the desktop / Tauri code path.

## Data classification

| Class | Examples | Storage protection |
|---|---|---|
| **HIGH** | Google / Microsoft OAuth `access_token` and `refresh_token` | Application-layer **Fernet** (AES-128-CBC + HMAC-SHA256) on the `accounts` table columns (`app/db/types/encrypted.py`). Also held in `oauth_tokens.json` on the persistent Railway volume, Fernet-encrypted with the same key. |
| **HIGH** | Third-party API keys (Anthropic, OpenAI, Google Cloud, etc.) | Stored only as Railway environment variables; never persisted in the database; never written to logs (per-pattern redaction in `app/api/app.py`). |
| **HIGH** | Magic-link tokens (auth bootstrap) | 256-bit random tokens (`secrets.token_urlsafe(32)`), held in-memory only, TTL 10 minutes (`MAGIC_LINK_TTL` in `app/api/auth.py`), single-use enforced by `dict.pop()` on first successful verification. Never persisted. |
| **MEDIUM** | Email metadata PII (sender / recipient addresses, subjects, provider IDs, thread IDs, labels, folder/read/starred state, attachment presence/count/type) | Stored in PostgreSQL behind Railway-managed at-rest encryption and covered by account-scoped deletion/export. Subjects and addresses are still personal data and must not be logged in full. |
| **HIGH** | Email content (body text, body HTML, long snippets, attachment contents, attachment filenames, raw free-form headers) | Not stored in Agentys Cloud by default. Provider-fetched on demand and processed in memory only. Historical rows are purged by migration `030_purge_email_content_cache` and retention scripts. |
| **LOW** | System events (audit log, sync status, scheduler ticks, request counters) | Plaintext storage acceptable — no PII, no secrets, used for observability and debugging. |

Protection level drives both storage policy and log policy. A control change for any HIGH item requires updating both `data-at-rest.md` (this file), [`email-data-inventory.md`](email-data-inventory.md), and the redaction patterns in `app/api/app.py`.

## Email content retention boundary

Agentys Cloud is not an email archive. In `metadata_only` mode:

- Gmail / Outlook bodies are fetched only for immediate user-facing actions:
  opening an email, generating a draft, onboarding/style analysis, labels or
  provider search fallback.
- The request/job may pass content to the configured AI provider, but the
  backend keeps only minimized outputs: style profile, abstract rules, labels,
  draft state, token counts and operational status.
- `body_text`, `body_html`, unrestricted `snippet`, attachment content,
  free-form draft prompts, draft critiques and raw example text are not written
  to durable cloud storage.
- Logs, Sentry events and text log retention must scrub known email-content
  fields before data leaves the process.
- A future full-content cloud cache requires a new ADR, explicit opt-in,
  retention period, export/delete coverage and updated privacy disclosures.



## Architecture warning — legacy SQLite layers still exist

Railway production no longer uses SQLite for the main SQLAlchemy database: it
must boot with `DATABASE_URL` and will fail closed otherwise. SQLite/SQLCipher
still exists for local/desktop installs and for historical migration tooling.

There are two SQLite connection layers that can target the same desktop or
historical migration file (`~/.agentys/data/agentys.db` on desktop, formerly
`/data/agentys/agentys.db` on Railway before the Postgres migration):

1. **`app/db/database.py`** — the SQLAlchemy engine. SQLCipher-aware since 2026-02. Used by everything that goes through the ORM (most of the read/write traffic).
2. **`app/infrastructure/database.py`** — a legacy direct-`sqlite3` `Database` class. Used by `TaskRepository`, `draft_history`, `processed_emails`, `sender_reputation`, `learned_patterns`, `prompt_adjustments`. Instantiated as a **module-level singleton** (`db = Database()` at the bottom of the file), which means the connection is opened during `app/api/__init__.py` import.

Both layers must agree on the SQLite module choice. If only the SQLAlchemy layer is SQLCipher-aware and the legacy layer keeps using stdlib `sqlite3`, then setting `AGENTYS_ENCRYPTION_KEY` on a now-encrypted file produces an immediate boot crash (`sqlite3.DatabaseError: file is not a database`) coming from `_get_connection()` running `PRAGMA journal_mode = WAL` straight away.

The fix that landed alongside the migration (commit `d0357984`) makes `app/infrastructure/database.py` honour the same env var: when `AGENTYS_ENCRYPTION_KEY` is set, it imports `sqlcipher3.dbapi2` (API-compatible with stdlib sqlite3) and applies the same PRAGMA stack. Any future sqlite layer added against `agentys.db` must do the same — see `_resolve_sqlite_module()` and `_apply_encryption_pragmas()` in that file as the reference.

Future cleanup (TODO, not blocking #206): hoist the PRAGMA stack and module-resolution helper into a shared `app/db/cipher.py` so all three callsites (db/database.py, infrastructure/database.py, scripts/encrypt_existing_db.py) consume one definition.

## How it works

`app/db/encryption.py:get_encryption_key()` retrieves the key in this order:

1. `AGENTYS_ENCRYPTION_KEY` env var (used in containers)
2. OS Keychain (used on developer machines and end-user installs)

The key is a 32-byte (64 hex char) value. Format validation lives in `_HEX_KEY_RE` and `_validate_hex_key()` — anything else is rejected before it reaches the SQLCipher PRAGMA, which prevents PRAGMA injection.

PRAGMA values applied on every connection (must match the values used at migration time, see below):

| PRAGMA | Value |
|---|---|
| `cipher_page_size` | `4096` |
| `kdf_iter` | `256000` |
| `cipher_hmac_algorithm` | `HMAC_SHA512` |
| `cipher_kdf_algorithm` | `PBKDF2_HMAC_SHA512` |

## One-time migration: plaintext → encrypted (executed 2026-04-29)

The historical Railway DB was plaintext because, before the env-var path was wired up, `get_encryption_key()` only fell back to keychain. Containers don't have a keychain, so the chain returned None → `EncryptionConfig(enabled=False)` → plaintext.

Setting the env var directly on a plaintext DB does **not** auto-migrate. SQLCipher would attempt to decrypt the file header, fail HMAC, and the boot would crash with `WrongKeyError` raised by `app/db/database.py:_create_connection`. The DB has to be re-encrypted out of band first.

### What was done (105 MB DB, ~3s migration)

1. **Generated a random 32-byte hex key** locally with `secrets.token_hex(32)`. Stored in `.encryption-key.local` (gitignored).
2. **Uploaded the migration script** `scripts/encrypt_existing_db.py` to `/tmp/migration/encrypt_existing_db.py` on Railway via base64 over `railway ssh` (a binary tar pipe was less reliable; base64 is small enough at 16 KB).
3. **Uploaded the key file** to `/tmp/migration/key.hex` (mode 0600).
4. **Ran the migration** — produced `/data/agentys/agentys.db.encrypted-staging` from `/data/agentys/agentys.db`. The script:
   - calls `PRAGMA wal_checkpoint(FULL)` to flush the live WAL into the main file,
   - opens plaintext via `sqlcipher3.connect()` with no PRAGMA key (default = plaintext),
   - `ATTACH DATABASE ... AS encrypted KEY "x'<hex>'"`,
   - applies the same SQLCipher PRAGMAs as the runtime,
   - `SELECT sqlcipher_export('encrypted')` — copies every table, index, trigger,
   - re-opens the encrypted file with the key and reports row counts to stdout.
5. **Verified row counts** — 25 tables, 7141 rows, every table matched plaintext exactly.
6. **Atomic file swap** on Railway (still inside `railway ssh`):
   ```
   mv /data/agentys/agentys.db /data/agentys/agentys.db.plaintext-pre-encrypt-<TS>
   rm -f /data/agentys/agentys.db-wal /data/agentys/agentys.db-shm
   mv /data/agentys/agentys.db.encrypted-staging /data/agentys/agentys.db
   ```
   The running container kept its open FDs on the old inode (Linux semantics) — its writes during the swap window land in the orphan file, recoverable from the `.plaintext-pre-encrypt-<TS>` backup if needed.
7. **Set the env var** with `railway variables --set AGENTYS_ENCRYPTION_KEY=<hex>` — this triggered an auto-redeploy. The new container started with the env var set and `database.py` opened the encrypted DB cleanly.

The plaintext backup `agentys.db.plaintext-pre-encrypt-<TS>` is left on the Railway volume for 7 days as a rollback. After that it should be removed (it's plaintext PII — keeping it indefinitely defeats the point of the migration).

## Day-2 operations

### Verifying the production DB is actually encrypted

```bash
railway ssh 'head -c 16 /data/agentys/agentys.db | od -c | head -1'
# OK: starts with random bytes (e.g. ".  364  210  357  …")
# NOT OK: starts with "S Q L i t e   f o r m a t   3"  → plaintext, escalate
```

### Reading the prod DB ad-hoc

The DB is encrypted. To open from `railway ssh`:

```bash
railway ssh 'python3 -c "
import os
from sqlcipher3 import dbapi2 as sqlite
conn = sqlite.connect(\"/data/agentys/agentys.db\")
cur = conn.cursor()
cur.execute(f\"PRAGMA key = \\\"x\\x27{os.environ[\\\"AGENTYS_ENCRYPTION_KEY\\\"]}\\x27\\\"\")
cur.execute(\"PRAGMA cipher_page_size = 4096\")
cur.execute(\"PRAGMA kdf_iter = 256000\")
cur.execute(\"PRAGMA cipher_hmac_algorithm = HMAC_SHA512\")
cur.execute(\"PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512\")
print(cur.execute(\"SELECT count(*) FROM accounts\").fetchone())
"'
```

(The env var is exposed inside the container — no need to type the key.)

### Rotating the key

Rotation is a re-migration: open with the old key, export to a new encrypted file with the new key, swap, set new env var.

```bash
# 1. Generate new key (locally — never commit, never log)
NEW_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# 2. Upload to Railway
railway ssh "echo -n '$NEW_KEY' > /tmp/key-new.hex && chmod 600 /tmp/key-new.hex"

# 3. Run rotation script (re-uses scripts/encrypt_existing_db.py with --plaintext
#    pointing at the existing encrypted DB; sqlcipher_export works the same way
#    when the source has its own key — the export uses the source connection's
#    PRAGMA context). Easier: write a sibling rotate_db_key.py that takes
#    --old-key-file and --new-key-file. (Not yet written; do this when first
#    rotation is actually scheduled.)

# 4. Atomic swap (same pattern as initial migration)

# 5. Set new env var
railway variables --set "AGENTYS_ENCRYPTION_KEY=$NEW_KEY"
```

The Anthropic CASA renewal cadence is annual (cf. CLAUDE.md), so rotating once per year alongside the audit is reasonable. There is no separate annual rotation requirement on the SQLCipher side — only OAuth client secrets and the encryption key tracked here have explicit expirations.

### Recovering from a crash boot ("WrongKeyError" on startup)

If the new container fails to boot with `WrongKeyError`:

1. Check `railway logs --deployment <id>` for the actual error
2. **Most likely cause**: env var got out of sync with the file (e.g., someone removed `AGENTYS_ENCRYPTION_KEY` while the file is encrypted). Fix:
   ```bash
   railway variables --set "AGENTYS_ENCRYPTION_KEY=<correct-key-from-password-manager>"
   ```
3. **If the file itself is corrupted**: roll back to the most recent plaintext backup AND remove the env var:
   ```bash
   railway ssh '
     cp /data/agentys/agentys.db /data/agentys/agentys.db.encrypted-corrupt-$(date +%Y%m%d-%H%M%S)
     cp /data/agentys/agentys.db.plaintext-pre-encrypt-* /data/agentys/agentys.db
     rm -f /data/agentys/agentys.db-wal /data/agentys/agentys.db-shm
   '
   railway variables --remove AGENTYS_ENCRYPTION_KEY
   ```
   This puts the backend back on plaintext (security regression, but service is restored). Then re-run the migration end-to-end.

### Where the key lives

- **Production source of truth**: Railway env var `AGENTYS_ENCRYPTION_KEY` (visible to anyone with project access via `railway variables`)
- **Disaster recovery copy**: developer's password manager (1Password / Bitwarden / etc.) — **must** be saved out-of-band the day the key is generated, otherwise a Railway project-deletion accident is unrecoverable
- **Local dev artifact**: `.encryption-key.local` at repo root, gitignored. Should be deleted from disk after copying into the password manager.

## Why not Fernet / why this PRAGMA stack

- **SQLCipher** is the canonical SQLite-at-rest answer; Fernet would force every read/write to do app-level decrypt and break SQL features (no indexes on encrypted columns, no `LIKE`, etc.).
- **PBKDF2-HMAC-SHA512 + 256k iterations** is the SQLCipher 4 default and matches OWASP ASVS V6.2 expectations. Lower iteration counts (e.g. 64k from SQLCipher 3) would be flagged by CASA.
- **HMAC-SHA512** is also the default and provides per-page integrity, so a flipped bit at rest fails the HMAC check rather than silently returning corrupted data.

## References

- ASVS V6.2.1 — Data at Rest: <https://github.com/OWASP/ASVS/blob/master/4.0/en/0x14-V6-Cryptography.md>
- SQLCipher docs: <https://www.zetetic.net/sqlcipher/>
- `app/db/encryption.py` — runtime key resolution + PRAGMA values
- `app/db/database.py` — `_create_connection()` applies the PRAGMAs and verifies the key on every new connection
- `scripts/encrypt_existing_db.py` — one-shot plaintext → encrypted migration (and basis for future rotation)

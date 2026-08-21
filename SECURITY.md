# Security Policy

Agentys holds OAuth tokens for people's mailboxes and processes their private
correspondence. Security reports are taken seriously and handled privately.

## Reporting a vulnerability

**Do not open a public issue.**

Use GitHub's private vulnerability reporting: go to the **Security** tab of this
repository and choose **Report a vulnerability**. This opens a private advisory
visible only to the maintainers.

Please include:

- what the issue is, and the impact you believe it has
- the steps to reproduce it, or a proof of concept
- the affected version or commit
- any mitigation you have already identified

You can expect an acknowledgement within a few days. Because this is a small
project, please allow reasonable time for a fix before disclosing publicly.

## Scope

The following are in scope:

- authentication and authorisation on the API, including cross-tenant access
- handling and storage of OAuth tokens and credentials
- encryption of the local database and of tokens at rest
- injection of any kind (SQL, prompt, header, template)
- server-side request forgery in the link and unsubscribe handling
- exposure of email content or metadata beyond its owner

The following are **out of scope**:

- findings that require an already-compromised machine or account
- rate limiting on a locally-run instance
- vulnerabilities in third-party dependencies with no exploitable path here
  (report those upstream; tell us if Agentys makes them reachable)

## What Agentys does to protect data

Useful context when assessing a report:

- OAuth tokens are encrypted at rest with Fernet, column-level, in the database
- the local desktop database is encrypted with SQLCipher
- email content retention is deliberately minimal; an audit endpoint verifies the
  metadata-only contract holds
- sending is manual by default; the one automated reply path (FAQ auto-reply) is
  opt-in and disabled by default

If you find any of the above to be untrue, that is itself a valid report.

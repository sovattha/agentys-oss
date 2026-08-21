# Contributing to Agentys

Thanks for taking an interest. This document covers what you need to know before
opening a pull request.

## Before you start

For anything beyond a small fix, **open an issue first**. Agentys came out of a
single-maintainer product and some areas are mid-refactor; a quick conversation
saves you from building on a module that is about to move.

## Setting up

See the Quick start in [README.md](README.md). In short:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
pytest
```

If `pytest` is green on a fresh clone, your environment is good.

## Working on a change

**Write the test first.** Every bug fix should start with a test that reproduces
the bug and fails; every feature with a test that describes the intended
behaviour. The test suite is the most trustworthy documentation this project has,
and it stays that way only if it grows with the code.

**Keep the diff to the change.** Do not reformat, rename, or "clean up" code
adjacent to what you are fixing. Unrelated improvements are welcome, in their own
pull request, where they can be reviewed on their own merits.

**Match the surrounding style.** Comments and docstrings across the codebase are
largely in French; identifiers are English. Follow whichever convention the file
you are editing already uses rather than introducing a third.

Tooling is configured in-repo and should be run before pushing:

```bash
ruff check .        # linting
mypy app            # type checking
pytest              # tests
```

## Handling email data

Agentys processes personal correspondence. Two rules are non-negotiable:

1. **Never commit real email content, addresses, or names.** Test fixtures use
   `example.com`, `example.fr`, and invented identities. If you need new fixture
   data, invent it — do not paste from a real mailbox, including your own.
2. **Never commit screenshots of a real inbox.** Use a throwaway account with
   synthetic data if a screenshot is needed.

`scripts/anonymize_fixtures.py` exists to sanitise captured pipeline data, but
treat it as a safety net, not permission to start from real data.

## Commits and pull requests

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add Fastmail IMAP preset
fix: stop the draft poller from surviving unmount
docs: document the FAQ auto-reply flag
```

Types in use: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

In the pull request, describe what changed and why, and say how you verified it.
"Tests pass" is enough when tests cover the change; otherwise explain what you
exercised by hand.

## Reporting bugs

Use the issue templates. The single most useful thing you can include is a
reliable way to reproduce the problem — the versions, the provider (Gmail /
Outlook / IMAP), and what you expected instead.

## Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the
AGPL-3.0-or-later, the same license as the project.

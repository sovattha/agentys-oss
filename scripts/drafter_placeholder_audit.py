#!/usr/bin/env python
"""Measure how often the current Drafter emits `[À confirmer]` placeholders.

Audit 2026-05-04 — root-cause analysis : the 60-case ground-truth eval
showed 13/15 user-labelled-bad drafts contained placeholders. But those
drafts were generated in April 2026 with Sonnet and a pre-RÈGLE-#5bis
prompt. This script runs the *current* Drafter (Haiku via the same
prompt builder prod uses) on the 60 source emails and reports :

  - placeholder_rate : % of drafts containing any placeholder marker
  - per-persona breakdown
  - per-marker breakdown (which markers leak most)

Cost : 60 Haiku Drafter calls × ~$0.001 = ~$0.06. ~1 min wall at parallel=4.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    pass

import anthropic  # noqa: E402

from app.prompts.builders import (  # noqa: E402
    get_drafter_system_prompt,
    get_drafter_user_prompt,
)

_LABELS_FILE = _REPO / "tasks" / "ground-truth-drafts-2026-05-04.json"
_OUT_JSON = _REPO / "tasks" / "drafter-placeholder-audit-2026-05-04.json"

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 1024  # matches MAX_TOKENS_DRAFT

_PERSONAS = [
    "consultant_intl", "default", "hr_director",
    "lawyer_paris", "sales_director", "startup_ceo",
]

# All known placeholder markers we want to flag in fresh drafts.
_PLACEHOLDER_REGEX = re.compile(
    r"\[(?:À |a |à )?(?:confirmer|valider|v[eé]rifier|pr[eé]ciser)\]|"
    r"\[(?:TBD|REDACTE|placeholder|XXX|TODO|X)\b[^\]]*\]",
    re.IGNORECASE,
)


@dataclass
class DraftSample:
    persona: str
    case_id: str
    email_subject: str
    email_body: str
    draft: str
    has_placeholder: bool
    placeholder_matches: list  # list[str] of the literal markers found
    error: str = ""


def _load_email_index() -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for persona in _PERSONAS:
        fname = "test_emails.json" if persona == "default" else f"test_emails_{persona}.json"
        path = _REPO / "tests" / "fixtures" / fname
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for e in (payload.get("emails") if isinstance(payload, dict) else payload) or []:
            if isinstance(e, dict):
                cid = e.get("id") or e.get("case_id")
                if cid:
                    out[(persona, cid)] = e
    return out


def _generate_one(client, kb: str, persona: str, case_id: str, email: dict) -> DraftSample:
    body = (email.get("body") or email.get("content") or "")
    subject = email.get("subject", "")
    sample = DraftSample(
        persona=persona,
        case_id=case_id,
        email_subject=subject,
        email_body=body[:300],
        draft="",
        has_placeholder=False,
        placeholder_matches=[],
    )
    if not body:
        sample.error = "empty_email_body"
        return sample
    try:
        # Compose the full email content the Drafter would see in prod.
        email_for_drafter = f"Subject: {subject}\n\n{body}"
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=get_drafter_system_prompt(kb),
            messages=[{
                "role": "user",
                "content": get_drafter_user_prompt(email_for_drafter),
            }],
        )
        sample.draft = response.content[0].text if response.content else ""
        matches = _PLACEHOLDER_REGEX.findall(sample.draft)
        sample.has_placeholder = bool(matches)
        sample.placeholder_matches = matches
    except Exception as e:
        sample.error = f"{type(e).__name__}: {e}"
    return sample


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    payload = json.loads(_LABELS_FILE.read_text(encoding="utf-8"))
    labels = [l for l in payload.get("labels", []) if l.get("verdict") in ("good", "bad")]
    if args.limit:
        labels = labels[:args.limit]

    email_index = _load_email_index()
    kb = (_REPO / "knowledge" / "memoire.md").read_text(encoding="utf-8")
    client = anthropic.Anthropic()

    print(f"[start] {len(labels)} fresh drafts via current Drafter prompt", file=sys.stderr)
    samples: list[DraftSample] = []
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futures = {
            ex.submit(_generate_one, client, kb, l["persona"], l["case_id"],
                      email_index.get((l["persona"], l["case_id"]), {})): l
            for l in labels
        }
        for fut in as_completed(futures):
            s = fut.result()
            samples.append(s)
            done = len(samples)
            if done % 10 == 0 or done == len(labels):
                err_n = sum(1 for x in samples if x.error)
                ph_n = sum(1 for x in samples if x.has_placeholder)
                print(f"  {done}/{len(labels)} ({err_n} errors, {ph_n} with placeholders) "
                      f"elapsed={time.time() - t_start:.0f}s", file=sys.stderr)

    successful = [s for s in samples if not s.error]
    n = len(successful)
    ph_n = sum(1 for s in successful if s.has_placeholder)
    rate = (ph_n / n) if n else 0.0

    by_persona: Counter[str] = Counter()
    for s in successful:
        if s.has_placeholder:
            by_persona[s.persona] += 1

    marker_counts: Counter[str] = Counter()
    for s in successful:
        for m in s.placeholder_matches:
            marker_counts[m.lower()] += 1

    print()
    print("=" * 60)
    print(f"Successful drafts: {n}/{len(samples)}")
    print(f"Drafts containing a placeholder: {ph_n}")
    print(f"Placeholder rate: {rate:.1%}")
    print()
    if by_persona:
        print("By persona:")
        for p, k in sorted(by_persona.items(), key=lambda x: -x[1]):
            persona_total = sum(1 for s in successful if s.persona == p)
            print(f"  {p:<18} {k}/{persona_total}")
    if marker_counts:
        print()
        print("Marker frequency:")
        for m, k in marker_counts.most_common(10):
            print(f"  {m:<30} {k}x")
    print("=" * 60)

    _OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    _OUT_JSON.write_text(json.dumps({
        "n_total": len(samples),
        "n_successful": n,
        "placeholder_count": ph_n,
        "placeholder_rate": round(rate, 4),
        "by_persona": dict(by_persona),
        "marker_counts": dict(marker_counts),
        "samples": [asdict(s) for s in samples],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[ok] wrote {_OUT_JSON}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

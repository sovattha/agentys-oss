#!/usr/bin/env python3
"""
Prepare NER benchmark dataset for spaCy evaluation.

Exports emails from the dev database to a CSV for manual annotation.
Used in étape 5 du plan smart-routing-pipeline-refactor.

Usage:
    python scripts/prepare_ner_benchmark.py [--db-path PATH] [--out PATH] [--n-per-category N]

Output format (CSV):
    id, category, sender, subject, body_preview, entities_person, entities_org, entities_loc

Columns `entities_person`, `entities_org`, `entities_loc` are left empty for manual annotation.
Convention : one entity per column, separated by '|' (pipe).

Example annotation:
    entities_person = "Jean Dupont|Marie Martin"
    entities_org    = "SNCF|Ministère du Travail"
    entities_loc    = "Paris|Lyon"

Stratification target:
    - 20 emails per category × 6 categories = 120 emails
    - Categories: factures, rdv, support, internal, spam_like, newsletter
    - If fewer than 20 in a category, export all available

After annotation, run:
    python scripts/benchmark_spacy_ner.py tmp/ner_benchmark/emails.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path


DEFAULT_DB_PATH = Path.home() / "Library" / "Application Support" / "agentys" / "agentys_encrypted.db"
DEFAULT_OUT_PATH = Path("tmp/ner_benchmark/emails.csv")
DEFAULT_N_PER_CATEGORY = 20

# Heuristics de catégorisation par regex (le vrai système d'Agentys est plus sophistiqué
# mais pour un benchmark NER c'est suffisant — le but est la diversité lexicale, pas
# la précision de catégorisation)
CATEGORY_PATTERNS: dict[str, list[str]] = {
    "factures": [
        r"\bfacture\b", r"\binvoice\b", r"\bpayment\b", r"\breçu\b",
        r"\bmontant\b", r"\btva\b", r"\brib\b", r"\biban\b",
    ],
    "rdv": [
        r"\brdv\b", r"\brendez-vous\b", r"\bmeeting\b", r"\bcalendar\b",
        r"\bagenda\b", r"\bdispos\b", r"\bcreneau\b",
    ],
    "support": [
        r"\bsupport\b", r"\bticket\b", r"\bproblème\b", r"\bissue\b",
        r"\bbug\b", r"\berreur\b", r"\bhelp\b", r"\bassist\b",
    ],
    "internal": [
        r"\bteam\b", r"\béquipe\b", r"\bréunion\b", r"\bsprint\b",
        r"\bprojet\b", r"\bproject\b", r"\bcollègue\b",
    ],
    "spam_like": [
        r"\bpromo\b", r"\bdiscount\b", r"\bwin\b", r"\bgagne\b",
        r"\bgratuit\b", r"\bfree\b", r"\b%\s?off\b", r"\bsoldes\b",
    ],
    "newsletter": [
        r"\bnewsletter\b", r"\bunsubscribe\b", r"\bse désabonner\b",
        r"\bwebinar\b", r"\bdigest\b", r"\babonné\b",
    ],
}


def classify_email(subject: str, body: str) -> str:
    """Simple heuristic classifier for benchmark stratification."""
    text = f"{subject} {body}".lower()
    for category, patterns in CATEGORY_PATTERNS.items():
        if any(re.search(p, text, re.IGNORECASE) for p in patterns):
            return category
    return "other"


def truncate_preview(body: str, max_chars: int = 500) -> str:
    """Truncate body for CSV preview. Full body reconstructible from DB via id."""
    if len(body) <= max_chars:
        return body
    return body[:max_chars] + "..."


def strip_newlines(text: str) -> str:
    """CSV-safe: remove newlines which break csv.writer in some configurations."""
    return text.replace("\r", " ").replace("\n", " ").strip()


def load_emails(db_path: Path, limit_per_category: int) -> list[dict]:
    """Query emails from the Agentys SQLite database, stratified by category."""
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. "
            "Run Agentys once to populate, or specify --db-path."
        )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Schema check: minimum required columns (supporte `body` ou `body_text`)
    cursor = conn.execute("PRAGMA table_info(emails)")
    columns = {row["name"] for row in cursor.fetchall()}
    body_col = "body_text" if "body_text" in columns else "body"
    required = {"id", "subject", body_col, "sender"}
    missing = required - columns
    if missing:
        raise RuntimeError(
            f"Emails table missing columns: {missing}. Available: {sorted(columns)}"
        )

    # Pull a generous sample, we'll stratify in Python
    query = f"""
        SELECT id, subject, {body_col} AS body, sender
        FROM emails
        WHERE {body_col} IS NOT NULL AND length({body_col}) > 50
        ORDER BY RANDOM()
        LIMIT 2000
    """
    rows = list(conn.execute(query))
    conn.close()

    # Classify + stratify
    by_category: dict[str, list[dict]] = {cat: [] for cat in CATEGORY_PATTERNS}
    by_category["other"] = []

    for row in rows:
        subject = row["subject"] or ""
        body = row["body"] or ""
        category = classify_email(subject, body)
        if len(by_category[category]) < limit_per_category:
            by_category[category].append({
                "id": row["id"],
                "category": category,
                "sender": row["sender"] or "",
                "subject": subject,
                "body_preview": truncate_preview(body),
            })

    # Flatten, skip "other" (focus on 6 known categories)
    result: list[dict] = []
    for category in CATEGORY_PATTERNS:
        bucket = by_category[category]
        if len(bucket) < limit_per_category:
            print(
                f"[WARN] Category '{category}': {len(bucket)}/{limit_per_category} emails",
                file=sys.stderr,
            )
        result.extend(bucket)

    return result


def write_csv(emails: list[dict], out_path: Path) -> None:
    """Write the CSV with annotation columns left empty."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id",
        "category",
        "sender",
        "subject",
        "body_preview",
        "entities_person",  # annotated by user
        "entities_org",     # annotated by user
        "entities_loc",     # annotated by user
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for email in emails:
            writer.writerow({
                "id": email["id"],
                "category": email["category"],
                "sender": strip_newlines(email["sender"]),
                "subject": strip_newlines(email["subject"]),
                "body_preview": strip_newlines(email["body_preview"]),
                "entities_person": "",
                "entities_org": "",
                "entities_loc": "",
            })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH,
                        help=f"Path to Agentys SQLite DB (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH,
                        help=f"Output CSV path (default: {DEFAULT_OUT_PATH})")
    parser.add_argument("--n-per-category", type=int, default=DEFAULT_N_PER_CATEGORY,
                        help=f"Emails per category (default: {DEFAULT_N_PER_CATEGORY})")
    args = parser.parse_args()

    try:
        emails = load_emails(args.db_path, args.n_per_category)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if not emails:
        print("[ERROR] No emails matched the criteria.", file=sys.stderr)
        return 1

    write_csv(emails, args.out)

    total = len(emails)
    by_cat: dict[str, int] = {}
    for email in emails:
        by_cat[email["category"]] = by_cat.get(email["category"], 0) + 1

    print(f"Exported {total} emails to {args.out}")
    print("Distribution par catégorie :")
    for category in CATEGORY_PATTERNS:
        count = by_cat.get(category, 0)
        marker = "OK " if count >= args.n_per_category else "!! "
        print(f"  {marker}{category:15s} {count:3d}/{args.n_per_category}")

    print()
    print("Next step: open the CSV and fill the 3 `entities_*` columns manually.")
    print("Convention: entities separated by '|', e.g. entities_person='Jean Dupont|Marie Martin'")
    print("After annotation, run: python scripts/benchmark_spacy_ner.py", args.out)

    return 0


if __name__ == "__main__":
    sys.exit(main())

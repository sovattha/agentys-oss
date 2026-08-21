"""Reclassify retroactively tous les emails de la boite inbox d'un compte.

Utilise le pipeline de règles (LabelEmailUseCase.execute) sans appeler le LLM
— donc gratuit. Les emails dont les règles ne tranchent pas gardent leur label.

Usage (sur Railway) :
    railway ssh 'python3 /tmp/reclassify.py 5 [--dry-run]'

Arguments :
    account_id (int) — ex: 5
    --dry-run (flag) — simule sans écrire

Output : count avant/après + changements par transition (ex: FYI→Noise: 88).
"""
import os
import re
import sqlite3
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone

# Force AGENTYS_DB_PATH (stable) avant d'importer l'app
os.environ.setdefault("AGENTYS_DB_PATH", "/data/agentys/agentys.db")
os.environ.setdefault("AGENTYS_ENCRYPTION_ENABLED", "false")

sys.path.insert(0, "/app")


class NullLLM:
    """LLM stub — returns empty so execute() falls through to rules-only."""

    def generate(self, *args, **kwargs):
        return ""


def parse_args():
    args = sys.argv[1:]
    account_id = 5
    dry_run = False
    for a in args:
        if a == "--dry-run":
            dry_run = True
        elif a.lstrip("-").isdigit():
            account_id = int(a)
    return account_id, dry_run


def main():
    account_id, dry_run = parse_args()
    print(f"[reclassify] account_id={account_id} dry_run={dry_run}")

    from app.domain.entities import Email
    from app.application.label_email import LabelEmailUseCase

    # Account email (needed for CC detection and user_email param)
    conn = sqlite3.connect(os.environ["AGENTYS_DB_PATH"])
    c = conn.cursor()
    user_email_row = c.execute(
        "SELECT email FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if not user_email_row:
        print(f"[reclassify] account {account_id} not found")
        return
    user_email = user_email_row[0]
    print(f"[reclassify] user_email={user_email}")

    # Fetch contact real-contact state (bidirectional for P1)
    contacts_bidir = set()
    for addr, sent_cnt, recv_cnt in c.execute(
        "SELECT email, sent_count, received_count FROM contacts WHERE account_id = ?",
        (account_id,),
    ).fetchall():
        if (sent_cnt or 0) > 0 and (recv_cnt or 0) > 0:
            contacts_bidir.add((addr or "").lower())
    print(f"[reclassify] bidir contacts: {len(contacts_bidir)}")

    # Fetch inbox emails + current label
    rows = c.execute(
        """
        SELECT e.id, e.email_id, e.thread_id, e.sender, e.sender_name,
               e.subject, e.body_text, e.recipients, e.cc, e.date,
               el.label_name
        FROM emails e
        LEFT JOIN email_labels el
          ON el.email_id = e.email_id AND el.account_id = e.account_id
        WHERE e.account_id = ? AND e.folder = 'inbox'
        ORDER BY e.date DESC
        """,
        (account_id,),
    ).fetchall()
    print(f"[reclassify] inbox rows: {len(rows)}")

    # Instantiate use case with null LLM
    use_case = LabelEmailUseCase(
        llm=NullLLM(),
        labels=[],
        rules=[],
        user_email=user_email,
    )

    transitions = Counter()
    changes = []  # (email_id, old, new, sender, subject)
    errors = 0

    for (
        pk, email_id, thread_id, sender, sender_name,
        subject, body_text, recipients, cc, date, current_label,
    ) in rows:
        try:
            # Build Email domain entity
            received = datetime.now(timezone.utc)
            if date:
                try:
                    received = datetime.fromisoformat(date.replace(" ", "T"))
                    if received.tzinfo is None:
                        received = received.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            # Extract exact sender address for real-contact lookup
            s = (sender or "").strip().lower()
            m = re.search(r"<([^>]+)>", s)
            addr = m.group(1) if m else s
            is_real_contact = addr in contacts_bidir

            email = Email(
                id=email_id,
                sender=sender or "",
                subject=subject or "",
                body=body_text or "",
                received_at=received,
                thread_id=thread_id,
            )

            raw_meta = {
                "classification_headers": {},  # headers not stored in DB
                "sender_is_real_contact": is_real_contact,
            }

            result = use_case.execute(email, raw_metadata=raw_meta)
            new_label = result.default_label or "Unlabeled"
            new_conf = result.confidences.get(new_label, 0.0) if hasattr(result, "confidences") else 0.0

            old = current_label or "Unlabeled"
            if new_label != old:
                transitions[f"{old}→{new_label} (conf={new_conf:.2f})"] += 1
                # Allowed transitions — conservative :
                # - Unlabeled → anything (nothing to lose)
                # - * → Noise (P1 target, even conf < 0.85)
                # - FYI → Action when conf >= 0.85 (P3 target : questions)
                # - Noise → Action when conf >= 0.90 (P4 target : codes 2FA/
                #   verification mis-classés en Noise parce que sender noreply).
                allow = False
                if old == "Unlabeled":
                    allow = True
                elif new_label == "Noise":
                    allow = True
                elif old == "FYI" and new_label == "Action" and new_conf >= 0.85:
                    allow = True
                elif old == "Noise" and new_label == "Action" and new_conf >= 0.90:
                    allow = True
                if not allow:
                    continue
                changes.append((email_id, old, new_label, sender, subject))
        except Exception as exc:
            errors += 1
            if errors <= 5:
                print(f"[reclassify] error on {email_id}: {exc}")
                traceback.print_exc()

    print()
    print(f"=== Reclass terminé — {len(changes)} changements / {len(rows)} emails ({errors} erreurs) ===")
    print()
    print("## Transitions")
    for t, n in transitions.most_common():
        print(f"  {t:30s} {n:4d}")

    print()
    print("## Sample changes (top 20)")
    for email_id, old, new, sender, subject in changes[:20]:
        sender_short = (sender or "")[:40]
        subj_short = (subject or "")[:60]
        print(f"  [{old}→{new}] {sender_short:40s} | {subj_short}")

    if dry_run:
        print()
        print("[DRY RUN] No DB writes performed.")
        return

    # Apply changes
    print()
    print(f"[reclassify] writing {len(changes)} updates to email_labels...")
    for email_id, old, new, sender, subject in changes:
        if old == "Unlabeled":
            # INSERT
            c.execute(
                "INSERT OR IGNORE INTO email_labels (email_id, account_id, label_name) VALUES (?, ?, ?)",
                (email_id, account_id, new),
            )
        else:
            # UPDATE the existing row (there's typically only one default label per email)
            c.execute(
                "UPDATE email_labels SET label_name = ? WHERE email_id = ? AND account_id = ?",
                (new, email_id, account_id),
            )
    conn.commit()
    print(f"[reclassify] DONE. Committed {len(changes)} changes.")


if __name__ == "__main__":
    main()

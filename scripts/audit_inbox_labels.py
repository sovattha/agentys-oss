"""Audit des labels d'inbox — compare label actuel vs label attendu via heuristiques.

Usage (sur Railway) :
    railway ssh 'python3 /app/scripts/audit_inbox_labels.py 5'

Arguments :
    account_id (int) — ex: 5 pour cours.universite@gmail.com

Output : stats globales + liste des mismatches les plus évidents.
"""
import re
import sqlite3
import sys
from collections import Counter, defaultdict

DB = "/data/agentys/agentys.db"

# Prefixes mass-mail (une vraie personne ne les utilise jamais)
MASS_MAIL_PREFIXES = (
    "team@", "news@", "newsletter@", "hello@", "updates@",
    "digest@", "weekly@", "daily@", "info@", "contact@",
    "notifications@", "notification@", "announcements@", "offers@",
    "promos@", "promo@", "marketing@", "deals@", "events@",
    "noreply@", "no-reply@", "donotreply@", "do-not-reply@",
    "auto-reply@", "autoreply@", "mailer@", "mailer-daemon@",
    "alerts@", "alert@", "feedback@", "surveys@",
    "receipts@", "billing@", "invoices@",
    "communications@", "emails@",
)

# Domaines marketing/SaaS connus (extrait de NOISE_SENDER_PATTERNS et NOISE_DOMAIN_SUFFIXES)
NOISE_DOMAIN_FRAGMENTS = (
    "@substack.com", "@brevo.com", "@superhuman.com",
    "@priority.instagram.com", "@mail.instagram.com", "instagram.com",
    "@facebookmail.com", "@mail.facebook.com", "facebook.com", "meta.com",
    "@notion.so", "@figma.com", "@vercel.com",
    "@sentry.io", "@linear.app", "@intercom.io",
    "@hubspot.com", "@mailchimp.com", "@sendgrid.net",
    "linkedin.com", "@netflix.com", "@strava.com",
    "@amazon.ca", "@amazon.com", "@flairair.ca",
    "binance.com", "coinbase.com", "kraken.com", "crypto.com",
    "bybit.com", "okx.com", "kucoin.com",
    "@notion.com", "@miro.com", "@uber.com", "@ubereats.com",
    "@thedailydegen.com", "@mail.thedailydegen.com",
    "@sidelined.app", "@sidelined.io", "@email.claude.com",
)

UNSUBSCRIBE_RE = re.compile(
    r"unsubscribe|désabonner|se désabonner|opt[-\s]?out|opter pour ne plus recevoir",
    re.IGNORECASE,
)
VIEW_IN_BROWSER_RE = re.compile(
    r"view.{0,20}in.{0,5}browser|voir.{0,20}navigateur|afficher.{0,20}navigateur",
    re.IGNORECASE,
)
MARKETING_CTA_RE = re.compile(
    r"\b(shop now|buy now|sign up|subscribe now|upgrade now|get started|"
    r"join now|try (it )?free|achetez|inscrivez-vous|profitez|découvrez|"
    r"commandez|rendez-vous sur)\b",
    re.IGNORECASE,
)


def extract_email(sender: str) -> str:
    """Extract address from 'Name <addr@domain>' format."""
    if not sender:
        return ""
    s = sender.strip().lower()
    m = re.search(r"<([^>]+)>", s)
    return m.group(1) if m else s


def has_mass_mail_prefix(email_addr: str) -> bool:
    return any(email_addr.startswith(p) for p in MASS_MAIL_PREFIXES)


def has_noise_domain(email_addr: str) -> bool:
    return any(frag in email_addr for frag in NOISE_DOMAIN_FRAGMENTS)


def compute_bulk_score(email_addr: str, body: str) -> float:
    """Approximation de _newsletter_score sans headers (pas stockés en DB)."""
    score = 0.0
    if has_mass_mail_prefix(email_addr):
        score += 0.5
    body_check = (body or "")[:5000]
    if UNSUBSCRIBE_RE.search(body_check):
        score += 0.3
    if VIEW_IN_BROWSER_RE.search(body_check):
        score += 0.3
    cta_count = len(MARKETING_CTA_RE.findall(body_check))
    if cta_count >= 2:
        score += 0.3
    return score


def expected_label(sender: str, subject: str, body: str) -> str:
    """Calcule le label attendu en inversant l'ordre des signaux décisifs."""
    email_addr = extract_email(sender)
    subj_lower = (subject or "").lower()

    # 1. Sender signaux durs → Noise
    if has_mass_mail_prefix(email_addr):
        return "Noise"
    if has_noise_domain(email_addr):
        return "Noise"

    # 2. Body signaux (bulk)
    if compute_bulk_score(email_addr, body) >= 0.6:
        return "Noise"

    # 3. Calendar noise patterns
    if re.search(r"^(?:re|tr|rv|fwd?)?:?\s*(accepted|declined|canceled|cancelled|annulé|refusé)\s*:",
                 subj_lower, re.IGNORECASE):
        return "Noise"

    # 4. Question = possible Action
    body_clean = (body or "")[:2000]
    if "?" in body_clean:
        # Genuine-question heuristic : court body OR interrogative marker
        if len(body_clean.strip()) <= 500 or re.search(
            r"\b(est-ce que|pourrais-tu|pouvez-vous|peux-tu|pouvez[- ]vous|can you|could you|please|merci de)\b",
            body_clean, re.IGNORECASE):
            return "Action"

    # 5. Action subject patterns
    if re.search(
        r"\b(action required|required|response needed|please (reply|review|confirm|sign|pay)|"
        r"invoice|facture|à signer|à valider|deadline|réclamation|demande d'information)\b",
        subj_lower, re.IGNORECASE):
        return "Action"

    # 6. Défaut FYI pour le reste
    return "FYI"


def main(account_id: int):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    rows = c.execute("""
        SELECT e.email_id, e.sender, e.subject, e.body_text, e.folder, e.date, el.label_name
        FROM emails e
        LEFT JOIN email_labels el ON el.email_id = e.email_id AND el.account_id = e.account_id
        WHERE e.account_id = ? AND e.folder = 'inbox'
    """, (account_id,)).fetchall()

    total = len(rows)
    actual_counts = Counter()
    expected_counts = Counter()
    confusion = defaultdict(lambda: Counter())  # confusion[actual][expected] = count
    mismatches_by_sender = defaultdict(lambda: {"count": 0, "actual": None, "expected": None, "samples": []})

    for email_id, sender, subject, body, folder, date, actual_label in rows:
        actual_label = actual_label or "Unlabeled"
        exp = expected_label(sender, subject, body)
        actual_counts[actual_label] += 1
        expected_counts[exp] += 1
        confusion[actual_label][exp] += 1

        if actual_label != exp and actual_label != "Unlabeled":
            email_addr = extract_email(sender or "")
            domain = email_addr.split("@")[-1] if "@" in email_addr else email_addr
            key = f"{actual_label}→{exp} | {domain}"
            mismatches_by_sender[key]["count"] += 1
            mismatches_by_sender[key]["actual"] = actual_label
            mismatches_by_sender[key]["expected"] = exp
            if len(mismatches_by_sender[key]["samples"]) < 3:
                mismatches_by_sender[key]["samples"].append({
                    "sender": sender,
                    "subject": (subject or "")[:80],
                    "date": date,
                })

    # Report
    print(f"=== AUDIT INBOX account {account_id} — {total} emails ===\n")
    print("## Distribution ACTUELLE (label posé par le classifieur)")
    for label, n in actual_counts.most_common():
        print(f"  {label:12s}: {n:4d} ({100*n/total:.1f}%)")

    print("\n## Distribution ATTENDUE (ce que nos heuristiques diraient)")
    for label, n in expected_counts.most_common():
        print(f"  {label:12s}: {n:4d} ({100*n/total:.1f}%)")

    print("\n## Matrice de confusion (actuel → attendu)")
    labels = ["Action", "FYI", "Noise", "Unlabeled"]
    print(f"{'':12s}" + "".join(f"{l[:9]:>10s}" for l in labels))
    for actual in labels:
        row = [f"{confusion[actual][exp]:10d}" for exp in labels]
        print(f"{actual:12s}" + "".join(row))

    # Top mismatches
    sorted_mismatches = sorted(mismatches_by_sender.items(), key=lambda kv: -kv[1]["count"])
    print(f"\n## Top 25 mismatches par (label actuel → attendu, domaine)")
    for key, info in sorted_mismatches[:25]:
        print(f"\n{key}  [{info['count']}x]")
        for s in info["samples"][:2]:
            sender_short = (s["sender"] or "")[:45]
            print(f"    - {s['date'][:10]}  {sender_short}")
            print(f"      subject: {s['subject']}")

    # Specific: emails that should be Noise but are FYI (main user pain)
    print("\n## PAIN POINT: 'FYI mais devrait être Noise' — détail complet")
    fyi_should_be_noise = []
    for email_id, sender, subject, body, folder, date, actual in rows:
        if actual == "FYI":
            exp = expected_label(sender, subject, body)
            if exp == "Noise":
                fyi_should_be_noise.append((date, sender, subject))
    print(f"  Total: {len(fyi_should_be_noise)} emails")
    for date, sender, subject in sorted(fyi_should_be_noise, reverse=True)[:30]:
        sender_short = (sender or "")[:40]
        subj_short = (subject or "")[:70]
        print(f"  {date[:10]}  {sender_short:40s}  {subj_short}")

    # Specific: emails that should be Action but are FYI
    print("\n## PAIN POINT: 'FYI mais devrait être Action' — détail")
    fyi_should_be_action = []
    for email_id, sender, subject, body, folder, date, actual in rows:
        if actual == "FYI":
            exp = expected_label(sender, subject, body)
            if exp == "Action":
                fyi_should_be_action.append((date, sender, subject))
    print(f"  Total: {len(fyi_should_be_action)} emails")
    for date, sender, subject in sorted(fyi_should_be_action, reverse=True)[:15]:
        sender_short = (sender or "")[:40]
        subj_short = (subject or "")[:70]
        print(f"  {date[:10]}  {sender_short:40s}  {subj_short}")


if __name__ == "__main__":
    aid = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    main(aid)

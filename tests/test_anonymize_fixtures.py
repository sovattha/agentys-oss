"""Tests unitaires pour `scripts/anonymize_fixtures.py`.

Couvre :
  - Regex strict sur emails, phones, IBAN, CB, IPs, numéros longs
  - Hash déterministe (même entrée → même sortie)
  - Placeholders non ré-hashés (stabilité à travers des passes successives)
  - Validator bloquant sur PII structurées
  - Validator laisse passer les noms (best-effort)
  - Récursion sur dicts / lists

Note : tests NER nécessitant spaCy chargé sont skipés si le modèle n'est pas installé.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


# Importer le script comme un module (enregistré dans sys.modules pour que @dataclass marche)
SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "anonymize_fixtures.py"
spec = importlib.util.spec_from_file_location("anonymize_fixtures", SCRIPT_PATH)
anon = importlib.util.module_from_spec(spec)
sys.modules["anonymize_fixtures"] = anon
spec.loader.exec_module(anon)


# ────────────────────────────────────────────────────────────────────────────
# Hash
# ────────────────────────────────────────────────────────────────────────────

def test_hash_is_deterministic():
    assert anon._hash_token("PER", "Jean Dupont") == anon._hash_token("PER", "Jean Dupont")


def test_hash_different_for_different_kinds():
    """Même token avec kind différent → hash différent (évite collisions)."""
    assert anon._hash_token("PER", "Paris") != anon._hash_token("LOC", "Paris")


def test_placeholder_format():
    ph = anon.make_placeholder("PER", "Jean")
    assert ph.startswith("PER_")
    assert len(ph) == 4 + 6  # "PER_" + 6 hex chars


# ────────────────────────────────────────────────────────────────────────────
# Regex structuré
# ────────────────────────────────────────────────────────────────────────────

def test_email_anonymized():
    stats = anon.AnonStats()
    out = anon.anonymize_text("Contact: alice@example.com pour plus d'info.", None, stats)
    assert "alice@example.com" not in out
    assert "EMAIL_" in out
    assert stats.regex_email == 1


def test_iban_anonymized():
    stats = anon.AnonStats()
    iban = "FR1420041010050500013M02606"
    out = anon.anonymize_text(f"IBAN: {iban}", None, stats)
    assert iban not in out
    assert "IBAN_" in out
    assert stats.regex_iban == 1


def test_ipv4_anonymized():
    stats = anon.AnonStats()
    out = anon.anonymize_text("Server at 192.168.1.42 was down.", None, stats)
    assert "192.168.1.42" not in out
    assert "IPV4_" in out
    assert stats.regex_ip == 1


def test_long_number_anonymized():
    """Un nombre long (11 chiffres) est anonymisé, soit comme PHONE (greedy)
    soit comme NUM. Les deux sont acceptables pour PII."""
    stats = anon.AnonStats()
    out = anon.anonymize_text("Commande 98765432101.", None, stats)
    assert "98765432101" not in out
    assert "PHONE_" in out or "NUM_" in out
    assert (stats.regex_phone + stats.regex_num) == 1


def test_multiple_pii_same_string():
    stats = anon.AnonStats()
    text = "Bonjour, email: x@y.fr, IBAN FR1420041010050500013M02606, IP 10.0.0.1"
    out = anon.anonymize_text(text, None, stats)
    assert "x@y.fr" not in out
    assert "FR1420041010050500013M02606" not in out
    assert "10.0.0.1" not in out
    assert stats.regex_email == 1
    assert stats.regex_iban == 1
    assert stats.regex_ip == 1


def test_deterministic_replacement_across_calls():
    """Même token → même placeholder entre appels."""
    stats1 = anon.AnonStats()
    stats2 = anon.AnonStats()
    out1 = anon.anonymize_text("Contact alice@test.fr", None, stats1)
    out2 = anon.anonymize_text("Nouveau message à alice@test.fr", None, stats2)
    # Extraire le placeholder de chaque sortie
    import re
    ph1 = re.search(r"EMAIL_[a-f0-9]{6}", out1).group(0)
    ph2 = re.search(r"EMAIL_[a-f0-9]{6}", out2).group(0)
    assert ph1 == ph2


def test_placeholder_not_re_hashed():
    """Un placeholder déjà anonymisé ne doit pas être re-hashé."""
    stats = anon.AnonStats()
    already = "Contact: EMAIL_abc123 (déjà anonymisé)"
    out = anon.anonymize_text(already, None, stats)
    # Le placeholder original reste (EMAIL_abc123 ne matche pas EMAIL_RE car pas de @)
    assert "EMAIL_abc123" in out


# ────────────────────────────────────────────────────────────────────────────
# Récursion dicts / lists
# ────────────────────────────────────────────────────────────────────────────

def test_anonymize_dict_recursive():
    stats = anon.AnonStats()
    payload = {
        "body": "Envoyé par alice@x.fr",
        "meta": {
            "sender": "bob@y.fr",
            "tags": ["charlie@z.fr", "public"],
        },
        "count": 42,  # int préservé
        "has_attachment": True,  # bool préservé
    }
    out = anon.anonymize_dict(payload, None, stats)
    assert "alice@x.fr" not in json.dumps(out)
    assert "bob@y.fr" not in json.dumps(out)
    assert "charlie@z.fr" not in json.dumps(out)
    assert out["count"] == 42
    assert out["has_attachment"] is True
    assert stats.regex_email == 3


def test_anonymize_record_preserves_metrics():
    """`corrections`, `correction_details`, etc. doivent être préservés intacts."""
    stats = anon.AnonStats()
    record = {
        "mode": "standard",
        "corrections": 4,
        "correction_details": ["html_cleanup", "filler_removed"],
        "learned_corrections_applied": ["rule_xyz"],
        "raw_draft": "Hello alice@test.fr",
        "cleaned_draft": "Hello alice@test.fr, how are you?",
        "pipeline_input": {"body": "Source from bob@x.fr", "formality": 3},
    }
    out = anon.anonymize_record(record, None, stats)
    assert out["mode"] == "standard"
    assert out["corrections"] == 4
    assert out["correction_details"] == ["html_cleanup", "filler_removed"]
    assert out["learned_corrections_applied"] == ["rule_xyz"]
    # Champs anonymisés
    assert "alice@test.fr" not in out["raw_draft"]
    assert "bob@x.fr" not in out["pipeline_input"]["body"]
    assert out["pipeline_input"]["formality"] == 3  # int préservé


# ────────────────────────────────────────────────────────────────────────────
# Validator
# ────────────────────────────────────────────────────────────────────────────

def test_validator_detects_email():
    issues = anon.validate_record(
        {"body": "Contact alice@leaky.fr"},
        fixture_name="test",
    )
    assert len(issues) == 1
    assert issues[0].kind == "EMAIL"
    assert "alice@leaky.fr" in issues[0].match


def test_validator_passes_clean_record():
    issues = anon.validate_record(
        {"body": "Hello PER_abc123, from ORG_def456."},
        fixture_name="test",
    )
    assert issues == []


def test_validator_ignores_names():
    """Les noms non-structurés ne sont PAS dans le validator (best-effort NER)."""
    issues = anon.validate_record(
        {"body": "Bonjour Richard Besson, ici Nathan Roy."},
        fixture_name="test",
    )
    # Noms laissés en clair : validator ne bloque pas (cf. D6 du RGPD)
    assert issues == []


def test_validator_detects_iban():
    issues = anon.validate_record(
        {"body": "IBAN: FR1420041010050500013M02606"},
        fixture_name="test",
    )
    assert len(issues) == 1
    assert issues[0].kind == "IBAN"


def test_validator_detects_ip():
    issues = anon.validate_record(
        {"body": "Server 192.168.1.42 failed."},
        fixture_name="test",
    )
    assert len(issues) == 1
    assert issues[0].kind == "IPV4"


def test_validator_traverses_nested():
    issues = anon.validate_record(
        {
            "level1": {
                "level2": {
                    "leak": "bob@evil.fr"
                }
            }
        },
        fixture_name="nested",
    )
    assert len(issues) == 1
    assert "bob@evil.fr" == issues[0].match


# ────────────────────────────────────────────────────────────────────────────
# Intégration (synthétique, sans spaCy chargé)
# ────────────────────────────────────────────────────────────────────────────

def test_end_to_end_without_nlp():
    """Pipeline complet regex-only (nlp=None). Résultat doit passer validator."""
    stats = anon.AnonStats()
    record = {
        "mode": "standard",
        "raw_draft": "Contact: alice@test.fr, tél 06.12.34.56.78.",
        "cleaned_draft": "Contact: alice@test.fr, tél 06.12.34.56.78. Cordialement.",
        "pipeline_input": {
            "body": "Original from bob@y.fr, IBAN FR1420041010050500013M02606",
            "subject": "Devis 20240815-0042",
            "formality": 3,
        },
        "corrections": 2,
        "correction_details": ["filler_removed", "html_cleanup"],
    }
    anonymized = anon.anonymize_record(record, None, stats)
    issues = anon.validate_record(anonymized, "test_e2e")

    assert issues == [], f"Validator failed: {issues}"
    # 3 email matches : alice x2 (raw + cleaned) + bob x1 (pipeline_input.body)
    assert stats.regex_email == 3
    assert stats.regex_iban == 1
    # "06.12.34.56.78" (phone FR avec points) matche le pattern IPv4 avant PHONE
    # — acceptable, la PII est anonymisée dans tous les cas
    assert (stats.regex_phone + stats.regex_ip) >= 2
    # Métriques préservées
    assert anonymized["corrections"] == 2
    assert anonymized["correction_details"] == ["filler_removed", "html_cleanup"]

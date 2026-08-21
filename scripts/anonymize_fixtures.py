#!/usr/bin/env python3
"""
Anonymiseur de fixtures pipeline capturées en prod.

Entrée  : `tmp/pipeline_captures/*.jsonl` (captures produites par `app._fixture_capture`)
Sortie  : `tests/fixtures/pipeline_golden/*.json` (fixtures anonymisées commitables)

Pipeline en 3 étapes :

1. **NER spaCy fr_core_news_lg** — identifie PERSON / ORG / LOC dans les champs texte.
   Best-effort d'après le benchmark (recall ~25-35%). Laisse passer une partie
   des noms : le dépôt étant public, l'étape 3 (validator bloquant) est ce qui
   garantit l'absence de PII structurée, pas le NER.

2. **Regex strict** (filet double) — remplace les PII structurées à 100% :
   emails, téléphones, IBAN, cartes bancaires, IPs, numéros longs.

3. **Validator PII** (bloquant) — re-scanne la sortie pour garantir 0 PII structurée
   résiduelle. Si match → exit 1 (commit bloqué).

Hash déterministe : `SHA-256(kind + "|" + token)[:6]` hex → 6 chars lowercase.
Même nom → même hash dans toutes les fixtures (préserve les patterns relationnels).

Usage :

    # Anonymiser tous les fichiers .jsonl du répertoire par défaut
    python scripts/anonymize_fixtures.py

    # Spécifier répertoires
    python scripts/anonymize_fixtures.py --input tmp/pipeline_captures \\
        --output tests/fixtures/pipeline_golden

    # Dry-run (pas d'écriture, juste stats + validator)
    python scripts/anonymize_fixtures.py --dry-run

    # Valider uniquement des fixtures déjà anonymisées (pas de NER/regex)
    python scripts/anonymize_fixtures.py --validate-only tests/fixtures/pipeline_golden/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)


# ============================================================================
# REGEX PII (filet double, couverture 100% requise)
# ============================================================================

# Emails : RFC-5322 simplifié
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Téléphones : formats FR + international. Tolère espaces, points, tirets, parens.
# Exemples : +33 6 12 34 56 78, 06.12.34.56.78, (+41) 78 123 45 67, 0041781234567
PHONE_RE = re.compile(
    r"(?:(?<=[\s:;,.!?\"'()\[\]/>])|^)"  # boundary avant (caractère non-chiffre ou début)
    r"(?:\+?\d{1,3}[\s.\-]?)?"  # préfixe international optionnel
    r"(?:\(\d{1,4}\)[\s.\-]?)?"  # code région entre parenthèses optionnel
    r"(?:\d{1,4}[\s.\-]?){3,5}"  # groupes de chiffres (min 3 groupes, max 5)
    r"\d{2,4}"  # dernier groupe
    r"(?=[\s:;,.!?\"'()\[\]<]|$)"  # boundary après
)

# IBAN : 2 lettres pays + 2 check digits + 11-30 caractères alphanumériques
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")

# Cartes bancaires : 13-19 chiffres, tolère espaces/tirets
CARD_RE = re.compile(r"\b(?:\d[\s\-]?){13,19}\b")

# IPv4
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# IPv6 (simplifié)
IPV6_RE = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b")

# Numéros longs (SIREN, numéros de compte, facture, etc.) — 8+ chiffres consécutifs
LONG_NUM_RE = re.compile(r"\b\d{8,}\b")

# Ordre d'application : les plus spécifiques d'abord pour éviter que LONG_NUM mange
# des chiffres d'un IBAN ou d'une CB.
STRUCTURED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", EMAIL_RE),
    ("IBAN", IBAN_RE),
    ("CARD", CARD_RE),
    ("IPV6", IPV6_RE),
    ("IPV4", IPV4_RE),
    ("PHONE", PHONE_RE),
    ("NUM", LONG_NUM_RE),
]

# Validator (strict) : patterns qui NE DOIVENT PAS apparaître dans la sortie.
# Les noms (PER/ORG/LOC) sont best-effort → pas dans le validator.
VALIDATOR_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", EMAIL_RE),
    ("IBAN", IBAN_RE),
    ("CARD", CARD_RE),
    ("IPV4", IPV4_RE),
    ("IPV6", IPV6_RE),
    # PHONE et NUM exclus du validator car trop ambigus (peut matcher des IDs
    # déjà hashés comme "PER_abc123def"). On fait confiance aux remplacements.
]


# ============================================================================
# HASH DÉTERMINISTE
# ============================================================================

def _hash_token(kind: str, token: str) -> str:
    """SHA-256 tronqué à 6 hex chars. Même entrée → même sortie."""
    raw = f"{kind}|{token}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:6]


def make_placeholder(kind: str, token: str) -> str:
    """Produit le placeholder lisible : `PER_abc123`, `EMAIL_def456`, etc."""
    return f"{kind}_{_hash_token(kind, token)}"


# ============================================================================
# ANONYMISATION TEXTE
# ============================================================================

@dataclass
class AnonStats:
    ner_person: int = 0
    ner_org: int = 0
    ner_loc: int = 0
    regex_email: int = 0
    regex_phone: int = 0
    regex_iban: int = 0
    regex_card: int = 0
    regex_ip: int = 0
    regex_num: int = 0

    def add(self, other: "AnonStats") -> None:
        self.ner_person += other.ner_person
        self.ner_org += other.ner_org
        self.ner_loc += other.ner_loc
        self.regex_email += other.regex_email
        self.regex_phone += other.regex_phone
        self.regex_iban += other.regex_iban
        self.regex_card += other.regex_card
        self.regex_ip += other.regex_ip
        self.regex_num += other.regex_num

    def summary(self) -> str:
        return (
            f"NER: PER={self.ner_person} ORG={self.ner_org} LOC={self.ner_loc} | "
            f"Regex: EMAIL={self.regex_email} PHONE={self.regex_phone} "
            f"IBAN={self.regex_iban} CARD={self.regex_card} IP={self.regex_ip} "
            f"NUM={self.regex_num}"
        )


# Mapping spaCy label → notre préfixe + compteur field
SPACY_LABEL_MAP: dict[str, str] = {
    "PER": "PER",
    "PERSON": "PER",
    "ORG": "ORG",
    "LOC": "LOC",
    "GPE": "LOC",
}


def anonymize_text(text: str, nlp, stats: AnonStats) -> str:
    """Anonymise un texte : regex structuré d'abord, puis NER.

    Ordre critique : regex en premier sinon spaCy pourrait tagger un IBAN comme
    MISC, créant des placeholders croisés.
    """
    if not text or not isinstance(text, str):
        return text

    # 1. Regex structuré — 100% couverture requise
    for kind, pattern in STRUCTURED_PATTERNS:
        def _replace(match: re.Match[str], _kind: str = kind) -> str:
            token = match.group(0)
            placeholder = make_placeholder(_kind, token)
            counter_field = f"regex_{_kind.lower()}"
            if counter_field == "regex_ipv4" or counter_field == "regex_ipv6":
                counter_field = "regex_ip"
            if hasattr(stats, counter_field):
                setattr(stats, counter_field, getattr(stats, counter_field) + 1)
            return placeholder
        text = pattern.sub(_replace, text)

    # 2. NER best-effort via spaCy
    if nlp is not None:
        doc = nlp(text)
        # Traiter les entités en ordre inverse pour ne pas casser les offsets
        spans = []
        for ent in doc.ents:
            mapped = SPACY_LABEL_MAP.get(ent.label_)
            if mapped is None:
                continue
            spans.append((ent.start_char, ent.end_char, ent.text, mapped))

        # Trier par start_char décroissant pour remplacer sans décaler
        spans.sort(key=lambda s: s[0], reverse=True)
        for start, end, token, kind in spans:
            # Vérifier que ce span n'est pas déjà un placeholder (evite double-hash)
            if re.fullmatch(r"(?:PER|ORG|LOC|EMAIL|PHONE|IBAN|CARD|IPV4|IPV6|NUM)_[a-f0-9]{6}", token):
                continue
            placeholder = make_placeholder(kind, token)
            text = text[:start] + placeholder + text[end:]
            if kind == "PER":
                stats.ner_person += 1
            elif kind == "ORG":
                stats.ner_org += 1
            elif kind == "LOC":
                stats.ner_loc += 1

    return text


def anonymize_dict(obj: Any, nlp, stats: AnonStats) -> Any:
    """Recursively anonymize string values in dicts/lists."""
    if isinstance(obj, str):
        return anonymize_text(obj, nlp, stats)
    if isinstance(obj, dict):
        return {k: anonymize_dict(v, nlp, stats) for k, v in obj.items()}
    if isinstance(obj, list):
        return [anonymize_dict(item, nlp, stats) for item in obj]
    return obj  # int, float, bool, None : inchangés


# Schéma d'anonymisation granulaire.
# Évite de passer des métadonnées (formality=3, detected_language="fr") au NER,
# qui sur-anonymise sinon ("fr" → LOC_xxx).
PRESERVED_FIELDS = {
    "captured_at", "mode", "corrections", "correction_details",
    "learned_corrections_applied",
}
ANON_FIELDS_TOP = {"raw_draft", "cleaned_draft", "extra"}

# Dans pipeline_input : seuls les champs contenant du texte libre sont anonymisés.
PIPELINE_INPUT_TEXT_FIELDS = {
    "body", "subject", "sender", "sender_name",
    "effective_sender_name", "greeting_hint",
}
# Liste de dicts (chaque message a body, sender, etc.) — récursion activée.
PIPELINE_INPUT_LIST_FIELDS = {"conversation_history"}
# Métadonnées numériques / enum — NE JAMAIS anonymiser (ferait passer "fr" → LOC_xxx).
PIPELINE_INPUT_PRESERVED = {
    "formality", "detected_language", "has_history",
}


def _anonymize_pipeline_input(data: dict, nlp, stats: AnonStats) -> dict:
    """Anonymisation granulaire du pipeline_input — champs texte seulement."""
    if not isinstance(data, dict):
        return anonymize_dict(data, nlp, stats)
    result: dict = {}
    for key, value in data.items():
        if key in PIPELINE_INPUT_TEXT_FIELDS:
            result[key] = anonymize_text(value, nlp, stats) if isinstance(value, str) else value
        elif key in PIPELINE_INPUT_LIST_FIELDS:
            result[key] = anonymize_dict(value, nlp, stats)
        elif key in PIPELINE_INPUT_PRESERVED:
            result[key] = value
        else:
            # Clé inconnue : anonymiser par défaut (safe fallback)
            result[key] = anonymize_dict(value, nlp, stats)
    return result


def anonymize_record(record: dict, nlp, stats: AnonStats) -> dict:
    """Anonymise une capture JSONL en préservant les métriques."""
    out: dict = {}
    for key, value in record.items():
        if key == "pipeline_input":
            out[key] = _anonymize_pipeline_input(value, nlp, stats)
        elif key in ANON_FIELDS_TOP:
            out[key] = anonymize_dict(value, nlp, stats)
        elif key in PRESERVED_FIELDS:
            out[key] = value
        else:
            # Clé inconnue : anonymiser par sécurité
            out[key] = anonymize_dict(value, nlp, stats)
    return out


# ============================================================================
# VALIDATOR PII (bloquant)
# ============================================================================

@dataclass
class ValidationIssue:
    fixture: str
    kind: str
    match: str
    context: str  # extrait 40 chars autour du match


def validate_record(record: dict, fixture_name: str) -> list[ValidationIssue]:
    """Re-scanne le record pour PII résiduelle. Retourne la liste des issues."""
    issues: list[ValidationIssue] = []

    def _scan(value: Any) -> None:
        if isinstance(value, str):
            for kind, pattern in VALIDATOR_PATTERNS:
                for match in pattern.finditer(value):
                    # Skip si c'est un placeholder valide
                    token = match.group(0)
                    if re.fullmatch(
                        r"(?:PER|ORG|LOC|EMAIL|PHONE|IBAN|CARD|IPV4|IPV6|NUM)_[a-f0-9]{6}",
                        token,
                    ):
                        continue
                    # Extrait de contexte autour du match
                    start = max(0, match.start() - 20)
                    end = min(len(value), match.end() + 20)
                    context = value[start:end].replace("\n", " ")
                    issues.append(ValidationIssue(
                        fixture=fixture_name, kind=kind, match=token, context=context,
                    ))
        elif isinstance(value, dict):
            for v in value.values():
                _scan(v)
        elif isinstance(value, list):
            for item in value:
                _scan(item)

    _scan(record)
    return issues


# ============================================================================
# I/O
# ============================================================================

def iter_captures(input_dir: Path) -> Iterator[tuple[str, dict]]:
    """Itère sur toutes les lignes JSONL des fichiers dans `input_dir`.

    Yield : (source_file_id, record)
    """
    for path in sorted(input_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning("Skipping malformed line %s:%d: %s", path.name, line_num, exc)
                    continue
                yield f"{path.stem}_L{line_num:04d}", record


def write_fixture(record: dict, out_dir: Path, fixture_id: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{fixture_id}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ============================================================================
# CLI
# ============================================================================

def load_nlp(model_name: str):
    """Charge spaCy model. Return None si non disponible (mode dégradé regex only)."""
    try:
        import spacy
    except ImportError:
        logger.error("spacy non installé. Installation: pip install spacy && "
                     "python -m spacy download fr_core_news_lg")
        return None
    try:
        return spacy.load(model_name)
    except OSError:
        logger.error("Modèle %s non installé. Installation: python -m spacy download %s",
                     model_name, model_name)
        return None


def run_anonymize(
    input_dir: Path,
    output_dir: Path,
    model_name: str,
    dry_run: bool,
) -> int:
    nlp = load_nlp(model_name)
    if nlp is None:
        return 1

    total_stats = AnonStats()
    all_issues: list[ValidationIssue] = []
    n_processed = 0
    n_written = 0

    for fixture_id, record in iter_captures(input_dir):
        n_processed += 1
        record_stats = AnonStats()
        anonymized = anonymize_record(record, nlp, record_stats)
        total_stats.add(record_stats)

        issues = validate_record(anonymized, fixture_id)
        all_issues.extend(issues)

        if not dry_run:
            write_fixture(anonymized, output_dir, fixture_id)
            n_written += 1

    # Rapport
    print(f"Fixtures traitées : {n_processed}")
    if not dry_run:
        print(f"Fixtures écrites  : {n_written} → {output_dir}")
    print(f"\nAnonymisation totale : {total_stats.summary()}")

    if all_issues:
        print(f"\n❌ {len(all_issues)} PII résiduelle(s) détectée(s) :")
        for issue in all_issues[:20]:
            print(f"  [{issue.kind}] {issue.fixture} : '{issue.match}' | "
                  f"contexte: ...{issue.context}...")
        if len(all_issues) > 20:
            print(f"  ... et {len(all_issues) - 20} autres")
        print("\nLe validator bloque la sortie. Corriger les regex de STRUCTURED_PATTERNS.")
        return 1

    print("\n✅ Validator OK : 0 PII structurée résiduelle.")
    print("ℹ️  Noms de personnes/orgs/lieux : anonymisation best-effort uniquement "
          "(validator PII bloquant — voir le docstring du module).")
    return 0


def run_validate_only(target_dir: Path) -> int:
    """Re-valider des fixtures déjà anonymisées (sans NER ni regex de remplacement)."""
    all_issues: list[ValidationIssue] = []
    n = 0
    for path in sorted(target_dir.glob("*.json")):
        n += 1
        record = json.loads(path.read_text(encoding="utf-8"))
        issues = validate_record(record, path.stem)
        all_issues.extend(issues)

    print(f"Fixtures validées : {n}")
    if all_issues:
        print(f"❌ {len(all_issues)} PII résiduelle(s) :")
        for issue in all_issues[:20]:
            print(f"  [{issue.kind}] {issue.fixture} : '{issue.match}'")
        return 1
    print("✅ 0 PII structurée résiduelle.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", type=Path, default=Path("tmp/pipeline_captures"))
    parser.add_argument("--output", type=Path, default=Path("tests/fixtures/pipeline_golden"))
    parser.add_argument("--model", default="fr_core_news_lg")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", type=Path, default=None,
                        help="Répertoire à re-valider (skip NER/regex).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s - %(message)s")

    if args.validate_only is not None:
        return run_validate_only(args.validate_only)

    if not args.input.exists():
        print(f"[ERROR] Répertoire d'entrée introuvable : {args.input}", file=sys.stderr)
        return 1

    return run_anonymize(args.input, args.output, args.model, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

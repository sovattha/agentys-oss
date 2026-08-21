# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter pour le stockage des labels et règles de labellisation.

Stocke:
- Labels personnalisés (Action, Waiting, FYI, Noise, custom)
- Règles de labellisation (apprises et manuelles)
- Historique des assignations

Génère aussi le fichier markdown des règles apprises.
"""

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any

import logging

from app.domain.entities.email_labels import (
    DEFAULT_LABEL_NAMES,
    EmailLabel,
    LabelAssignment,
    LabelingRule,
    get_default_labels,
)

logger = logging.getLogger(__name__)


@dataclass
class LabelStore:
    """
    Stockage persistant pour labels et règles.

    Structure de fichiers:
    - labels.json: Définitions des labels
    - rules.json: Règles de labellisation
    - assignments.json: Historique des assignations
    - RULES.md: Documentation markdown des règles
    """
    storage_dir: str

    def __post_init__(self):
        """Initialise le stockage."""
        os.makedirs(self.storage_dir, exist_ok=True)

        # In-memory assignment cache: loaded lazily, invalidated on save
        self._assign_cache: Optional[Dict[str, LabelAssignment]] = None

        # Lock for all assignment file read-modify-write operations
        self._assign_lock = threading.Lock()
        self._rules_lock = threading.RLock()

        # Initialiser avec labels par défaut si nouveau
        if not os.path.exists(self._labels_path):
            self._init_default_labels()

        if not os.path.exists(self._rules_path):
            self._save_rules([])

        # Purge rules targeting labels that no longer exist
        self._purge_orphaned_rules()

        # Warm assignment cache eagerly to avoid lazy disk I/O on first request
        self._load_assign_cache()

    def _purge_orphaned_rules(self):
        """Remove rules targeting labels that don't exist in the library."""
        try:
            labels = self.get_labels()
            known = {lbl.name for lbl in labels}
            known.update(DEFAULT_LABEL_NAMES)

            rules = self.get_rules()
            clean = [r for r in rules if r.label_name in known]
            removed = len(rules) - len(clean)
            if removed > 0:
                self._save_rules(clean)
                logger.info("Purged %d orphaned rules targeting non-existent labels", removed)
        except Exception as e:
            logger.debug("purge_orphaned_rules: %s", e)

    @property
    def _labels_path(self) -> str:
        return os.path.join(self.storage_dir, "labels.json")

    @property
    def _rules_path(self) -> str:
        return os.path.join(self.storage_dir, "rules.json")

    @property
    def _assignments_path(self) -> str:
        return os.path.join(self.storage_dir, "assignments.json")

    def _global_assignments_path(self) -> Optional[str]:
        """If self is a per-account store (`data/labels/<acct>/`), return
        the path to the global store's assignments file one level up
        (`data/labels/assignments.json`). Otherwise return None.

        Used to merge auto-classifier writes (which land in the global
        file when no account context is available) into per-account reads.
        """
        parent = os.path.dirname(self.storage_dir.rstrip(os.sep).rstrip('/'))
        candidate = os.path.join(parent, "assignments.json")
        if candidate == self._assignments_path:
            return None
        return candidate if os.path.exists(candidate) else None

    @property
    def _rules_md_path(self) -> str:
        return os.path.join(self.storage_dir, "RULES.md")

    def _init_default_labels(self) -> None:
        """Crée les labels par défaut."""
        default_labels = get_default_labels()
        self._save_labels(default_labels)

    # =========================================================================
    # Labels
    # =========================================================================

    def get_labels(self) -> List[EmailLabel]:
        """Retourne tous les labels."""
        try:
            with open(self._labels_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return get_default_labels()

        labels: List[EmailLabel] = []
        for item in data:
            try:
                labels.append(EmailLabel.from_dict(item))
            except Exception:
                # Skip corrupted entries (missing/empty name, bad types, etc.)
                pass
        return labels

    def get_label(self, name: str) -> Optional[EmailLabel]:
        """Retourne un label par son nom."""
        labels = self.get_labels()
        for label in labels:
            if label.name.lower() == name.lower():
                return label
        return None

    def add_label(self, label: EmailLabel) -> bool:
        """Ajoute un nouveau label."""
        labels = self.get_labels()

        # Vérifier unicité du nom
        if any(lbl.name.lower() == label.name.lower() for lbl in labels):
            return False

        labels.append(label)
        self._save_labels(labels)
        return True

    def update_label(self, name: str, updates: Dict[str, Any]) -> bool:
        """Met à jour un label existant."""
        labels = self.get_labels()

        for i, label in enumerate(labels):
            if label.name.lower() == name.lower():
                label_dict = label.to_dict()
                label_dict.update(updates)
                labels[i] = EmailLabel.from_dict(label_dict)
                self._save_labels(labels)
                return True

        return False

    def delete_label(self, name: str) -> str:
        """Supprime un label (pas les labels par défaut).

        Returns: 'deleted' | 'not_found' | 'is_default'
        """
        labels = self.get_labels()

        for i, label in enumerate(labels):
            if label.name.lower() == name.lower():
                if label.is_default:
                    return 'is_default'
                labels.pop(i)
                self._save_labels(labels)
                return 'deleted'

        return 'not_found'

    def _save_labels(self, labels: List[EmailLabel]) -> None:
        """Sauvegarde les labels."""
        data = [label.to_dict() for label in labels]
        with open(self._labels_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # =========================================================================
    # Rules
    # =========================================================================

    def get_rules(self) -> List[LabelingRule]:
        """Retourne toutes les règles."""
        with self._rules_lock:
            try:
                with open(self._rules_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return []

            rules: List[LabelingRule] = []
            for item in data:
                try:
                    rules.append(LabelingRule.from_dict(item))
                except Exception:
                    pass
            return rules

    def get_rules_for_label(self, label_name: str) -> List[LabelingRule]:
        """Retourne les règles pour un label donné."""
        rules = self.get_rules()
        return [r for r in rules if r.label_name.lower() == label_name.lower()]

    def add_rule(self, rule: LabelingRule) -> bool:
        """Ajoute une nouvelle règle.

        Handles conflicts: if a rule with the same condition but a different
        default label already exists, the old rule is replaced (user's latest
        correction wins).

        Rejects rules targeting labels that don't exist in the user's library.
        """
        with self._rules_lock:
            # Guard: only accept rules for labels that exist in the library
            known = {lbl.name for lbl in self.get_labels()}
            known.update(DEFAULT_LABEL_NAMES)
            if rule.label_name not in known:
                logger.warning("add_rule: label '%s' not in library, rule rejected", rule.label_name)
                return False

            rules = self.get_rules()

            # Check for exact duplicate (same label + same condition)
            for existing in rules:
                if (existing.label_name == rule.label_name and
                    existing.condition_type == rule.condition_type and
                    existing.condition_value.lower() == rule.condition_value.lower()):
                    # Update confidence if higher
                    if rule.confidence > existing.confidence:
                        existing.confidence = rule.confidence
                        self._save_rules(rules)
                    return False

            # Check for conflicting default label rules (same condition, different default label)
            # User's latest correction should win over old rules.
            if rule.label_name in DEFAULT_LABEL_NAMES:
                conflicting = [
                    r for r in rules
                    if r.condition_type == rule.condition_type
                    and r.condition_value.lower() == rule.condition_value.lower()
                    and r.label_name in DEFAULT_LABEL_NAMES
                    and r.label_name != rule.label_name
                ]
                for old_rule in conflicting:
                    rules.remove(old_rule)

            rules.append(rule)
            self._save_rules(rules)
            self._update_rules_markdown()
            return True

    def update_rule(self, rule_id: str, updates: Dict[str, Any]) -> bool:
        """Met à jour une règle existante."""
        with self._rules_lock:
            rules = self.get_rules()

            for i, rule in enumerate(rules):
                if rule.rule_id == rule_id:
                    rule_dict = rule.to_dict()
                    rule_dict.update(updates)
                    rules[i] = LabelingRule.from_dict(rule_dict)
                    self._save_rules(rules)
                    self._update_rules_markdown()
                    return True

            return False

    def delete_rule(self, rule_id: str) -> bool:
        """Supprime une règle."""
        with self._rules_lock:
            rules = self.get_rules()

            for i, rule in enumerate(rules):
                if rule.rule_id == rule_id:
                    rules.pop(i)
                    self._save_rules(rules)
                    self._update_rules_markdown()
                    return True

            return False

    def _save_rules(self, rules: List[LabelingRule]) -> None:
        """Sauvegarde les règles."""
        with self._rules_lock:
            data = [rule.to_dict() for rule in rules]
            with open(self._rules_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    def increment_rule_match_counts(self, rule_ids: List[str]) -> None:
        """Incrémente atomiquement total_matches et use_count pour les règles matchées."""
        if not rule_ids:
            return
        with self._rules_lock:
            rules = self.get_rules()
            rule_id_set = set(rule_ids)
            changed = False
            now = datetime.now().isoformat()
            for rule in rules:
                if rule.rule_id in rule_id_set:
                    rule.total_matches += 1
                    rule.use_count += 1
                    rule.last_used_at = now
                    changed = True
            if changed:
                self._save_rules(rules)

    def prune_inactive_rules(self, max_age_days: int = 90) -> int:
        """Prune stale rules: disabled rules and unused learned rules older than max_age_days.

        Called automatically every ~50 corrections. Lightweight: skips if no rules to prune.
        """
        with self._rules_lock:
            rules = self.get_rules()
            if not rules:
                return 0

            now = datetime.now()
            to_keep = []
            pruned = 0

            for rule in rules:
                age_days = 0
                try:
                    created = datetime.fromisoformat(rule.created_at)
                    age_days = (now - created).days
                except (ValueError, TypeError):
                    pass

                # Prune disabled rules older than max_age_days
                if not rule.is_active and age_days > max_age_days:
                    pruned += 1
                    continue

                # Prune learned rules with 0 usage older than max_age_days
                if (rule.learned_from and rule.use_count == 0
                        and rule.total_matches == 0 and age_days > max_age_days):
                    pruned += 1
                    continue

                to_keep.append(rule)

            if pruned > 0:
                self._save_rules(to_keep)
                self._update_rules_markdown()

            return pruned

    # =========================================================================
    # Assignments
    # =========================================================================

    def get_assignments(self, limit: int = 100) -> List[LabelAssignment]:
        """Retourne l'historique des assignations."""
        try:
            with open(self._assignments_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                assignments = [LabelAssignment.from_dict(item) for item in data]
                return assignments[-limit:]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _load_assign_cache(self) -> Dict[str, LabelAssignment]:
        """Load assignment cache lazily from disk (1 read, then in-memory)."""
        if self._assign_cache is not None:
            return self._assign_cache
        assignments = self.get_assignments(limit=10000)
        # Build dict keyed by email_id (last entry wins for duplicates)
        cache: Dict[str, LabelAssignment] = {}
        for a in assignments:
            cache[a.email_id] = a
        self._assign_cache = cache
        return cache

    def get_assignment(self, email_id: str) -> Optional[LabelAssignment]:
        """Retourne l'assignation pour un email (cache mémoire)."""
        cache = self._load_assign_cache()
        return cache.get(email_id)

    def get_assignments_batch(self, email_ids: List[str]) -> Dict[str, LabelAssignment]:
        """Batch lookup: retourne les assignations pour une liste d'emails.

        Single cache load instead of N file reads.

        Returns:
            Dict email_id -> LabelAssignment (only for emails that have one).
        """
        cache = self._load_assign_cache()
        return {eid: cache[eid] for eid in email_ids if eid in cache}

    def save_assignment(self, assignment: LabelAssignment) -> None:
        """Sauvegarde une assignation (invalide le cache mémoire)."""
        with self._assign_lock:
            # Update the in-memory cache directly (source of truth)
            cache = self._load_assign_cache()
            cache[assignment.email_id] = assignment

            # Limit to 10000 entries
            if len(cache) > 10000:
                # Remove oldest entries (arbitrary order in dict, but good enough)
                excess = len(cache) - 10000
                for key in list(cache.keys())[:excess]:
                    del cache[key]

            data = [a.to_dict() for a in cache.values()]
            with open(self._assignments_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            # Cache is already updated in-place — no invalidation needed

        # Dual-write to SQLite email_labels table (best-effort — JSON is authoritative)
        try:
            from app.db.database import get_db_session
            from sqlalchemy import text as _text
            with get_db_session() as _session:
                # Resolve account_id from emails table
                _account_id = _session.execute(
                    _text("SELECT account_id FROM emails WHERE email_id = :eid LIMIT 1"),
                    {"eid": assignment.email_id},
                ).scalar()
                if not _account_id:
                    # SKIP the SQL dual-write rather than fall back to a hardcoded
                    # account_id=1, which would cross-contaminate labels between
                    # accounts when email_id is momentarily missing from the emails
                    # table (pending sync, race condition). JSON remains authoritative.
                    import logging as _logging
                    _logging.getLogger(__name__).warning(
                        "[WARN] email_labels: email_id %s not found in emails table, "
                        "skipping SQL dual-write (JSON remains authoritative)",
                        assignment.email_id,
                    )
                else:
                    _session.execute(
                        _text("DELETE FROM email_labels WHERE email_id = :eid AND account_id = :aid"),
                        {"eid": assignment.email_id, "aid": _account_id},
                    )
                    for _label in assignment.labels:
                        _session.execute(
                            _text("INSERT INTO email_labels (email_id, account_id, label_name) "
                                  "VALUES (:eid, :aid, :lbl)"),
                            {"eid": assignment.email_id, "aid": _account_id, "lbl": _label},
                        )
        except Exception as _e:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"[WARN] email_labels dual-write failed for {assignment.email_id}: {_e}"
            )

    def save_assignments_batch(self, assignments: List[LabelAssignment]) -> None:
        """Persist many assignments in ONE file rewrite + ONE DB transaction.

        ``save_assignment`` rewrites the entire assignments JSON file (up to
        10 000 entries) AND opens a fresh DB session on EVERY call. A labeling
        loop calling it once per email therefore did N full-file rewrites + N
        independent transactions for a page of N emails (deep audit 2026-06-02
        G). This batches both: the in-memory cache (the source of truth) is
        updated for every assignment, the file is dumped once, and the SQLite
        dual-write runs inside a single session/transaction.

        SAFETY: only use this when NO per-email read of the just-persisted label
        state happens between iterations. ``_sync_label_emails`` deliberately
        keeps the per-email ``save_assignment`` because it fires
        ``run_auto_triggers`` inline after each save, and ``has_label`` reads the
        ``email_labels`` SQL table — so that path needs the SQL write committed
        per email. ``_auto_assign_labels_background`` saves ALL emails first and
        only then runs triggers, so it is safe to batch.
        """
        if not assignments:
            return

        with self._assign_lock:
            cache = self._load_assign_cache()
            for assignment in assignments:
                cache[assignment.email_id] = assignment

            # Limit to 10000 entries (same policy as save_assignment).
            if len(cache) > 10000:
                excess = len(cache) - 10000
                for key in list(cache.keys())[:excess]:
                    del cache[key]

            data = [a.to_dict() for a in cache.values()]
            with open(self._assignments_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        # Single DB transaction for the SQL dual-write of every assignment.
        try:
            from app.db.database import get_db_session
            from sqlalchemy import text as _text, bindparam as _bindparam
            import logging as _logging

            email_ids = [a.email_id for a in assignments]
            with get_db_session() as _session:
                # Resolve account_id for all email_ids in ONE query.
                _resolve_stmt = _text(
                    "SELECT email_id, account_id FROM emails WHERE email_id IN :eids"
                ).bindparams(_bindparam("eids", expanding=True))
                _rows = _session.execute(
                    _resolve_stmt, {"eids": list({*email_ids})}
                ).fetchall()
                _acct_by_eid = {r[0]: r[1] for r in _rows}

                for assignment in assignments:
                    _account_id = _acct_by_eid.get(assignment.email_id)
                    if not _account_id:
                        # Same policy as save_assignment: skip the SQL dual-write
                        # rather than guess account_id (would cross-contaminate);
                        # JSON remains authoritative.
                        _logging.getLogger(__name__).warning(
                            "[WARN] email_labels: email_id %s not found in emails "
                            "table, skipping SQL dual-write (JSON authoritative)",
                            assignment.email_id,
                        )
                        continue
                    _session.execute(
                        _text("DELETE FROM email_labels WHERE email_id = :eid AND account_id = :aid"),
                        {"eid": assignment.email_id, "aid": _account_id},
                    )
                    for _label in assignment.labels:
                        _session.execute(
                            _text("INSERT INTO email_labels (email_id, account_id, label_name) "
                                  "VALUES (:eid, :aid, :lbl)"),
                            {"eid": assignment.email_id, "aid": _account_id, "lbl": _label},
                        )
        except Exception as _e:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"[WARN] email_labels batch dual-write failed: {_e}"
            )

    def get_label_counts(self, valid_email_ids: set = None) -> Dict[str, int]:
        """Retourne le nombre d'emails par label.

        Args:
            valid_email_ids: If provided, only count assignments whose email_id
                is in this set. Prevents stale counts for deleted emails.
        """
        cache = self._load_assign_cache()
        counts: Dict[str, int] = {}

        for email_id, assignment in cache.items():
            if valid_email_ids is not None and email_id not in valid_email_ids:
                continue
            for label_name in assignment.labels:
                counts[label_name] = counts.get(label_name, 0) + 1

        return counts

    def get_emails_by_label(
        self,
        label_name: str,
        valid_email_ids: set = None,
        account_id: Optional[int] = None,
    ) -> List[str]:
        """Retourne les IDs d'emails ayant un label donné.

        Args:
            valid_email_ids: If provided, only return IDs in this set.
            account_id: DB integer account id (from accounts.id). When
                omitted, the function falls back to the process-global
                current account, which is not user-scoped on a multi-user
                deployment and is therefore unreliable. Always pass the
                resolved INT id from a request context.

        Strategy: read BOTH stores and union the results.

        - SQL `email_labels` is fast and account-scoped but is a lossy mirror —
          `save_assignment()` skips the SQL write when the corresponding row
          in `emails` hasn't synced yet (cf. BUG-I001, save_assignment L420-430),
          so a label can live in JSON alone for some time.
        - JSON `assignments.json` is the canonical authority per the
          file-level docstring AND is what `/api/labels/counts` reads, so a
          SQL-only read here is what makes the Action/Info tabs show "111
          counted, 2 listed" — the divergence the user reports.

        Cross-account safety: provider email IDs are unique per account
        namespace, so a JSON ID belonging to another account cannot shadow a
        real match. Downstream callers (`get_by_account(email_ids=…)`) layer
        an `account_id = :aid` SQL filter on top, so the final list is
        always scoped correctly.
        """
        _account_id = int(account_id) if account_id is not None else None
        if _account_id is None:
            try:
                from app.multi_accounts import get_account_manager
                _acct = get_account_manager().get_current_account()
                if _acct:
                    from app.db.database import get_db_session as _resolve_session
                    from sqlalchemy import text as _resolve_text
                    with _resolve_session() as _rs:
                        _row = _rs.execute(
                            _resolve_text(
                                "SELECT id FROM accounts WHERE email = :email"
                            ),
                            {"email": _acct.email},
                        ).first()
                        if _row:
                            _account_id = int(_row[0])
            except Exception:
                pass

        # ── SQL pass (account-scoped, fast) ────────────────────────────
        sql_ids: set = set()
        if _account_id:
            try:
                from app.db.database import get_db_session
                from sqlalchemy import text as _text

                with get_db_session() as _session:
                    rows = _session.execute(
                        _text(
                            "SELECT DISTINCT email_id FROM email_labels "
                            "WHERE label_name = :lbl AND account_id = :aid"
                        ),
                        {"lbl": label_name, "aid": _account_id},
                    ).fetchall()
                    sql_ids = {str(r[0]) for r in rows if r[0]}
            except Exception as _e:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "[label_store] SQL get_emails_by_label('%s') failed: %s — using JSON only",
                    label_name, _e,
                )

        # ── JSON pass (canonical, may include cross-account entries) ───
        cache = self._load_assign_cache()
        json_ids: set = {
            eid for eid, assignment in cache.items()
            if label_name in assignment.labels
        }

        # The auto-classifier (LabelEmailUseCase called from the daemon
        # pipeline) writes to the *global* store at `data/labels/` because
        # at classification time the account context is not always passed
        # in. The counts endpoint (`/api/labels/counts`) also reads from
        # the global store — and that is why list and counts diverge
        # ("Action 110 counted, 43 listed"): a per-account store sees only
        # its own JSON, missing every entry the classifier wrote globally.
        # Union the global file too. Account scoping is preserved
        # downstream by `get_by_account(account_id=…, email_ids=…)`.
        global_path = self._global_assignments_path()
        if global_path:
            try:
                with open(global_path, 'r', encoding='utf-8') as f:
                    global_data = json.load(f)
                items = (
                    global_data
                    if isinstance(global_data, list)
                    else global_data.get('assignments', [])
                )
                for entry in items:
                    if label_name in entry.get('labels', []):
                        eid = entry.get('email_id')
                        if eid:
                            json_ids.add(str(eid))
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            except Exception as _e:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "[label_store] global JSON read failed: %s", _e,
                )

        merged = sql_ids | json_ids
        if valid_email_ids is not None:
            merged &= valid_email_ids
        return list(merged)

    def bulk_remove_label(self, email_ids: set, label_name: str) -> int:
        """Retire un label de plusieurs emails en une seule opération JSON.

        Args:
            email_ids: Set d'email IDs à modifier.
            label_name: Label à retirer (ex: "Noise").

        Returns:
            Nombre d'assignments modifiés.
        """
        with self._assign_lock:
            # Work on the in-memory cache (source of truth) to avoid
            # race conditions with concurrent save_assignment calls.
            cache = self._load_assign_cache()
            modified = 0
            for eid in email_ids:
                a = cache.get(eid)
                if a and label_name in a.labels:
                    a.labels.remove(label_name)
                    modified += 1

            if modified > 0:
                data = [a.to_dict() for a in cache.values()]
                with open(self._assignments_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                # Cache is already updated in-place — no need to invalidate

            return modified

    # =========================================================================
    # Rules Markdown
    # =========================================================================

    def _update_rules_markdown(self) -> None:
        """Met à jour le fichier markdown des règles."""
        rules = self.get_rules()
        labels = self.get_labels()

        content = f"""# Règles de Labellisation Agentys

> Généré automatiquement le {datetime.now().strftime('%Y-%m-%d %H:%M')}
> Ces règles sont apprises des corrections utilisateur et définies manuellement.

## Labels disponibles

| Label | Description | Type |
|-------|-------------|------|
"""

        for label in labels:
            label_type = "Défaut" if label.is_default else "Custom"
            content += f"| {label.name} | {label.description[:50]}... | {label_type} |\n"

        content += f"""

## Règles actives ({len(rules)})

"""

        # Grouper par label
        rules_by_label: Dict[str, List[LabelingRule]] = {}
        for rule in rules:
            if rule.label_name not in rules_by_label:
                rules_by_label[rule.label_name] = []
            rules_by_label[rule.label_name].append(rule)

        if not rules_by_label:
            content += "_Aucune règle définie. Les règles seront apprises de vos corrections._\n"
        else:
            for label_name, label_rules in sorted(rules_by_label.items()):
                content += f"### {label_name}\n\n"

                for rule in sorted(label_rules, key=lambda r: -r.priority):
                    learned = " (apprise)" if rule.learned_from else ""
                    content += f"""- **{rule.condition_type}** = `{rule.condition_value}`{learned}
  - Confiance: {rule.confidence * 100:.0f}%
  - Utilisations: {rule.use_count}

"""

        content += """
## Comment ça marche

1. **Règles utilisateur** (priorité haute): Définies manuellement via l'API
2. **Règles apprises** (priorité moyenne): Extraites de vos corrections
3. **Classification IA** (fallback): Utilisée si aucune règle ne match

## Modifier les règles

- Via l'API: `POST /api/labels/rules`
- Ou corrigez les labels dans l'app, Agentys apprendra automatiquement
"""

        with open(self._rules_md_path, 'w', encoding='utf-8') as f:
            f.write(content)

    def get_rules_markdown(self) -> str:
        """Retourne le contenu du fichier markdown."""
        try:
            with open(self._rules_md_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            self._update_rules_markdown()
            with open(self._rules_md_path, 'r', encoding='utf-8') as f:
                return f.read()

    # =========================================================================
    # VIP / High Importance
    # =========================================================================

    def add_vip_sender(self, email_address: str, name: str = "") -> List[LabelingRule]:
        """Ajoute un expéditeur VIP (haute importance).

        Creates 1 rule:
        - sender → VIP (custom label, priority 90)

        The default label (Action/FYI/etc.) is determined by the LLM or
        built-in rules based on actual email content, NOT forced to Action.

        Auto-creates the VIP label if it doesn't exist.

        Returns list of created rules.
        """
        import uuid

        email_lower = email_address.lower()

        # Ensure the VIP custom label exists
        if not self.get_label("VIP"):
            vip_label = EmailLabel(
                name="VIP",
                color="#8b5cf6",  # Purple
                description="Contacts VIP — haute importance",
                is_default=False,
                is_favorite=True,
            )
            self.add_label(vip_label)

        # VIP custom label rule
        vip_rule = LabelingRule(
            rule_id=str(uuid.uuid4())[:8],
            label_name="VIP",
            condition_type="sender",
            condition_value=email_lower,
            priority=90,
            confidence=1.0,
        )
        self.add_rule(vip_rule)

        return [vip_rule]

    def get_vip_senders(self) -> List[str]:
        """Retourne la liste des expéditeurs VIP."""
        rules = self.get_rules()
        result = []
        for r in rules:
            if r.label_name == "VIP" and r.condition_type == "sender":
                result.append(r.condition_value)
        return result

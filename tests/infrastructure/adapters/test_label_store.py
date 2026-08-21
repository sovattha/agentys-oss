# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour app/infrastructure/adapters/label_store.py."""

import json
import os
import tempfile


from app.domain.entities.email_labels import (
    DefaultLabel,
    EmailLabel,
    LabelAssignment,
    LabelingRule,
)
from app.infrastructure.adapters.label_store import LabelStore


class TestLabelStoreInit:
    """Tests pour l'initialisation du LabelStore."""

    def test_creates_storage_directory(self):
        """Le store crée le répertoire de stockage s'il n'existe pas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = os.path.join(tmpdir, "labels_store")
            LabelStore(storage_dir=storage_path)

            assert os.path.exists(storage_path)
            assert os.path.isdir(storage_path)

    def test_creates_labels_json_with_defaults(self):
        """Le store crée labels.json avec les labels par défaut."""
        with tempfile.TemporaryDirectory() as tmpdir:
            LabelStore(storage_dir=tmpdir)

            labels_path = os.path.join(tmpdir, "labels.json")
            assert os.path.exists(labels_path)

            with open(labels_path, 'r') as f:
                data = json.load(f)

            assert len(data) == len(DefaultLabel)
            label_names = [lbl["name"] for lbl in data]
            assert "Action" in label_names
            assert "FYI" in label_names
            assert "Noise" in label_names

    def test_creates_empty_rules_json(self):
        """Le store crée rules.json vide."""
        with tempfile.TemporaryDirectory() as tmpdir:
            LabelStore(storage_dir=tmpdir)

            rules_path = os.path.join(tmpdir, "rules.json")
            assert os.path.exists(rules_path)

            with open(rules_path, 'r') as f:
                data = json.load(f)

            assert data == []

    def test_does_not_reinit_existing_labels(self):
        """Le store ne réinitialise pas les labels existants."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Créer un fichier labels.json custom
            labels_path = os.path.join(tmpdir, "labels.json")
            custom_labels = [{"name": "Custom", "color": "#FF0000", "is_default": False}]
            with open(labels_path, 'w') as f:
                json.dump(custom_labels, f)

            LabelStore(storage_dir=tmpdir)

            with open(labels_path, 'r') as f:
                data = json.load(f)

            assert len(data) == 1
            assert data[0]["name"] == "Custom"

    def test_does_not_reinit_existing_rules(self):
        """Le store ne réinitialise pas les règles existantes.

        Note: LabelStore.__post_init__ runs ``_purge_orphaned_rules`` which
        removes rules targeting labels that don't exist in the library.
        The fixture needs a label that matches the rule's ``label_name``
        so the rule isn't considered orphaned and purged away — otherwise
        we'd be testing the purge path, not the "preserve existing rules"
        path.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Label "Test" must exist for the rule targeting it to survive
            # the orphaned-rules purge on __post_init__.
            labels_path = os.path.join(tmpdir, "labels.json")
            with open(labels_path, 'w') as f:
                json.dump(
                    [{"name": "Test", "color": "#FF0000", "is_default": False}],
                    f,
                )

            rules_path = os.path.join(tmpdir, "rules.json")
            custom_rules = [{"rule_id": "1", "label_name": "Test", "condition_type": "sender", "condition_value": "test@test.com"}]
            with open(rules_path, 'w') as f:
                json.dump(custom_rules, f)

            LabelStore(storage_dir=tmpdir)

            with open(rules_path, 'r') as f:
                data = json.load(f)

            assert len(data) == 1
            assert data[0]["rule_id"] == "1"


class TestLabelStorePaths:
    """Tests pour les propriétés de chemins."""

    def test_labels_path(self):
        """_labels_path retourne le bon chemin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)
            assert store._labels_path == os.path.join(tmpdir, "labels.json")

    def test_rules_path(self):
        """_rules_path retourne le bon chemin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)
            assert store._rules_path == os.path.join(tmpdir, "rules.json")

    def test_assignments_path(self):
        """_assignments_path retourne le bon chemin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)
            assert store._assignments_path == os.path.join(tmpdir, "assignments.json")

    def test_rules_md_path(self):
        """_rules_md_path retourne le bon chemin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)
            assert store._rules_md_path == os.path.join(tmpdir, "RULES.md")


class TestGetLabels:
    """Tests pour get_labels()."""

    def test_returns_default_labels(self):
        """get_labels retourne les labels par défaut."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)
            labels = store.get_labels()

            assert len(labels) == 3
            names = [lbl.name for lbl in labels]
            assert "Action" in names
            assert "FYI" in names
            assert "Noise" in names

    def test_returns_custom_labels(self):
        """get_labels retourne les labels custom."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            custom_label = EmailLabel(name="Project", color="#00FF00", description="Project emails")
            store.add_label(custom_label)

            labels = store.get_labels()
            assert len(labels) == 4  # 3 defaults + 1 custom
            assert any(lbl.name == "Project" for lbl in labels)

    def test_returns_defaults_on_file_not_found(self):
        """get_labels retourne les defaults si le fichier n'existe pas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)
            # Supprimer le fichier
            os.remove(store._labels_path)

            labels = store.get_labels()
            assert len(labels) == len(DefaultLabel)

    def test_returns_defaults_on_json_decode_error(self):
        """get_labels retourne les defaults si le JSON est invalide."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)
            # Écrire du JSON invalide
            with open(store._labels_path, 'w') as f:
                f.write("not valid json")

            labels = store.get_labels()
            assert len(labels) == len(DefaultLabel)


class TestGetLabel:
    """Tests pour get_label()."""

    def test_returns_label_by_name(self):
        """get_label retourne le label correspondant."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            label = store.get_label("Action")

            assert label is not None
            assert label.name == "Action"

    def test_case_insensitive_search(self):
        """get_label est insensible à la casse."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            label1 = store.get_label("action")
            label2 = store.get_label("ACTION")
            label3 = store.get_label("AcTiOn")

            assert label1 is not None
            assert label2 is not None
            assert label3 is not None
            assert label1.name == label2.name == label3.name

    def test_returns_none_for_nonexistent(self):
        """get_label retourne None si le label n'existe pas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            label = store.get_label("NonExistent")

            assert label is None


class TestAddLabel:
    """Tests pour add_label()."""

    def test_adds_new_label(self):
        """add_label ajoute un nouveau label."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            new_label = EmailLabel(name="Project", color="#00FF00", description="Project emails")
            result = store.add_label(new_label)

            assert result is True
            labels = store.get_labels()
            assert any(lbl.name == "Project" for lbl in labels)

    def test_returns_false_for_duplicate_name(self):
        """add_label retourne False si le nom existe déjà."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            duplicate_label = EmailLabel(name="Action", color="#FF0000")
            result = store.add_label(duplicate_label)

            assert result is False

    def test_duplicate_check_is_case_insensitive(self):
        """La vérification de doublon est insensible à la casse."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            duplicate_label = EmailLabel(name="action", color="#FF0000")
            result = store.add_label(duplicate_label)

            assert result is False

    def test_persists_to_disk(self):
        """add_label persiste les changements sur disque."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            new_label = EmailLabel(name="Project", color="#00FF00")
            store.add_label(new_label)

            # Créer un nouveau store pour vérifier la persistance
            store2 = LabelStore(storage_dir=tmpdir)
            labels = store2.get_labels()
            assert any(lbl.name == "Project" for lbl in labels)


class TestUpdateLabel:
    """Tests pour update_label()."""

    def test_updates_existing_label(self):
        """update_label met à jour un label existant."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            new_label = EmailLabel(name="Project", color="#00FF00", description="Old desc")
            store.add_label(new_label)

            result = store.update_label("Project", {"description": "New desc"})

            assert result is True
            label = store.get_label("Project")
            assert label.description == "New desc"

    def test_case_insensitive_update(self):
        """update_label est insensible à la casse."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            new_label = EmailLabel(name="Project", color="#00FF00")
            store.add_label(new_label)

            result = store.update_label("project", {"color": "#FF0000"})

            assert result is True
            label = store.get_label("Project")
            assert label.color == "#FF0000"

    def test_returns_false_for_nonexistent(self):
        """update_label retourne False si le label n'existe pas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            result = store.update_label("NonExistent", {"color": "#FF0000"})

            assert result is False

    def test_partial_update(self):
        """update_label met à jour partiellement."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            new_label = EmailLabel(name="Project", color="#00FF00", description="Desc")
            store.add_label(new_label)

            store.update_label("Project", {"color": "#FF0000"})

            label = store.get_label("Project")
            assert label.color == "#FF0000"
            assert label.description == "Desc"  # Inchangé


class TestDeleteLabel:
    """Tests pour delete_label()."""

    def test_deletes_custom_label(self):
        """delete_label supprime un label custom."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            new_label = EmailLabel(name="Project", color="#00FF00")
            store.add_label(new_label)

            result = store.delete_label("Project")

            assert result == "deleted"
            label = store.get_label("Project")
            assert label is None

    def test_cannot_delete_default_label(self):
        """delete_label ne supprime pas les labels par défaut."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            result = store.delete_label("Action")

            assert result == "is_default"
            label = store.get_label("Action")
            assert label is not None

    def test_returns_not_found_for_nonexistent(self):
        """delete_label retourne 'not_found' si le label n'existe pas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            result = store.delete_label("NonExistent")

            assert result == "not_found"

    def test_case_insensitive_delete(self):
        """delete_label est insensible à la casse."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            new_label = EmailLabel(name="Project", color="#00FF00")
            store.add_label(new_label)

            result = store.delete_label("project")

            assert result == "deleted"
            label = store.get_label("Project")
            assert label is None


class TestGetRules:
    """Tests pour get_rules()."""

    def test_returns_empty_list_initially(self):
        """get_rules retourne une liste vide au départ."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)
            rules = store.get_rules()
            assert rules == []

    def test_returns_added_rules(self):
        """get_rules retourne les règles ajoutées."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule = LabelingRule(
                rule_id="1",
                label_name="Action",
                condition_type="sender",
                condition_value="boss@company.com"
            )
            store.add_rule(rule)

            rules = store.get_rules()
            assert len(rules) == 1
            assert rules[0].label_name == "Action"

    def test_returns_empty_on_file_not_found(self):
        """get_rules retourne vide si le fichier n'existe pas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)
            os.remove(store._rules_path)

            rules = store.get_rules()
            assert rules == []

    def test_returns_empty_on_json_decode_error(self):
        """get_rules retourne vide si le JSON est invalide."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)
            with open(store._rules_path, 'w') as f:
                f.write("not valid json")

            rules = store.get_rules()
            assert rules == []


class TestGetRulesForLabel:
    """Tests pour get_rules_for_label()."""

    def test_returns_rules_for_label(self):
        """get_rules_for_label retourne les règles du label."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule1 = LabelingRule(rule_id="1", label_name="Action", condition_type="sender", condition_value="a@b.com")
            rule2 = LabelingRule(rule_id="2", label_name="Read", condition_type="sender", condition_value="c@d.com")
            rule3 = LabelingRule(rule_id="3", label_name="Action", condition_type="subject", condition_value="urgent")

            store.add_rule(rule1)
            store.add_rule(rule2)
            store.add_rule(rule3)

            action_rules = store.get_rules_for_label("Action")

            assert len(action_rules) == 2
            assert all(r.label_name == "Action" for r in action_rules)

    def test_case_insensitive_search(self):
        """get_rules_for_label est insensible à la casse."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule = LabelingRule(rule_id="1", label_name="Action", condition_type="sender", condition_value="a@b.com")
            store.add_rule(rule)

            rules = store.get_rules_for_label("action")

            assert len(rules) == 1

    def test_returns_empty_for_no_match(self):
        """get_rules_for_label retourne vide si pas de match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rules = store.get_rules_for_label("NonExistent")

            assert rules == []


class TestAddRule:
    """Tests pour add_rule()."""

    def test_adds_new_rule(self):
        """add_rule ajoute une nouvelle règle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule = LabelingRule(
                rule_id="1",
                label_name="Action",
                condition_type="sender",
                condition_value="boss@company.com"
            )
            result = store.add_rule(rule)

            assert result is True
            rules = store.get_rules()
            assert len(rules) == 1

    def test_returns_false_for_duplicate(self):
        """add_rule retourne False pour une règle similaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule1 = LabelingRule(rule_id="1", label_name="Action", condition_type="sender", condition_value="a@b.com")
            rule2 = LabelingRule(rule_id="2", label_name="Action", condition_type="sender", condition_value="a@b.com")

            store.add_rule(rule1)
            result = store.add_rule(rule2)

            assert result is False
            rules = store.get_rules()
            assert len(rules) == 1

    def test_updates_confidence_if_higher(self):
        """add_rule met à jour la confiance si supérieure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule1 = LabelingRule(rule_id="1", label_name="Action", condition_type="sender", condition_value="a@b.com", confidence=0.5)
            rule2 = LabelingRule(rule_id="2", label_name="Action", condition_type="sender", condition_value="a@b.com", confidence=0.9)

            store.add_rule(rule1)
            store.add_rule(rule2)

            rules = store.get_rules()
            assert len(rules) == 1
            assert rules[0].confidence == 0.9

    def test_creates_rules_markdown(self):
        """add_rule crée le fichier RULES.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule = LabelingRule(rule_id="1", label_name="Action", condition_type="sender", condition_value="a@b.com")
            store.add_rule(rule)

            assert os.path.exists(store._rules_md_path)


class TestUpdateRule:
    """Tests pour update_rule()."""

    def test_updates_existing_rule(self):
        """update_rule met à jour une règle existante."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule = LabelingRule(rule_id="1", label_name="Action", condition_type="sender", condition_value="a@b.com", priority=50)
            store.add_rule(rule)

            result = store.update_rule("1", {"priority": 90})

            assert result is True
            rules = store.get_rules()
            assert rules[0].priority == 90

    def test_returns_false_for_nonexistent(self):
        """update_rule retourne False si la règle n'existe pas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            result = store.update_rule("nonexistent", {"priority": 90})

            assert result is False


class TestDeleteRule:
    """Tests pour delete_rule()."""

    def test_deletes_rule(self):
        """delete_rule supprime une règle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule = LabelingRule(rule_id="1", label_name="Action", condition_type="sender", condition_value="a@b.com")
            store.add_rule(rule)

            result = store.delete_rule("1")

            assert result is True
            rules = store.get_rules()
            assert len(rules) == 0

    def test_returns_false_for_nonexistent(self):
        """delete_rule retourne False si la règle n'existe pas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            result = store.delete_rule("nonexistent")

            assert result is False


class TestGetAssignments:
    """Tests pour get_assignments()."""

    def test_returns_empty_initially(self):
        """get_assignments retourne vide au départ."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            assignments = store.get_assignments()

            assert assignments == []

    def test_returns_saved_assignments(self):
        """get_assignments retourne les assignations sauvegardées."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            assignment = LabelAssignment(email_id="email-1", labels=["Action"])
            store.save_assignment(assignment)

            assignments = store.get_assignments()

            assert len(assignments) == 1
            assert assignments[0].email_id == "email-1"

    def test_respects_limit(self):
        """get_assignments respecte la limite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            for i in range(10):
                assignment = LabelAssignment(email_id=f"email-{i}", labels=["Action"])
                store.save_assignment(assignment)

            assignments = store.get_assignments(limit=5)

            assert len(assignments) == 5

    def test_returns_most_recent_with_limit(self):
        """get_assignments retourne les plus récents avec limite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            for i in range(10):
                assignment = LabelAssignment(email_id=f"email-{i}", labels=["Action"])
                store.save_assignment(assignment)

            assignments = store.get_assignments(limit=3)

            # Doit retourner les 3 derniers (email-7, email-8, email-9)
            assert assignments[0].email_id == "email-7"
            assert assignments[2].email_id == "email-9"

    def test_returns_empty_on_file_not_found(self):
        """get_assignments retourne vide si le fichier n'existe pas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            # Le fichier n'existe pas encore
            assignments = store.get_assignments()

            assert assignments == []

    def test_returns_empty_on_json_decode_error(self):
        """get_assignments retourne vide si le JSON est invalide."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            with open(store._assignments_path, 'w') as f:
                f.write("not valid json")

            assignments = store.get_assignments()

            assert assignments == []


class TestGetAssignment:
    """Tests pour get_assignment()."""

    def test_returns_assignment_for_email(self):
        """get_assignment retourne l'assignation pour un email."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            assignment = LabelAssignment(email_id="email-1", labels=["Action", "Read"])
            store.save_assignment(assignment)

            result = store.get_assignment("email-1")

            assert result is not None
            assert result.email_id == "email-1"
            assert "Action" in result.labels

    def test_returns_none_for_nonexistent(self):
        """get_assignment retourne None si l'email n'existe pas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            result = store.get_assignment("nonexistent")

            assert result is None

    def test_returns_most_recent_for_duplicate(self):
        """get_assignment retourne la plus récente pour un email."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            # Première assignation
            assignment1 = LabelAssignment(email_id="email-1", labels=["Read"])
            store.save_assignment(assignment1)

            # Mise à jour
            assignment2 = LabelAssignment(email_id="email-1", labels=["Action"])
            store.save_assignment(assignment2)

            result = store.get_assignment("email-1")

            assert "Action" in result.labels


class TestSaveAssignment:
    """Tests pour save_assignment()."""

    def test_saves_new_assignment(self):
        """save_assignment sauvegarde une nouvelle assignation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            assignment = LabelAssignment(email_id="email-1", labels=["Action"])
            store.save_assignment(assignment)

            result = store.get_assignment("email-1")

            assert result is not None
            assert result.labels == ["Action"]

    def test_updates_existing_assignment(self):
        """save_assignment met à jour une assignation existante."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            assignment1 = LabelAssignment(email_id="email-1", labels=["Read"])
            store.save_assignment(assignment1)

            assignment2 = LabelAssignment(email_id="email-1", labels=["Action"])
            store.save_assignment(assignment2)

            assignments = store.get_assignments()

            # Doit avoir une seule entrée mise à jour
            email_1_assignments = [a for a in assignments if a.email_id == "email-1"]
            assert len(email_1_assignments) == 1
            assert "Action" in email_1_assignments[0].labels

    def test_limits_to_10000_entries(self):
        """save_assignment limite à 10000 entrées."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write the file BEFORE creating the store so the eager cache
            # warm-up in __post_init__ picks up the pre-existing entries.
            assignments_path = os.path.join(tmpdir, "assignments.json")
            data = [{"email_id": f"email-{i}", "labels": ["Read"]} for i in range(10005)]
            with open(assignments_path, 'w') as f:
                json.dump(data, f)

            store = LabelStore(storage_dir=tmpdir)

            # Ajouter une nouvelle
            assignment = LabelAssignment(email_id="new-email", labels=["Action"])
            store.save_assignment(assignment)

            # Vérifier la limite
            with open(store._assignments_path, 'r') as f:
                saved_data = json.load(f)

            assert len(saved_data) == 10000

    def test_persists_to_disk(self):
        """save_assignment persiste sur disque."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            assignment = LabelAssignment(email_id="email-1", labels=["Action"])
            store.save_assignment(assignment)

            # Créer un nouveau store
            store2 = LabelStore(storage_dir=tmpdir)
            result = store2.get_assignment("email-1")

            assert result is not None


class TestRulesMarkdown:
    """Tests pour la génération du fichier RULES.md."""

    def test_creates_markdown_file(self):
        """_update_rules_markdown crée le fichier."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule = LabelingRule(rule_id="1", label_name="Action", condition_type="sender", condition_value="a@b.com")
            store.add_rule(rule)

            assert os.path.exists(store._rules_md_path)

    def test_contains_labels_section(self):
        """Le markdown contient la section des labels."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)
            store._update_rules_markdown()

            with open(store._rules_md_path, 'r') as f:
                content = f.read()

            assert "## Labels disponibles" in content
            assert "Action" in content
            assert "FYI" in content

    def test_contains_rules_section(self):
        """Le markdown contient la section des règles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule = LabelingRule(rule_id="1", label_name="Action", condition_type="sender", condition_value="boss@company.com")
            store.add_rule(rule)

            with open(store._rules_md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            assert "Règles actives" in content
            assert "### Action" in content
            assert "boss@company.com" in content

    def test_shows_no_rules_message(self):
        """Le markdown indique si aucune règle n'existe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)
            store._update_rules_markdown()

            with open(store._rules_md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            assert "Aucune règle définie" in content

    def test_get_rules_markdown_creates_if_missing(self):
        """get_rules_markdown crée le fichier s'il n'existe pas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            # S'assurer que le fichier n'existe pas
            if os.path.exists(store._rules_md_path):
                os.remove(store._rules_md_path)

            content = store.get_rules_markdown()

            assert content is not None
            assert "Règles de Labellisation" in content

    def test_get_rules_markdown_returns_existing(self):
        """get_rules_markdown retourne le contenu existant."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule = LabelingRule(rule_id="1", label_name="Action", condition_type="sender", condition_value="test@test.com")
            store.add_rule(rule)

            content = store.get_rules_markdown()

            assert "test@test.com" in content


class TestVIPSenders:
    """Tests pour les fonctions VIP."""

    def test_add_vip_sender(self):
        """add_vip_sender ajoute un expéditeur VIP."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rules = store.add_vip_sender("ceo@company.com", "CEO")

            assert rules is not None
            assert len(rules) >= 1
            assert rules[0].condition_value == "ceo@company.com"
            assert rules[0].priority == 90

    def test_vip_sender_has_vip_label(self):
        """Un expéditeur VIP est associé au label VIP."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rules = store.add_vip_sender("ceo@company.com")

            assert rules[0].label_name == "VIP"

    def test_vip_sender_is_lowercased(self):
        """L'adresse VIP est mise en minuscules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rules = store.add_vip_sender("CEO@COMPANY.COM")

            assert rules[0].condition_value == "ceo@company.com"

    def test_get_vip_senders(self):
        """get_vip_senders retourne la liste des VIP."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            store.add_vip_sender("ceo@company.com")
            store.add_vip_sender("cto@company.com")

            vips = store.get_vip_senders()

            assert len(vips) == 2
            assert "ceo@company.com" in vips
            assert "cto@company.com" in vips

    def test_get_vip_senders_filters_by_priority(self):
        """get_vip_senders ne retourne que les règles haute priorité."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            # VIP (haute priorité)
            store.add_vip_sender("ceo@company.com")

            # Non-VIP (priorité normale)
            normal_rule = LabelingRule(
                rule_id="2",
                label_name=DefaultLabel.ACTION.value,
                condition_type="sender",
                condition_value="coworker@company.com",
                priority=50
            )
            store.add_rule(normal_rule)

            vips = store.get_vip_senders()

            assert len(vips) == 1
            assert "ceo@company.com" in vips
            assert "coworker@company.com" not in vips

    def test_get_vip_senders_empty_initially(self):
        """get_vip_senders retourne vide au départ."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            vips = store.get_vip_senders()

            assert vips == []


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_unicode_in_label_name(self):
        """Les noms de labels supportent l'unicode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            label = EmailLabel(name="Projets français 日本語", color="#00FF00")
            result = store.add_label(label)

            assert result is True
            retrieved = store.get_label("Projets français 日本語")
            assert retrieved is not None

    def test_special_characters_in_condition(self):
        """Les conditions supportent les caractères spéciaux."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            rule = LabelingRule(
                rule_id="1",
                label_name="Action",
                condition_type="subject",
                condition_value=".*urgent.*|.*ASAP.*"
            )
            store.add_rule(rule)

            rules = store.get_rules()
            assert rules[0].condition_value == ".*urgent.*|.*ASAP.*"

    def test_empty_storage_dir_path(self):
        """Gestion d'un chemin de stockage problématique."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = os.path.join(tmpdir, "deep", "nested", "path")
            LabelStore(storage_dir=nested_path)

            assert os.path.exists(nested_path)

    def test_concurrent_operations(self):
        """Opérations séquentielles fonctionnent correctement."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            # Ajouter plusieurs labels et règles rapidement
            for i in range(10):
                label = EmailLabel(name=f"Label{i}", color="#FF0000")
                store.add_label(label)

                rule = LabelingRule(rule_id=str(i), label_name=f"Label{i}", condition_type="sender", condition_value=f"user{i}@test.com")
                store.add_rule(rule)

            labels = store.get_labels()
            rules = store.get_rules()

            # 3 par défaut + 10 custom
            assert len(labels) == 13
            assert len(rules) == 10

    def test_large_assignment_history(self):
        """Gestion d'un historique d'assignations volumineux."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LabelStore(storage_dir=tmpdir)

            # Créer 500 assignations
            for i in range(500):
                assignment = LabelAssignment(email_id=f"email-{i}", labels=["Action"])
                store.save_assignment(assignment)

            # Vérifier qu'on peut récupérer
            assignments = store.get_assignments(limit=100)
            assert len(assignments) == 100

            # Vérifier le total
            all_assignments = store.get_assignments(limit=1000)
            assert len(all_assignments) == 500

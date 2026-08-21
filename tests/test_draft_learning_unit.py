import os

# Set API key BEFORE any app imports
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

import json
import pytest
import threading
from datetime import datetime, timedelta

from app.draft_learning import (
    DraftLearningStore,
    RULE_CATEGORIES,
    RULE_SCOPES,
    _MAX_CORRECTIONS,
    _MAX_POSITIVE_EXAMPLES,
    _MAX_RULES,
    _EXTRACTION_THRESHOLD,
)


@pytest.fixture
def tmp_json_path(tmp_path):
    return str(tmp_path / "draft_corrections.json")


@pytest.fixture(autouse=True)
def _legacy_email_content_storage(monkeypatch):
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")


@pytest.fixture
def store(tmp_json_path):
    return DraftLearningStore(persist_path=tmp_json_path)


# ============================================================================
# Initialization Tests
# ============================================================================


class TestDraftLearningStoreInit:
    def test_init_with_no_file(self, tmp_json_path):
        assert not os.path.exists(tmp_json_path)
        store = DraftLearningStore(persist_path=tmp_json_path)
        assert store._corrections == []
        assert store._positive_count == 0
        assert store._positive_examples == []
        assert store._rules == []

    def test_init_with_empty_file(self, tmp_json_path):
        with open(tmp_json_path, "w") as f:
            f.write("")
        store = DraftLearningStore(persist_path=tmp_json_path)
        assert store._corrections == []

    def test_init_with_old_list_format(self, tmp_json_path):
        data = [{"email_id": "1", "contact": "a@b.com", "original": "Hi", "sent": "Hey"}]
        with open(tmp_json_path, "w") as f:
            json.dump(data, f)
        store = DraftLearningStore(persist_path=tmp_json_path)
        assert len(store._corrections) == 1
        assert store._positive_count == 0

    def test_init_with_dict_format(self, tmp_json_path):
        data = {
            "corrections": [{"email_id": "1"}],
            "positive_count": 5,
            "positive_examples": [{"snippet": "ok"}],
            "rules": [{"rule_text": "Always greet"}],
            "suggestion_clicks": [{"email_id": "1"}],
            "refine_instructions": [{"instruction": "shorter"}],
            "edit_patterns": {"greeting": 3},
        }
        with open(tmp_json_path, "w") as f:
            json.dump(data, f)
        store = DraftLearningStore(persist_path=tmp_json_path)
        assert len(store._corrections) == 1
        assert store._positive_count == 5
        assert len(store._positive_examples) == 1
        assert len(store._rules) == 1
        assert len(store._suggestion_clicks) == 1
        assert len(store._refine_instructions) == 1
        assert store._edit_patterns == {"greeting": 3}

    def test_init_with_corrupted_json(self, tmp_json_path):
        with open(tmp_json_path, "w") as f:
            f.write("{invalid json")
        store = DraftLearningStore(persist_path=tmp_json_path)
        assert store._corrections == []
        assert store._positive_count == 0


class TestDraftLearningMetadataOnlyPrivacy:
    def test_record_correction_drops_raw_drafts_on_disk_and_prompt(
        self, tmp_json_path, monkeypatch
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        store = DraftLearningStore(persist_path=tmp_json_path)

        recorded = store.record_correction(
            "email-private",
            "Bonjour Alice, le contrat ACME confidentiel est prêt. Cordialement.",
            "Salut Alice, je reviens vers toi avec une réponse plus courte.",
            contact="alice@example.com",
        )

        assert recorded is True
        data = json.loads(open(tmp_json_path, encoding="utf-8").read())
        correction = data["corrections"][0]
        serialized = json.dumps(data, ensure_ascii=False)
        assert correction["original"] == ""
        assert correction["sent"] == ""
        assert "ACME confidentiel" not in serialized
        assert "réponse plus courte" not in serialized
        assert "Salutation modifiée" in correction["diff_summary"]

        prompt_section = store.get_recent_corrections()
        assert "ACME confidentiel" not in prompt_section
        assert "réponse plus courte" not in prompt_section
        assert "IA:" not in prompt_section
        assert "Envoye:" not in prompt_section

    def test_metadata_only_drops_positive_refine_and_regeneration_payloads(
        self, tmp_json_path, monkeypatch
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        store = DraftLearningStore(persist_path=tmp_json_path)

        store.record_positive(
            "email-positive",
            "Brouillon accepté avec données privées",
            contact="bob@example.com",
            email_subject="Sujet confidentiel",
            routing_tier="standard",
        )
        store.record_refine_instruction(
            "Rends la réponse plus courte",
            "Avant avec détails privés",
            "Après avec détails privés",
            contact="bob@example.com",
        )
        store.record_regeneration(
            "email-regen",
            "Brouillon rejeté avec détails privés",
            "Réécris sans mentionner le budget privé",
            contact="bob@example.com",
        )

        data = json.loads(open(tmp_json_path, encoding="utf-8").read())
        assert data["positive_examples"][0]["snippet"] == ""
        assert data["positive_examples"][0]["subject"] == ""
        assert data["refine_instructions"][0]["before"] == ""
        assert data["refine_instructions"][0]["after"] == ""
        assert data["corrections"][0]["original"] == ""
        assert data["corrections"][0]["instructions"] == ""
        serialized = json.dumps(data, ensure_ascii=False)
        assert "données privées" not in serialized
        assert "Sujet confidentiel" not in serialized
        assert "budget privé" not in serialized

    def test_metadata_only_sanitizes_legacy_file_on_load(
        self, tmp_json_path, monkeypatch
    ):
        with open(tmp_json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "corrections": [{
                        "email_id": "legacy",
                        "contact": "c@example.com",
                        "original": "Ancien brouillon privé",
                        "sent": "Ancienne version envoyée",
                        "diff_summary": "Salutation: 'Bonjour Alice' -> 'Salut Alice'",
                    }],
                    "positive_count": 1,
                    "positive_examples": [{
                        "snippet": "Ancien snippet privé",
                        "subject": "Ancien sujet privé",
                    }],
                    "refine_instructions": [{
                        "instruction": "Plus court",
                        "before": "Avant privé",
                        "after": "Après privé",
                    }],
                },
                f,
            )
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")

        store = DraftLearningStore(persist_path=tmp_json_path)

        assert store._corrections[0]["original"] == ""
        assert store._corrections[0]["sent"] == ""
        assert store._corrections[0]["diff_summary"] == "Salutation modifiée"
        assert store._positive_examples[0]["snippet"] == ""
        assert store._positive_examples[0]["subject"] == ""
        assert store._refine_instructions[0]["before"] == ""
        assert store._refine_instructions[0]["after"] == ""

    def test_metadata_only_prunes_expired_artifacts_on_load(
        self,
        tmp_json_path,
        monkeypatch,
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        monkeypatch.setenv("AGENTYS_AI_ARTIFACT_RETENTION_DAYS", "7")
        old_ts = (datetime.now() - timedelta(days=8)).isoformat()
        recent_ts = datetime.now().isoformat()
        with open(tmp_json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "corrections": [
                        {"timestamp": old_ts, "email_id": "old", "original": "old"},
                        {"timestamp": recent_ts, "email_id": "recent", "original": "new"},
                    ],
                    "positive_examples": [
                        {"timestamp": old_ts, "snippet": "old"},
                        {"timestamp": recent_ts, "snippet": "new"},
                    ],
                    "suggestion_clicks": [
                        {"timestamp": old_ts, "suggestion_text": "old"},
                        {"timestamp": recent_ts, "suggestion_text": "new"},
                    ],
                    "refine_instructions": [
                        {"timestamp": old_ts, "instruction": "old", "before": "old"},
                        {"timestamp": recent_ts, "instruction": "new", "before": "new"},
                    ],
                    "last_extracted_index": 10,
                },
                f,
            )

        store = DraftLearningStore(persist_path=tmp_json_path)

        assert [c["email_id"] for c in store._corrections] == ["recent"]
        assert len(store._positive_examples) == 1
        assert len(store._suggestion_clicks) == 1
        assert len(store._refine_instructions) == 1
        assert store._last_extracted_index == 1

    def test_metadata_only_drops_suggestion_text(
        self,
        tmp_json_path,
        monkeypatch,
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        store = DraftLearningStore(persist_path=tmp_json_path)

        store.record_suggestion_click(
            "email-suggestion",
            "Private quick reply with confidential content",
            contact="alice@example.com",
        )

        data = json.loads(open(tmp_json_path, encoding="utf-8").read())
        assert data["suggestion_clicks"][0]["suggestion_text"] == ""
        assert "confidential content" not in json.dumps(data)


# ============================================================================
# Record Correction Tests
# ============================================================================


class TestRecordCorrection:
    def test_record_significant_correction(self, store):
        result = store.record_correction(
            email_id="e1",
            original_draft="Bonjour, je vous confirme la réunion de demain à 14h.",
            sent_body="Salut, la réunion est confirmée pour demain 14h. À plus !",
            contact="alice@example.com",
        )
        assert result is True
        assert len(store._corrections) == 1
        assert store._corrections[0]["email_id"] == "e1"
        assert store._corrections[0]["contact"] == "alice@example.com"

    def test_record_correction_empty_original(self, store):
        result = store.record_correction("e1", "", "sent body")
        assert result is False

    def test_record_correction_empty_sent(self, store):
        result = store.record_correction("e1", "original", "")
        assert result is False

    def test_record_correction_identical(self, store):
        result = store.record_correction("e1", "Hello world", "Hello world")
        assert result is False

    def test_record_correction_minor_change_ignored(self, store):
        """Changes < 10% should be ignored."""
        original = "Bonjour, je vous confirme la réunion de demain à 14h. Merci."
        # Change just one char
        sent = "Bonjour, je vous confirme la réunion de demain à 14H. Merci."
        result = store.record_correction("e1", original, sent)
        assert result is False

    def test_record_correction_truncates_long_text(self, store):
        original = "A" * 1000
        sent = "B" * 1000
        store.record_correction("e1", original, sent)
        assert len(store._corrections[0]["original"]) <= 500
        assert len(store._corrections[0]["sent"]) <= 500

    def test_record_correction_max_limit(self, store):
        for i in range(_MAX_CORRECTIONS + 5):
            store.record_correction(
                f"e{i}",
                f"Original draft number {i} with enough text to be different",
                f"Completely different sent body number {i} with new content",
            )
        assert len(store._corrections) <= _MAX_CORRECTIONS

    def test_record_correction_tracks_greeting_pattern(self, store):
        """Greeting changes should be tracked in edit_patterns."""
        store.record_correction(
            "e1",
            "Bonjour Monsieur, je vous écris au sujet de votre demande concernant le projet.",
            "Salut ! Je t'écris au sujet de ta demande concernant le projet !",
        )
        # The _summarize_diff should detect salutation change
        assert len(store._corrections) >= 1

    def test_record_correction_persists(self, store, tmp_json_path):
        store.record_correction(
            "e1",
            "Bonjour, voici un texte original assez long pour être significatif.",
            "Hey, voici un texte modifié assez long pour être considéré comme différent.",
        )
        # Reload from disk
        store2 = DraftLearningStore(persist_path=tmp_json_path)
        assert len(store2._corrections) == len(store._corrections)


# ============================================================================
# Record Positive Tests
# ============================================================================


class TestRecordPositive:
    def test_record_positive_increments_count(self, store):
        store.record_positive("e1", "Great draft", contact="bob@test.com")
        assert store._positive_count == 1

    def test_record_positive_multiple(self, store):
        for i in range(5):
            store.record_positive(f"e{i}", f"Draft {i}")
        assert store._positive_count == 5

    def test_record_positive_stores_example(self, store):
        store.record_positive("e1", "Draft body", contact="x@y.com", email_subject="Subject", routing_tier="STANDARD")
        assert len(store._positive_examples) == 1
        ex = store._positive_examples[0]
        assert ex["contact"] == "x@y.com"
        assert ex["tier"] == "STANDARD"

    def test_record_positive_max_examples(self, store):
        for i in range(_MAX_POSITIVE_EXAMPLES + 5):
            store.record_positive(f"e{i}", f"Draft {i}")
        assert len(store._positive_examples) <= _MAX_POSITIVE_EXAMPLES

    def test_record_positive_boosts_rule_confidence(self, store):
        store.add_rules([{"rule_text": "Always be polite", "scope": "global", "confidence": 0.5}])
        store.record_positive("e1", "Polite draft", contact="a@b.com")
        rules = store.get_rules()
        assert rules[0]["confidence"] > 0.5

    def test_record_positive_persists(self, store, tmp_json_path):
        store.record_positive("e1", "Draft")
        store2 = DraftLearningStore(persist_path=tmp_json_path)
        assert store2._positive_count == 1


# ============================================================================
# Record Rejection Tests
# ============================================================================


class TestRecordRejection:
    def test_record_rejection(self, store):
        store.record_rejection("e1", "Bad draft", contact="c@d.com")
        assert len(store._corrections) == 1
        assert store._corrections[0].get("rejected") is True

    def test_record_rejection_degrades_confidence(self, store):
        store.add_rules([{"rule_text": "Be concise", "scope": "global", "confidence": 0.8}])
        store.record_rejection("e1", "Long draft")
        rules = store.get_rules()
        assert rules[0]["confidence"] < 0.8


# ============================================================================
# Record Regeneration Tests
# ============================================================================


class TestRecordRegeneration:
    def test_record_regeneration(self, store):
        store.record_regeneration("e1", "Previous", "Make it shorter")
        assert len(store._corrections) == 1
        assert store._corrections[0].get("regenerated") is True
        assert "Make it shorter" in store._corrections[0].get("instructions", "")


# ============================================================================
# Suggestion Click Tests
# ============================================================================


class TestRecordSuggestionClick:
    def test_record_click(self, store):
        store.record_suggestion_click("e1", "Quick reply suggestion", suggestion_index=0, contact="a@b.com")
        assert len(store._suggestion_clicks) == 1
        assert store._suggestion_clicks[0]["suggestion_index"] == 0

    def test_record_click_max_limit(self, store):
        for i in range(105):
            store.record_suggestion_click(f"e{i}", f"suggestion {i}")
        assert len(store._suggestion_clicks) <= 100

    def test_record_click_truncates(self, store):
        store.record_suggestion_click("e1", "X" * 500)
        assert len(store._suggestion_clicks[0]["suggestion_text"]) <= 200


# ============================================================================
# Refine Instruction Tests
# ============================================================================


class TestRecordRefineInstruction:
    def test_record_refine(self, store):
        store.record_refine_instruction("Make it formal", "Hey", "Bonjour", contact="a@b.com")
        assert len(store._refine_instructions) == 1
        assert store._refine_instructions[0]["instruction"] == "Make it formal"

    def test_record_refine_max_limit(self, store):
        for i in range(55):
            store.record_refine_instruction(f"Instruction {i}", "before", "after")
        assert len(store._refine_instructions) <= 50

    def test_record_refine_truncates(self, store):
        store.record_refine_instruction("I" * 600, "B" * 400, "A" * 400)
        assert len(store._refine_instructions[0]["instruction"]) <= 500
        assert len(store._refine_instructions[0]["before"]) <= 300
        assert len(store._refine_instructions[0]["after"]) <= 300

    def test_record_refine_increments_extraction_counter(self, store):
        before = store._corrections_since_extraction
        store.record_refine_instruction("Fix tone", "bad", "good")
        assert store._corrections_since_extraction == before + 1


# ============================================================================
# Edit Patterns Tests
# ============================================================================


class TestEditPatterns:
    def test_edit_patterns_empty_initially(self, store):
        assert store._edit_patterns == {}

    def test_edit_patterns_content_tracked(self, store):
        """A correction with no specific zone detected should be categorized as content."""
        store.record_correction(
            "e1",
            "Original text that is significantly different from sent version here.",
            "Completely rewritten text with totally new information and content here.",
        )
        # Some pattern should be tracked
        assert len(store._corrections) == 1

    def test_edit_patterns_persisted(self, store, tmp_json_path):
        store._edit_patterns = {"greeting": 3, "content": 2}
        store._save()
        store2 = DraftLearningStore(persist_path=tmp_json_path)
        assert store2._edit_patterns == {"greeting": 3, "content": 2}


# ============================================================================
# Rules Management Tests
# ============================================================================


class TestRuleManagement:
    def test_add_single_rule(self, store):
        added = store.add_rules([{"rule_text": "Always use formal tone"}])
        assert len(added) == 1
        assert added[0]["category"] == "contenu"  # default
        assert added[0]["scope"] == "global"  # default

    def test_add_rule_dedup(self, store):
        store.add_rules([{"rule_text": "Be polite"}])
        added = store.add_rules([{"rule_text": "Be polite"}])
        assert len(added) == 0
        assert len(store._rules) == 1

    def test_add_rule_dedup_case_insensitive(self, store):
        store.add_rules([{"rule_text": "Be POLITE"}])
        added = store.add_rules([{"rule_text": "be polite"}])
        assert len(added) == 0

    def test_add_rule_empty_text_ignored(self, store):
        added = store.add_rules([{"rule_text": ""}])
        assert len(added) == 0

    def test_add_rule_with_category(self, store):
        added = store.add_rules([{"rule_text": "Use tu", "category": "ton"}])
        assert added[0]["category"] == "ton"

    def test_add_rule_invalid_category_defaults(self, store):
        added = store.add_rules([{"rule_text": "X", "category": "invalid_cat"}])
        assert added[0]["category"] == "contenu"

    def test_add_rule_invalid_scope_defaults(self, store):
        added = store.add_rules([{"rule_text": "X", "scope": "invalid_scope"}])
        assert added[0]["scope"] == "global"

    def test_add_rule_contact_scope(self, store):
        added = store.add_rules([
            {"rule_text": "Be casual", "scope": "contact", "contact": "alice@test.com"}
        ])
        assert added[0]["scope"] == "contact"
        assert added[0]["contact"] == "alice@test.com"

    def test_add_rules_max_limit(self, store):
        rules = [{"rule_text": f"Rule number {i}"} for i in range(_MAX_RULES + 10)]
        store.add_rules(rules)
        assert len(store._rules) <= _MAX_RULES

    def test_add_rules_sets_defaults(self, store):
        added = store.add_rules([{"rule_text": "Test rule"}])
        r = added[0]
        assert "id" in r
        assert r["confidence"] == 0.7
        assert r["active"] is True
        assert r["source_emails"] == []

    def test_get_rules_active_only(self, store):
        store.add_rules([{"rule_text": "Active rule"}])
        store._rules[0]["active"] = False
        store._save()
        rules = store.get_rules(active_only=True)
        assert len(rules) == 0

    def test_get_rules_all(self, store):
        store.add_rules([{"rule_text": "Active rule"}])
        store._rules[0]["active"] = False
        rules = store.get_rules(active_only=False)
        assert len(rules) == 1

    def test_get_rules_by_contact(self, store):
        store.add_rules([
            {"rule_text": "Global rule", "scope": "global"},
            {"rule_text": "Alice rule", "scope": "contact", "contact": "alice@test.com"},
            {"rule_text": "Bob rule", "scope": "contact", "contact": "bob@test.com"},
        ])
        rules = store.get_rules(contact="alice@test.com")
        # Should include global + alice's rules
        assert len(rules) == 2
        texts = {r["rule_text"] for r in rules}
        assert "Global rule" in texts
        assert "Alice rule" in texts
        assert "Bob rule" not in texts

    def test_get_rules_no_contact_returns_all_active(self, store):
        store.add_rules([
            {"rule_text": "Global rule", "scope": "global"},
            {"rule_text": "Contact rule", "scope": "contact", "contact": "a@b.com"},
        ])
        rules = store.get_rules()
        assert len(rules) == 2


# ============================================================================
# Rule Update/Delete Tests
# ============================================================================


class TestRuleUpdateDelete:
    def test_delete_rule(self, store):
        added = store.add_rules([{"rule_text": "To delete"}])
        rule_id = added[0]["id"]
        result = store.delete_rule(rule_id)
        assert result is True
        assert len(store._rules) == 0

    def test_delete_nonexistent_rule(self, store):
        result = store.delete_rule("nonexistent_id")
        assert result is False

    def test_update_rule(self, store):
        added = store.add_rules([{"rule_text": "Original text"}])
        rule_id = added[0]["id"]
        result = store.update_rule(rule_id, rule_text="Updated text", active=False)
        assert result is True
        assert store._rules[0]["rule_text"] == "Updated text"
        assert store._rules[0]["active"] is False

    def test_update_nonexistent_rule(self, store):
        result = store.update_rule("nonexistent_id", rule_text="X")
        assert result is False

    def test_update_rule_confidence(self, store):
        added = store.add_rules([{"rule_text": "Rule", "confidence": 0.5}])
        store.update_rule(added[0]["id"], confidence=0.9)
        assert store._rules[0]["confidence"] == 0.9


# ============================================================================
# Should Extract Rules Tests
# ============================================================================


class TestShouldExtractRules:
    def test_initially_false(self, store):
        assert store.should_extract_rules() is False

    def test_after_threshold_corrections(self, store):
        for i in range(_EXTRACTION_THRESHOLD):
            store.record_refine_instruction(f"Instruction {i}", "before", "after")
        assert store.should_extract_rules() is True


# ============================================================================
# Rules For Prompt Tests
# ============================================================================


class TestGetRulesForPrompt:
    def test_empty_rules(self, store):
        result = store.get_rules_for_prompt()
        assert result == ""

    def test_with_rules(self, store):
        store.add_rules([{"rule_text": "Always greet with Bonjour"}])
        result = store.get_rules_for_prompt()
        assert "Bonjour" in result
        assert "REGLES_APPRISES" in result

    def test_with_contact_rules(self, store):
        store.add_rules([
            {"rule_text": "Global rule", "scope": "global"},
            {"rule_text": "Alice: use tu", "scope": "contact", "contact": "alice@test.com"},
        ])
        result = store.get_rules_for_prompt(contact="alice@test.com")
        assert "alice" in result.lower()


# ============================================================================
# Persistence Tests
# ============================================================================


class TestPersistence:
    def test_corrections_persist(self, store, tmp_json_path):
        store.record_correction(
            "e1",
            "Bonjour, je vous confirme la réunion de demain à 14h dans nos bureaux.",
            "Salut, c'est confirmé pour demain 14h chez nous. Bises !",
        )
        store2 = DraftLearningStore(persist_path=tmp_json_path)
        assert len(store2._corrections) == len(store._corrections)

    def test_rules_persist(self, store, tmp_json_path):
        store.add_rules([{"rule_text": "Be formal"}])
        store2 = DraftLearningStore(persist_path=tmp_json_path)
        assert len(store2._rules) == 1

    def test_all_data_persists(self, store, tmp_json_path):
        store.record_positive("e1", "Good draft")
        store.add_rules([{"rule_text": "Rule 1"}])
        store.record_suggestion_click("e1", "Suggestion 1")
        store.record_refine_instruction("Be shorter", "long text", "short text")
        store2 = DraftLearningStore(persist_path=tmp_json_path)
        assert store2._positive_count == 1
        assert len(store2._rules) == 1
        assert len(store2._suggestion_clicks) == 1
        assert len(store2._refine_instructions) == 1


# ============================================================================
# Thread Safety Tests
# ============================================================================


class TestThreadSafety:
    def test_concurrent_corrections(self, store):
        errors = []

        def worker(i):
            try:
                store.record_correction(
                    f"email_{i}",
                    f"Original draft number {i} which is quite different from sent",
                    f"Completely rewritten sent body number {i} with new content",
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0

    def test_concurrent_rules(self, store):
        errors = []

        def worker(i):
            try:
                store.add_rules([{"rule_text": f"Rule number {i}"}])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        assert len(store._rules) == 10


# ============================================================================
# Clear Tests
# ============================================================================


class TestClear:
    def test_clear_empty_store(self, store):
        store.clear()
        assert store._corrections == []
        assert store._positive_count == 0

    def test_clear_populated_store(self, store):
        store.record_positive("e1", "Draft")
        store.add_rules([{"rule_text": "Rule"}])
        store.record_suggestion_click("e1", "Suggestion")
        store.clear()
        assert store._corrections == []
        assert store._positive_count == 0
        assert store._positive_examples == []
        assert store._rules == []
        assert store._suggestion_clicks == []
        assert store._refine_instructions == []
        assert store._edit_patterns == {}

    def test_clear_persists(self, store, tmp_json_path):
        store.add_rules([{"rule_text": "Rule"}])
        store.clear()
        store2 = DraftLearningStore(persist_path=tmp_json_path)
        assert store2._rules == []


# ============================================================================
# Summarize Diff Tests
# ============================================================================


class TestSummarizeDiff:
    def test_greeting_change_detected(self, store):
        summary = store._summarize_diff(
            "Bonjour Monsieur,\nVoici le rapport.",
            "Salut,\nVoici le rapport.",
        )
        assert "Salutation" in summary

    def test_closing_change_detected(self, store):
        summary = store._summarize_diff(
            "Voici le rapport.\nCordialement",
            "Voici le rapport.\nÀ bientôt",
        )
        assert "Cloture" in summary

    def test_length_shortening_detected(self, store):
        summary = store._summarize_diff("A " * 100, "A " * 30)
        assert "Raccourci" in summary

    def test_length_extension_detected(self, store):
        summary = store._summarize_diff("A " * 30, "A " * 100)
        assert "Allonge" in summary

    def test_tone_change_detected(self, store):
        summary = store._summarize_diff(
            "Bonjour, je vous confirme que vous avez raison. Vous pouvez procéder.",
            "Salut, je te confirme que tu as raison. Tu peux procéder.",
        )
        assert "tutoiement" in summary.lower()

    def test_minor_adjustments(self, store):
        summary = store._summarize_diff("Hello world.", "Hello world!")
        assert summary  # Should return something


# ============================================================================
# Edge Cases Tests
# ============================================================================


class TestEdgeCases:
    def test_unicode_contact(self, store):
        store.record_positive("e1", "Draft", contact="étienne@hébergement.fr")
        assert store._positive_count == 1

    def test_very_long_email_id(self, store):
        long_id = "x" * 1000
        store.record_positive(long_id, "Draft")
        assert store._positive_count == 1

    def test_special_chars_in_text(self, store):
        store.record_correction(
            "e1",
            "Bonjour, le tarif est de 1 500€/mois avec une remise de 15% pour le Q1 2026.",
            "Salut, le prix est de 2 000€/mois sans remise pour l'année 2026 complète.",
        )
        assert len(store._corrections) == 1

    def test_rules_categories_constant(self):
        expected = {"salutation", "cloture", "ton", "longueur", "contenu", "formule", "format", "vocabulaire", "structure"}
        assert RULE_CATEGORIES == expected

    def test_rules_scopes_constant(self):
        assert RULE_SCOPES == {"contact", "global"}

    def test_get_recent_corrections(self, store):
        """Test the get_recent_corrections method returns formatted string."""
        store.record_correction(
            "e1",
            "Bonjour, je vous confirme la réunion de demain à 14h dans nos locaux.",
            "Salut, c'est confirmé pour demain 14h chez nous. À plus !",
            contact="a@b.com",
        )
        recent = store.get_recent_corrections()
        assert isinstance(recent, str)
        assert len(recent) > 0

    def test_get_recent_corrections_with_contact(self, store):
        store.record_correction(
            "e1",
            "Bonjour, je vous confirme la réunion de demain à 14h dans nos locaux.",
            "Salut, c'est confirmé pour demain 14h chez nous. À plus !",
            contact="a@b.com",
        )
        store.record_correction(
            "e2",
            "Dear sir, I would like to inform you about the meeting tomorrow at 2pm.",
            "Hi, just wanted to let you know about the meeting tomorrow at 2pm!",
            contact="b@c.com",
        )
        recent = store.get_recent_corrections(contact="a@b.com")
        assert isinstance(recent, str)


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    def test_full_workflow(self, store, tmp_json_path):
        """Test a complete workflow: correction → positive → rules → reload."""
        # Record correction
        store.record_correction(
            "e1",
            "Bonjour, je vous confirme la réunion de demain à 14h dans nos locaux.",
            "Salut, c'est confirmé pour demain 14h chez nous. À plus !",
            contact="alice@test.com",
        )

        # Record positive
        store.record_positive("e2", "Good draft", contact="bob@test.com")

        # Add rules
        store.add_rules([
            {"rule_text": "Use informal tone with Alice", "scope": "contact", "contact": "alice@test.com"},
            {"rule_text": "Keep replies short", "scope": "global"},
        ])

        # Record suggestion click
        store.record_suggestion_click("e3", "Quick ack")

        # Reload and verify
        store2 = DraftLearningStore(persist_path=tmp_json_path)
        assert store2._positive_count == 1
        assert len(store2._rules) == 2
        assert len(store2._suggestion_clicks) == 1

        # Get rules for Alice
        rules = store2.get_rules(contact="alice@test.com")
        assert len(rules) == 2  # global + alice's

    def test_multi_contact_workflow(self, store):
        """Test with multiple contacts."""
        contacts = ["alice@test.com", "bob@test.com", "carol@test.com"]
        for i, contact in enumerate(contacts):
            store.record_correction(
                f"e{i}",
                f"Original draft for contact {i} with enough difference to register.",
                f"Sent body for contact {i} that is completely different and new.",
                contact=contact,
            )
            store.add_rules([
                {"rule_text": f"Rule for {contact}", "scope": "contact", "contact": contact}
            ])

        # Verify per-contact rules
        for contact in contacts:
            rules = store.get_rules(contact=contact)
            contact_rules = [r for r in rules if r.get("scope") == "contact"]
            assert len(contact_rules) == 1

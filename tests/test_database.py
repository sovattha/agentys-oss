# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module de base de données SQLite.

Couvre:
- Database (connexion, transactions)
- ProcessedEmailsRepository
- DraftHistoryRepository
- SentEmailsRepository
- CostTrackingRepository
- AuditLogRepository
- TaskRepository
"""

import pytest
import threading
from datetime import datetime, timedelta

from app.infrastructure.database import (
    Database,
    ProcessedEmailsRepository,
    DraftHistoryRepository,
    SentEmailsRepository,
    CostTrackingRepository,
    AuditLogRepository,
    TaskRepository,
)
from app.agents import ExtractedTask


@pytest.fixture
def temp_db(tmp_path):
    """Crée une base de données temporaire pour les tests."""
    db_path = tmp_path / "test.db"
    # Reset class state for each test
    Database._initialized = False
    Database._local = threading.local()
    db = Database(db_path)
    # Create the accounts table required by FK constraints in draft_history
    db.execute("CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY, email TEXT)")
    db.execute("INSERT OR IGNORE INTO accounts (id, email) VALUES (1, 'test@test.com')")
    db.commit()
    yield db
    db.close()


class TestDatabase:
    """Tests pour la classe Database."""

    def test_init_creates_database(self, tmp_path):
        """L'initialisation crée le fichier de base de données."""
        db_path = tmp_path / "new_test.db"
        Database._initialized = False
        Database._local = threading.local()

        db = Database(db_path)

        assert db_path.exists()
        db.close()

    def test_schema_creates_all_tables(self, temp_db):
        """Le schéma crée toutes les tables nécessaires."""
        tables = temp_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        table_names = [row['name'] for row in tables]

        expected_tables = [
            'audit_log',
            'cost_tracking',
            'draft_history',
            'extracted_tasks',
            'learned_patterns',
            'processed_emails',
            'prompt_adjustments',
            'sent_emails',
        ]

        for table in expected_tables:
            assert table in table_names, f"Table {table} manquante"

    def test_execute_and_commit(self, temp_db):
        """Execute et commit fonctionnent correctement."""
        temp_db.execute(
            "INSERT INTO processed_emails (id) VALUES (?)",
            ("test-id",)
        )
        temp_db.commit()

        result = temp_db.fetchone(
            "SELECT id FROM processed_emails WHERE id = ?",
            ("test-id",)
        )

        assert result is not None
        assert result['id'] == "test-id"

    def test_transaction_commit(self, temp_db):
        """Les transactions sont correctement committées."""
        with temp_db.transaction():
            temp_db.execute(
                "INSERT INTO processed_emails (id) VALUES (?)",
                ("tx-test",)
            )

        result = temp_db.fetchone(
            "SELECT id FROM processed_emails WHERE id = ?",
            ("tx-test",)
        )

        assert result is not None

    def test_transaction_rollback_on_error(self, temp_db):
        """Les transactions sont rollback en cas d'erreur."""
        try:
            with temp_db.transaction():
                temp_db.execute(
                    "INSERT INTO processed_emails (id) VALUES (?)",
                    ("rollback-test",)
                )
                raise ValueError("Test error")
        except ValueError:
            pass

        result = temp_db.fetchone(
            "SELECT id FROM processed_emails WHERE id = ?",
            ("rollback-test",)
        )

        assert result is None

    def test_fetchall(self, temp_db):
        """fetchall retourne toutes les lignes."""
        for i in range(5):
            temp_db.execute(
                "INSERT INTO processed_emails (id) VALUES (?)",
                (f"email-{i}",)
            )
        temp_db.commit()

        results = temp_db.fetchall("SELECT id FROM processed_emails")

        assert len(results) == 5

    def test_thread_safety(self, tmp_path):
        """La base de données est thread-safe."""
        db_path = tmp_path / "thread_test.db"
        Database._initialized = False
        Database._local = threading.local()

        results = []
        errors = []

        def worker(worker_id):
            try:
                db = Database(db_path)
                for i in range(10):
                    db.execute(
                        "INSERT INTO processed_emails (id) VALUES (?)",
                        (f"worker-{worker_id}-{i}",)
                    )
                    db.commit()
                results.append(True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 3
        assert len(errors) == 0


class TestProcessedEmailsRepository:
    """Tests pour ProcessedEmailsRepository."""

    def test_mark_processed(self, temp_db):
        """mark_processed ajoute un email."""
        repo = ProcessedEmailsRepository(temp_db)

        repo.mark_processed("email-123")

        assert repo.is_processed("email-123")

    def test_is_processed_false_for_new(self, temp_db):
        """is_processed retourne False pour un email non traité."""
        repo = ProcessedEmailsRepository(temp_db)

        assert not repo.is_processed("unknown-email")

    def test_count(self, temp_db):
        """count retourne le bon nombre."""
        repo = ProcessedEmailsRepository(temp_db)

        repo.mark_processed("email-1")
        repo.mark_processed("email-2")
        repo.mark_processed("email-3")

        assert repo.count() == 3

    def test_get_all_ids(self, temp_db):
        """get_all_ids retourne tous les IDs."""
        repo = ProcessedEmailsRepository(temp_db)

        repo.mark_processed("email-a")
        repo.mark_processed("email-b")

        ids = repo.get_all_ids()

        assert set(ids) == {"email-a", "email-b"}

    def test_mark_processed_idempotent(self, temp_db):
        """mark_processed est idempotent."""
        repo = ProcessedEmailsRepository(temp_db)

        repo.mark_processed("email-dup")
        repo.mark_processed("email-dup")

        assert repo.count() == 1


class TestDraftHistoryRepository:
    """Tests pour DraftHistoryRepository."""

    def test_add(self, temp_db):
        """add ajoute un enregistrement."""
        repo = DraftHistoryRepository(temp_db)

        record_id = repo.add({
            "email_id": "email-456",
            "email_sender": "sender@example.com",
            "email_subject": "Test Subject",
            "draft_v1": "Draft content",
            "status": "V1",
        })

        assert record_id > 0

    def test_add_metadata_only_drops_content_columns(self, temp_db, monkeypatch):
        """Le cache historique ne garde pas les contenus en metadata-only."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        repo = DraftHistoryRepository(temp_db)

        repo.add({
            "email_id": "email-private",
            "email_body": "secret body",
            "draft_v1": "draft one",
            "critique": "private critique",
            "draft_final": "final answer",
            "status": "V1",
            "tokens_used": 42,
        })

        result = repo.get_by_email_id("email-private")

        assert result["email_body"] is None
        assert result["draft_v1"] is None
        assert result["critique"] is None
        assert result["draft_final"] is None
        assert result["status"] == "V1"
        assert result["tokens_used"] == 42

    def test_get_recent(self, temp_db):
        """get_recent retourne les enregistrements récents."""
        repo = DraftHistoryRepository(temp_db)

        for i in range(5):
            repo.add({
                "email_id": f"email-{i}",
                "email_subject": f"Subject {i}",
            })

        recent = repo.get_recent(limit=3)

        assert len(recent) == 3

    def test_get_by_email_id(self, temp_db):
        """get_by_email_id retourne le bon enregistrement."""
        repo = DraftHistoryRepository(temp_db)

        repo.add({
            "email_id": "find-me",
            "email_subject": "Target Subject",
        })

        result = repo.get_by_email_id("find-me")

        assert result is not None
        assert result['email_subject'] == "Target Subject"

    def test_get_by_email_id_not_found(self, temp_db):
        """get_by_email_id retourne None si non trouvé."""
        repo = DraftHistoryRepository(temp_db)

        result = repo.get_by_email_id("unknown")

        assert result is None

    def test_update_feedback(self, temp_db):
        """update_feedback met à jour le feedback."""
        repo = DraftHistoryRepository(temp_db)

        repo.add({
            "email_id": "feedback-test",
            "email_subject": "Feedback Test",
        })

        repo.update_feedback("feedback-test", "Great draft!", 5)

        result = repo.get_by_email_id("feedback-test")
        assert result['feedback'] == "Great draft!"
        assert result['feedback_score'] == 5

    def test_get_stats(self, temp_db):
        """get_stats retourne les statistiques."""
        repo = DraftHistoryRepository(temp_db)

        repo.add({"email_id": "s1", "status": "V1", "tokens_used": 100})
        repo.add({"email_id": "s2", "status": "V2", "tokens_used": 200})
        repo.add({"email_id": "s3", "status": "V1", "tokens_used": 150})

        stats = repo.get_stats()

        assert stats['total'] == 3
        assert stats['validated_v1'] == 2
        assert stats['corrected_v2'] == 1
        assert stats['total_tokens'] == 450

    def test_get_by_category(self, temp_db):
        """get_by_category retourne le breakdown."""
        repo = DraftHistoryRepository(temp_db)

        repo.add({"email_id": "c1", "category": "NORMAL"})
        repo.add({"email_id": "c2", "category": "URGENT"})
        repo.add({"email_id": "c3", "category": "NORMAL"})

        breakdown = repo.get_by_category()

        assert breakdown["NORMAL"] == 2
        assert breakdown["URGENT"] == 1


class TestSentEmailsRepository:
    """Tests pour SentEmailsRepository."""

    def test_add(self, temp_db):
        """add ajoute un email envoyé."""
        repo = SentEmailsRepository(temp_db)

        repo.add({
            "id": "sent-1",
            "recipient": "recipient@example.com",
            "subject": "Test Subject",
        })

        rows = temp_db.fetchall("SELECT * FROM sent_emails")
        assert len(rows) == 1

    def test_add_metadata_only_drops_body_preview(self, temp_db, monkeypatch):
        """sent_emails ne doit pas retenir d'aperçu de body en metadata-only."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        repo = SentEmailsRepository(temp_db)

        repo.add({
            "id": "sent-private",
            "recipient": "recipient@example.com",
            "subject": "Test Subject",
            "body_preview": "PRIVATE BODY PREVIEW",
        })

        row = temp_db.fetchone(
            "SELECT body_preview FROM sent_emails WHERE id = ?",
            ("sent-private",),
        )
        assert row["body_preview"] == ""

    def test_get_pending_metadata_only_sanitizes_legacy_preview(
        self,
        temp_db,
        monkeypatch,
    ):
        """Les anciennes lignes sent_emails ne doivent pas réexposer le body."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        old_sent_at = (datetime.now() - timedelta(days=5)).isoformat()
        temp_db.execute("""
            INSERT INTO sent_emails (id, recipient, subject, body_preview, sent_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "legacy-sent",
            "test@example.com",
            "Subject",
            "LEGACY BODY PREVIEW",
            old_sent_at,
            "pending",
        ))
        temp_db.commit()

        repo = SentEmailsRepository(temp_db)
        pending = repo.get_pending(delay_days=3)

        assert pending[0]["body_preview"] == ""

    def test_get_pending(self, temp_db):
        """get_pending retourne les emails en attente."""
        repo = SentEmailsRepository(temp_db)

        # Email envoyé il y a 5 jours
        temp_db.execute("""
            INSERT INTO sent_emails (id, recipient, sent_at, status)
            VALUES (?, ?, ?, ?)
        """, (
            "old-email",
            "test@example.com",
            (datetime.now() - timedelta(days=5)).isoformat(),
            "pending"
        ))
        temp_db.commit()

        pending = repo.get_pending(delay_days=3)

        assert len(pending) == 1
        assert pending[0]['id'] == "old-email"

    def test_mark_replied(self, temp_db):
        """mark_replied met à jour le statut."""
        repo = SentEmailsRepository(temp_db)

        repo.add({"id": "reply-test", "recipient": "test@example.com"})
        repo.mark_replied("reply-test")

        row = temp_db.fetchone(
            "SELECT status FROM sent_emails WHERE id = ?",
            ("reply-test",)
        )

        assert row['status'] == "replied"

    def test_mark_followup_sent(self, temp_db):
        """mark_followup_sent met à jour le statut."""
        repo = SentEmailsRepository(temp_db)

        repo.add({"id": "followup-test", "recipient": "test@example.com"})
        repo.mark_followup_sent("followup-test")

        row = temp_db.fetchone(
            "SELECT status FROM sent_emails WHERE id = ?",
            ("followup-test",)
        )

        assert row['status'] == "followup_sent"

    def test_get_stats(self, temp_db):
        """get_stats retourne les statistiques."""
        repo = SentEmailsRepository(temp_db)

        repo.add({"id": "s1", "recipient": "a@test.com"})
        repo.add({"id": "s2", "recipient": "b@test.com"})
        repo.mark_replied("s1")

        stats = repo.get_stats()

        assert stats['total'] == 2
        assert stats['replied'] == 1
        assert stats['pending'] == 1


class TestCostTrackingRepository:
    """Tests pour CostTrackingRepository."""

    def test_record_usage(self, temp_db):
        """record_usage enregistre l'utilisation."""
        repo = CostTrackingRepository(temp_db)

        repo.record_usage("claude-3", 100, 50, 0.005)

        rows = temp_db.fetchall("SELECT * FROM cost_tracking")
        assert len(rows) == 1

    def test_record_usage_aggregates(self, temp_db):
        """record_usage agrège les données par jour/modèle."""
        repo = CostTrackingRepository(temp_db)

        repo.record_usage("claude-3", 100, 50, 0.005)
        repo.record_usage("claude-3", 200, 100, 0.010)

        rows = temp_db.fetchall("SELECT * FROM cost_tracking")
        assert len(rows) == 1
        assert rows[0]['input_tokens'] == 300
        assert rows[0]['request_count'] == 2

    def test_get_daily_cost(self, temp_db):
        """get_daily_cost retourne le coût du jour."""
        repo = CostTrackingRepository(temp_db)

        repo.record_usage("claude-3", 100, 50, 0.005)
        repo.record_usage("gpt-4", 200, 100, 0.015)

        cost = repo.get_daily_cost()

        assert cost == pytest.approx(0.020, abs=0.001)

    def test_get_monthly_cost(self, temp_db):
        """get_monthly_cost retourne le coût du mois."""
        repo = CostTrackingRepository(temp_db)

        now = datetime.now()
        repo.record_usage("claude-3", 100, 50, 1.00)

        cost = repo.get_monthly_cost(now.year, now.month)

        assert cost == pytest.approx(1.00, abs=0.01)

    def test_get_by_model(self, temp_db):
        """get_by_model retourne le breakdown par modèle."""
        repo = CostTrackingRepository(temp_db)

        repo.record_usage("claude-3", 100, 50, 0.005)
        repo.record_usage("gpt-4", 200, 100, 0.015)

        breakdown = repo.get_by_model(days=30)

        assert "claude-3" in breakdown
        assert "gpt-4" in breakdown

    def test_get_trend(self, temp_db):
        """get_trend retourne la tendance."""
        repo = CostTrackingRepository(temp_db)

        repo.record_usage("claude-3", 100, 50, 0.005)

        trend = repo.get_trend(days=7)

        assert len(trend) >= 1


class TestAuditLogRepository:
    """Tests pour AuditLogRepository."""

    def test_log(self, temp_db):
        """log ajoute une entrée."""
        repo = AuditLogRepository(temp_db)

        log_id = repo.log(
            event_type="draft_created",
            success=True,
            email_id="email-123",
        )

        assert log_id > 0

    def test_log_with_details(self, temp_db):
        """log avec détails JSON."""
        repo = AuditLogRepository(temp_db)

        repo.log(
            event_type="error",
            success=False,
            error="Test error",
            details={"context": "test", "value": 123},
        )

        rows = temp_db.fetchall("SELECT * FROM audit_log")
        assert len(rows) == 1

    def test_get_recent(self, temp_db):
        """get_recent retourne les entrées récentes."""
        repo = AuditLogRepository(temp_db)

        for i in range(5):
            repo.log(event_type=f"event_{i}")

        recent = repo.get_recent(limit=3)

        assert len(recent) == 3

    def test_get_recent_filtered(self, temp_db):
        """get_recent filtre par type d'événement."""
        repo = AuditLogRepository(temp_db)

        repo.log(event_type="draft_created")
        repo.log(event_type="draft_failed")
        repo.log(event_type="draft_created")

        created = repo.get_recent(event_type="draft_created")

        assert len(created) == 2

    def test_purge_old(self, temp_db):
        """purge_old supprime les vieilles entrées."""
        repo = AuditLogRepository(temp_db)

        # Ajouter une entrée ancienne
        temp_db.execute("""
            INSERT INTO audit_log (event_type, timestamp)
            VALUES (?, ?)
        """, ("old_event", (datetime.now() - timedelta(days=100)).isoformat()))
        temp_db.commit()

        # Ajouter une entrée récente
        repo.log(event_type="new_event")

        deleted = repo.purge_old(days=90)

        assert deleted == 1
        remaining = repo.get_recent()
        assert len(remaining) == 1


class TestTaskRepository:
    """Tests pour TaskRepository."""

    def test_add_single_task(self, temp_db):
        """add ajoute une tâche et retourne son ID."""
        repo = TaskRepository(temp_db)
        task = ExtractedTask(
            title="Envoyer le rapport",
            description="Envoyer le rapport mensuel",
            priority="HIGH",
            deadline="2024-01-15",
        )

        task_id = repo.add("email-123", task)

        assert task_id > 0

    def test_add_task_without_deadline(self, temp_db):
        """add fonctionne sans deadline."""
        repo = TaskRepository(temp_db)
        task = ExtractedTask(
            title="Tâche simple",
            description="Description",
            priority="MEDIUM",
        )

        task_id = repo.add("email-456", task)

        assert task_id > 0

    def test_add_many_tasks(self, temp_db):
        """add_many ajoute plusieurs tâches."""
        repo = TaskRepository(temp_db)
        tasks = [
            ExtractedTask("Tâche 1", "Desc 1", "HIGH"),
            ExtractedTask("Tâche 2", "Desc 2", "MEDIUM"),
            ExtractedTask("Tâche 3", "Desc 3", "LOW"),
        ]

        task_ids = repo.add_many("email-789", tasks)

        assert len(task_ids) == 3
        assert all(tid > 0 for tid in task_ids)

    def test_add_many_empty_list(self, temp_db):
        """add_many avec liste vide retourne liste vide."""
        repo = TaskRepository(temp_db)

        task_ids = repo.add_many("email-empty", [])

        assert task_ids == []

    def test_get_by_email_id(self, temp_db):
        """get_by_email_id retourne les tâches d'un email."""
        repo = TaskRepository(temp_db)
        tasks = [
            ExtractedTask("Tâche A", "Desc A", "HIGH", "2024-01-20"),
            ExtractedTask("Tâche B", "Desc B", "LOW"),
        ]
        repo.add_many("email-find", tasks)

        found = repo.get_by_email_id("email-find")

        assert len(found) == 2
        assert found[0]['title'] == "Tâche A"
        assert found[0]['priority'] == "HIGH"
        assert found[0]['deadline'] == "2024-01-20"
        assert found[1]['title'] == "Tâche B"

    def test_get_by_email_id_not_found(self, temp_db):
        """get_by_email_id retourne liste vide si pas trouvé."""
        repo = TaskRepository(temp_db)

        found = repo.get_by_email_id("unknown-email")

        assert found == []

    def test_get_pending(self, temp_db):
        """get_pending retourne les tâches non complétées."""
        repo = TaskRepository(temp_db)
        repo.add("email-1", ExtractedTask("Pending 1", "Desc", "HIGH"))
        repo.add("email-2", ExtractedTask("Pending 2", "Desc", "MEDIUM"))

        pending = repo.get_pending()

        assert len(pending) == 2
        assert all(t['status'] == 'pending' for t in pending)

    def test_get_pending_with_limit(self, temp_db):
        """get_pending respecte la limite."""
        repo = TaskRepository(temp_db)
        for i in range(5):
            repo.add(f"email-{i}", ExtractedTask(f"Task {i}", "Desc", "MEDIUM"))

        pending = repo.get_pending(limit=3)

        assert len(pending) == 3

    def test_get_pending_excludes_completed(self, temp_db):
        """get_pending exclut les tâches complétées."""
        repo = TaskRepository(temp_db)
        task_id = repo.add("email-complete", ExtractedTask("Will complete", "Desc", "HIGH"))
        repo.add("email-pending", ExtractedTask("Stay pending", "Desc", "LOW"))

        repo.mark_completed(task_id)
        pending = repo.get_pending()

        assert len(pending) == 1
        assert pending[0]['title'] == "Stay pending"

    def test_mark_completed(self, temp_db):
        """mark_completed met à jour le statut."""
        repo = TaskRepository(temp_db)
        task_id = repo.add("email-mark", ExtractedTask("To complete", "Desc", "HIGH"))

        repo.mark_completed(task_id)

        tasks = repo.get_by_email_id("email-mark")
        assert tasks[0]['status'] == 'completed'
        assert tasks[0]['completed_at'] is not None

    def test_mark_completed_idempotent(self, temp_db):
        """mark_completed est idempotent."""
        repo = TaskRepository(temp_db)
        task_id = repo.add("email-idem", ExtractedTask("Idempotent", "Desc", "MEDIUM"))

        repo.mark_completed(task_id)
        repo.mark_completed(task_id)

        tasks = repo.get_by_email_id("email-idem")
        assert tasks[0]['status'] == 'completed'

    def test_table_created_in_schema(self, temp_db):
        """La table extracted_tasks est créée par le schéma."""
        tables = temp_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='extracted_tasks'"
        )

        assert len(tables) == 1
        assert tables[0]['name'] == 'extracted_tasks'

    def test_indexes_created(self, temp_db):
        """Les index sont créés sur email_id et status."""
        indexes = temp_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_extracted_tasks%'"
        )
        index_names = [idx['name'] for idx in indexes]

        assert 'idx_extracted_tasks_email_id' in index_names
        assert 'idx_extracted_tasks_status' in index_names

    def test_get_by_id_found(self, temp_db):
        """get_by_id retourne la tâche si trouvée."""
        repo = TaskRepository(temp_db)
        task = ExtractedTask("Ma tâche", "Description", "HIGH", "2024-01-15")
        task_id = repo.add("email-123", task)

        found = repo.get_by_id(task_id)

        assert found is not None
        assert found['id'] == task_id
        assert found['title'] == "Ma tâche"
        assert found['priority'] == "HIGH"

    def test_get_by_id_not_found(self, temp_db):
        """get_by_id retourne None si pas trouvé."""
        repo = TaskRepository(temp_db)

        found = repo.get_by_id(99999)

        assert found is None


class TestTaskRepositoryEdgeCases:
    """Tests edge cases pour TaskRepository."""

    def test_add_with_empty_email_id(self, temp_db):
        """add fonctionne avec un email_id vide."""
        repo = TaskRepository(temp_db)
        task = ExtractedTask("Tâche", "Description", "HIGH")

        task_id = repo.add("", task)

        assert task_id > 0
        tasks = repo.get_by_email_id("")
        assert len(tasks) == 1

    def test_add_with_none_description(self, temp_db):
        """add fonctionne avec description None."""
        repo = TaskRepository(temp_db)
        task = ExtractedTask("Tâche", None, "HIGH")

        task_id = repo.add("email-none-desc", task)

        assert task_id > 0
        tasks = repo.get_by_email_id("email-none-desc")
        assert tasks[0]['description'] is None

    def test_add_with_unicode_content(self, temp_db):
        """add gère les caractères Unicode."""
        repo = TaskRepository(temp_db)
        task = ExtractedTask(
            title="Tâche avec émojis 🎉 和中文",
            description="Description avec accents éèàù et symboles €£¥",
            priority="HIGH",
        )

        repo.add("email-unicode", task)

        tasks = repo.get_by_email_id("email-unicode")
        assert tasks[0]['title'] == "Tâche avec émojis 🎉 和中文"
        assert "€£¥" in tasks[0]['description']

    def test_add_with_very_long_content(self, temp_db):
        """add gère les contenus très longs."""
        repo = TaskRepository(temp_db)
        long_title = "T" * 1000
        long_desc = "D" * 10000
        task = ExtractedTask(long_title, long_desc, "MEDIUM")

        repo.add("email-long", task)

        tasks = repo.get_by_email_id("email-long")
        assert len(tasks[0]['title']) == 1000
        assert len(tasks[0]['description']) == 10000

    def test_add_with_special_chars_in_email_id(self, temp_db):
        """add gère les caractères spéciaux dans email_id."""
        repo = TaskRepository(temp_db)
        task = ExtractedTask("Tâche", "Desc", "LOW")
        special_email = "user+tag@example.com/<msg-123>"

        repo.add(special_email, task)

        tasks = repo.get_by_email_id(special_email)
        assert len(tasks) == 1
        assert tasks[0]['email_id'] == special_email

    def test_add_with_nonstandard_priority(self, temp_db):
        """add accepte les priorités non-standard."""
        repo = TaskRepository(temp_db)
        task = ExtractedTask("Tâche", "Desc", "CRITICAL")

        repo.add("email-priority", task)

        tasks = repo.get_by_email_id("email-priority")
        assert tasks[0]['priority'] == "CRITICAL"

    def test_mark_completed_nonexistent_task(self, temp_db):
        """mark_completed ne lève pas d'erreur pour un ID inexistant."""
        repo = TaskRepository(temp_db)

        # Ne doit pas lever d'exception
        repo.mark_completed(99999)

        # Vérifier que rien n'a été modifié
        pending = repo.get_pending()
        assert len(pending) == 0

    def test_get_pending_with_limit_zero(self, temp_db):
        """get_pending avec limit=0 retourne liste vide."""
        repo = TaskRepository(temp_db)
        repo.add("email-1", ExtractedTask("Task 1", "Desc", "HIGH"))
        repo.add("email-2", ExtractedTask("Task 2", "Desc", "MEDIUM"))

        pending = repo.get_pending(limit=0)

        assert pending == []

    def test_get_pending_returns_all_pending_tasks(self, temp_db):
        """get_pending retourne toutes les tâches pending triées par created_at DESC."""
        repo = TaskRepository(temp_db)
        repo.add("email-1", ExtractedTask("First", "Desc", "HIGH"))
        repo.add("email-2", ExtractedTask("Second", "Desc", "MEDIUM"))
        repo.add("email-3", ExtractedTask("Third", "Desc", "LOW"))

        pending = repo.get_pending()

        # Vérifier que toutes les tâches sont retournées
        assert len(pending) == 3
        titles = {t['title'] for t in pending}
        assert titles == {"First", "Second", "Third"}

    def test_get_by_email_id_preserves_insertion_order(self, temp_db):
        """get_by_email_id retourne les tâches dans l'ordre d'insertion."""
        repo = TaskRepository(temp_db)
        tasks = [
            ExtractedTask("Alpha", "Desc", "HIGH"),
            ExtractedTask("Beta", "Desc", "MEDIUM"),
            ExtractedTask("Gamma", "Desc", "LOW"),
        ]
        repo.add_many("email-order", tasks)

        found = repo.get_by_email_id("email-order")

        assert found[0]['title'] == "Alpha"
        assert found[1]['title'] == "Beta"
        assert found[2]['title'] == "Gamma"

    def test_add_with_empty_title(self, temp_db):
        """add accepte un titre vide."""
        repo = TaskRepository(temp_db)
        task = ExtractedTask("", "Description sans titre", "HIGH")

        repo.add("email-empty-title", task)

        tasks = repo.get_by_email_id("email-empty-title")
        assert tasks[0]['title'] == ""

    def test_add_with_whitespace_only_fields(self, temp_db):
        """add accepte les champs avec seulement des espaces."""
        repo = TaskRepository(temp_db)
        task = ExtractedTask("   ", "   ", "HIGH")

        repo.add("email-whitespace", task)

        tasks = repo.get_by_email_id("email-whitespace")
        assert tasks[0]['title'] == "   "
        assert tasks[0]['description'] == "   "

    def test_add_many_with_single_task(self, temp_db):
        """add_many fonctionne avec une seule tâche."""
        repo = TaskRepository(temp_db)
        tasks = [ExtractedTask("Single", "Desc", "HIGH")]

        task_ids = repo.add_many("email-single", tasks)

        assert len(task_ids) == 1
        assert task_ids[0] > 0

    def test_multiple_emails_same_task_content(self, temp_db):
        """Plusieurs emails peuvent avoir des tâches identiques."""
        repo = TaskRepository(temp_db)
        task = ExtractedTask("Identique", "Même contenu", "HIGH")

        id1 = repo.add("email-a", task)
        id2 = repo.add("email-b", task)

        assert id1 != id2
        assert len(repo.get_by_email_id("email-a")) == 1
        assert len(repo.get_by_email_id("email-b")) == 1

    def test_status_default_is_pending(self, temp_db):
        """Le status par défaut est 'pending'."""
        repo = TaskRepository(temp_db)
        repo.add("email-status", ExtractedTask("Task", "Desc", "HIGH"))

        tasks = repo.get_by_email_id("email-status")

        assert tasks[0]['status'] == 'pending'

    def test_completed_at_is_none_initially(self, temp_db):
        """completed_at est None à l'insertion."""
        repo = TaskRepository(temp_db)
        repo.add("email-completed-at", ExtractedTask("Task", "Desc", "HIGH"))

        tasks = repo.get_by_email_id("email-completed-at")

        assert tasks[0]['completed_at'] is None

    def test_deadline_formats_preserved(self, temp_db):
        """Différents formats de deadline sont préservés."""
        repo = TaskRepository(temp_db)

        # Format ISO date
        repo.add("email-iso", ExtractedTask("Task 1", "Desc", "HIGH", "2024-12-31"))
        # Format ISO datetime
        repo.add("email-datetime", ExtractedTask("Task 2", "Desc", "HIGH", "2024-12-31T23:59:59"))
        # Format texte libre
        repo.add("email-text", ExtractedTask("Task 3", "Desc", "HIGH", "fin de semaine"))

        t1 = repo.get_by_email_id("email-iso")[0]
        t2 = repo.get_by_email_id("email-datetime")[0]
        t3 = repo.get_by_email_id("email-text")[0]

        assert t1['deadline'] == "2024-12-31"
        assert t2['deadline'] == "2024-12-31T23:59:59"
        assert t3['deadline'] == "fin de semaine"


class TestInitSchemaRegression:
    """Régression boot Railway 2026-05-06.

    Voir tasks/lessons.md § "Convention projet — Ajouter une colonne à
    SCHEMA sans ALTER TABLE jumelée crashe le boot prod".

    Scénario : la migration Alembic 021_add_token_usage_log a créé
    token_usage_log avec un schéma minimal (id, account_id, agent, model,
    input_tokens, output_tokens, cost_usd, created_at). Plus tard, le
    SCHEMA legacy de database.py a déclaré la même table avec des
    colonnes supplémentaires (feature, user_id, agent_name, cache_*) plus
    deux index sur la colonne `feature`. Sur les DB prod existantes, le
    CREATE TABLE IF NOT EXISTS est devenu no-op, la colonne `feature`
    n'a jamais été ajoutée et CREATE INDEX … (feature) a halt
    executescript(SCHEMA), bloquant tous les boots Railway.
    """

    def test_boot_survives_existing_alembic_only_token_usage_log(self, tmp_path):
        """Reproduit la DB prod : token_usage_log pré-existante avec le schéma
        Alembic-021 (minimal). _init_schema doit survivre et combler les colonnes."""
        import sqlite3

        db_path = tmp_path / "prod_like.db"

        # Pré-créer la table avec exactement le schéma Alembic 021 :
        # pas de feature, pas de user_id, pas de agent_name, pas de cache_*.
        bootstrap = sqlite3.connect(str(db_path))
        bootstrap.executescript(
            """
            CREATE TABLE token_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                agent TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        bootstrap.commit()
        bootstrap.close()

        Database._initialized = False
        Database._local = threading.local()

        # Ne doit PAS lever sqlite3.OperationalError("no such column: feature").
        db = Database(db_path)

        # La table doit maintenant porter les colonnes que le SCHEMA déclare
        # ET qu'admin.py + _track_token_usage utilisent.
        cols = {
            row[1]
            for row in db.execute("PRAGMA table_info(token_usage_log)").fetchall()
        }
        assert "feature" in cols
        assert "user_id" in cols
        assert "agent_name" in cols
        assert "cache_creation_input_tokens" in cols
        assert "cache_read_input_tokens" in cols

        # L'index sur feature doit être créé (post-migration).
        idxs = {
            row[1]
            for row in db.execute(
                "SELECT * FROM sqlite_master "
                "WHERE type='index' AND tbl_name='token_usage_log'"
            ).fetchall()
        }
        assert "idx_token_usage_feature_created" in idxs
        db.close()

    def test_boot_idempotent_on_already_full_schema(self, tmp_path):
        """Boot répété sur une DB qui a déjà toutes les colonnes ne doit pas crasher
        ni perturber les colonnes existantes (try/except sur ALTER TABLE)."""
        Database._initialized = False
        Database._local = threading.local()
        db_path = tmp_path / "fresh.db"
        db1 = Database(db_path)
        db1.close()

        # Re-boot — singleton reset, même fichier.
        Database._initialized = False
        Database._local = threading.local()
        db2 = Database(db_path)
        cols = {
            row[1]
            for row in db2.execute("PRAGMA table_info(token_usage_log)").fetchall()
        }
        assert "feature" in cols
        db2.close()

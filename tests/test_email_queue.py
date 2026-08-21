# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour la queue de traitement des emails.

La queue gère les emails en attente avec:
- Priorité: les emails urgents/VIP sont traités en premier
- Concurrence: thread-safe avec workers parallèles
- Limites: max_size configurable
- Retry: emails échoués remis en queue avec backoff

Couvre:
- EmailQueueItem dataclass
- EmailQueue classe principale
- Priorité et ordering
- Thread-safety
- Retry logic avec backoff
"""

import pytest
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch
from queue import Empty

from app.interfaces.email_provider import StandardEmail


def make_test_email(
    email_id: str = "test-123",
    subject: str = "Test Subject",
    sender: str = "sender@example.com",
    priority: int = 50,
) -> StandardEmail:
    """Factory pour créer des emails de test."""
    return StandardEmail(
        id=email_id,
        subject=subject,
        sender=sender,
        sender_name="Test Sender",
        body="Test body content",
        received_at=datetime.now().isoformat(),
    )


class TestEmailQueueItem:
    """Tests pour la structure d'un item de queue."""

    def test_queue_item_creation(self):
        """Un item de queue contient un email et sa priorité."""
        from app.daemon import EmailQueueItem

        email = make_test_email()
        item = EmailQueueItem(email=email, priority=80)

        assert item.email == email
        assert item.priority == 80
        assert item.retry_count == 0
        assert item.added_at is not None

    def test_queue_item_comparison_by_priority(self):
        """Les items sont comparés par priorité (plus haut = premier)."""
        from app.daemon import EmailQueueItem

        high_priority = EmailQueueItem(email=make_test_email("high"), priority=90)
        low_priority = EmailQueueItem(email=make_test_email("low"), priority=30)

        # PriorityQueue utilise < pour l'ordre
        # Priorité haute doit venir AVANT (donc < retourne True)
        assert high_priority < low_priority

    def test_queue_item_comparison_by_timestamp_if_same_priority(self):
        """À priorité égale, le plus ancien est traité en premier (FIFO)."""
        from app.daemon import EmailQueueItem
        import time

        first = EmailQueueItem(email=make_test_email("first"), priority=50)
        time.sleep(0.01)  # Petit délai pour garantir timestamp différent
        second = EmailQueueItem(email=make_test_email("second"), priority=50)

        # Le premier ajouté doit venir avant
        assert first < second


class TestEmailQueue:
    """Tests pour la queue principale."""

    def test_queue_creation_with_defaults(self):
        """La queue est créée avec une taille max par défaut."""
        from app.daemon import EmailQueue

        queue = EmailQueue()

        assert queue.max_size == 100
        assert queue.is_empty()
        assert len(queue) == 0

    def test_queue_creation_with_custom_size(self):
        """La queue peut avoir une taille max personnalisée."""
        from app.daemon import EmailQueue

        queue = EmailQueue(max_size=50)

        assert queue.max_size == 50

    def test_enqueue_single_email(self):
        """Un email peut être ajouté à la queue."""
        from app.daemon import EmailQueue

        queue = EmailQueue()
        email = make_test_email()

        queue.enqueue(email, priority=50)

        assert not queue.is_empty()
        assert len(queue) == 1

    def test_enqueue_with_default_priority(self):
        """La priorité par défaut est 50 (normale)."""
        from app.daemon import EmailQueue

        queue = EmailQueue()
        email = make_test_email()

        queue.enqueue(email)

        item = queue.dequeue()
        assert item.priority == 50

    def test_dequeue_returns_highest_priority_first(self):
        """Le dequeue retourne l'email avec la plus haute priorité."""
        from app.daemon import EmailQueue

        queue = EmailQueue()
        queue.enqueue(make_test_email("low"), priority=30)
        queue.enqueue(make_test_email("high"), priority=90)
        queue.enqueue(make_test_email("medium"), priority=50)

        first = queue.dequeue()
        second = queue.dequeue()
        third = queue.dequeue()

        assert first.email.id == "high"
        assert second.email.id == "medium"
        assert third.email.id == "low"

    def test_dequeue_empty_queue_raises(self):
        """Dequeue sur queue vide lève Empty après timeout."""
        from app.daemon import EmailQueue

        queue = EmailQueue()

        with pytest.raises(Empty):
            queue.dequeue(timeout=0.1)

    def test_dequeue_blocking(self):
        """Dequeue peut bloquer en attendant un email."""
        from app.daemon import EmailQueue

        queue = EmailQueue()
        result = []

        def producer():
            time.sleep(0.1)
            queue.enqueue(make_test_email("delayed"), priority=50)

        def consumer():
            item = queue.dequeue(timeout=1.0)
            result.append(item.email.id)

        producer_thread = threading.Thread(target=producer)
        consumer_thread = threading.Thread(target=consumer)

        consumer_thread.start()
        producer_thread.start()

        producer_thread.join()
        consumer_thread.join()

        assert result == ["delayed"]

    def test_queue_max_size_blocks(self):
        """Une queue pleine bloque l'ajout jusqu'à libération."""
        from app.daemon import EmailQueue

        queue = EmailQueue(max_size=2)
        queue.enqueue(make_test_email("1"), priority=50)
        queue.enqueue(make_test_email("2"), priority=50)

        # Queue est pleine, le 3ème ajout doit échouer avec timeout
        with pytest.raises(Exception):  # Full exception
            queue.enqueue(make_test_email("3"), priority=50, timeout=0.1)

    def test_requeue_with_retry_increment(self):
        """Requeue incrémente le compteur de retry."""
        from app.daemon import EmailQueue

        queue = EmailQueue()
        email = make_test_email()

        queue.enqueue(email, priority=50)
        item = queue.dequeue()
        assert item.retry_count == 0

        queue.requeue(item)
        requeued = queue.dequeue()
        assert requeued.retry_count == 1

    def test_requeue_reduces_priority(self):
        """Requeue réduit la priorité pour éviter starvation."""
        from app.daemon import EmailQueue

        queue = EmailQueue()
        email = make_test_email()

        queue.enqueue(email, priority=80)
        item = queue.dequeue()
        original_priority = item.priority

        queue.requeue(item)
        requeued = queue.dequeue()

        # La priorité est réduite de 10 par retry
        assert requeued.priority == original_priority - 10

    def test_requeue_max_retries_exceeded(self):
        """Un email dépassant max_retries est rejeté."""
        from app.daemon import EmailQueue

        queue = EmailQueue(max_retries=3)
        email = make_test_email()

        queue.enqueue(email, priority=50)
        item = queue.dequeue()

        # Simuler 3 retries
        for _ in range(3):
            queue.requeue(item)
            item = queue.dequeue()

        # Le 4ème retry doit être rejeté
        result = queue.requeue(item)
        assert result is False
        assert queue.is_empty()

    def test_thread_safety_concurrent_enqueue(self):
        """La queue supporte des ajouts concurrents."""
        from app.daemon import EmailQueue

        queue = EmailQueue(max_size=1000)
        num_threads = 10
        emails_per_thread = 50

        def add_emails(thread_id: int):
            for i in range(emails_per_thread):
                email = make_test_email(f"t{thread_id}-e{i}")
                queue.enqueue(email, priority=50)

        threads = [
            threading.Thread(target=add_emails, args=(i,))
            for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(queue) == num_threads * emails_per_thread

    def test_clear_queue(self):
        """La queue peut être vidée."""
        from app.daemon import EmailQueue

        queue = EmailQueue()
        for i in range(10):
            queue.enqueue(make_test_email(f"email-{i}"), priority=50)

        queue.clear()

        assert queue.is_empty()
        assert len(queue) == 0

    def test_peek_without_removing(self):
        """Peek retourne le prochain email sans le retirer."""
        from app.daemon import EmailQueue

        queue = EmailQueue()
        queue.enqueue(make_test_email("test"), priority=50)

        peeked = queue.peek()
        assert peeked is not None
        assert peeked.email.id == "test"
        assert len(queue) == 1  # Toujours présent

    def test_get_stats(self):
        """La queue fournit des statistiques."""
        from app.daemon import EmailQueue

        queue = EmailQueue(max_size=100)
        queue.enqueue(make_test_email("1"), priority=80)
        queue.enqueue(make_test_email("2"), priority=50)
        queue.enqueue(make_test_email("3"), priority=30)

        stats = queue.get_stats()

        assert stats["size"] == 3
        assert stats["max_size"] == 100
        assert stats["utilization"] == 0.03  # 3/100


class TestEmailQueueIntegration:
    """Tests d'intégration avec le daemon."""

    def test_daemon_uses_queue_in_api_mode(self):
        """En mode API, le daemon utilise une queue."""
        from app.daemon import EmailDaemon, EmailQueue, InMemoryEventEmitter

        emitter = InMemoryEventEmitter()
        queue = EmailQueue()

        with patch("app.daemon.get_email_provider") as mock_provider, \
             patch("app.daemon.get_container") as mock_container:
            mock_provider.return_value = MagicMock()
            mock_container.return_value = MagicMock()

            daemon = EmailDaemon(
                api_mode=True,
                event_emitter=emitter,
                email_queue=queue,
            )

            assert daemon.email_queue is not None
            assert daemon.email_queue is queue

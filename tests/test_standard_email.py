# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour la dataclass StandardEmail.
"""


from app.interfaces.email_provider import StandardEmail


class TestStandardEmail:
    """Tests pour StandardEmail."""

    def test_create_minimal_email(self):
        """Test création email avec paramètres minimaux."""
        email = StandardEmail(
            id="test-123",
            sender="test@example.com"
        )

        assert email.id == "test-123"
        assert email.sender == "test@example.com"
        assert email.subject == ""
        assert email.body == ""
        assert email.is_read is False
        assert email.provider_source == "unknown"

    def test_create_full_email(self, sample_email):
        """Test création email avec tous les paramètres."""
        assert sample_email.id == "msg-123"
        assert sample_email.sender == "client@example.com"
        assert sample_email.sender_name == "Jean Client"
        assert sample_email.subject == "Question sur votre service"
        assert sample_email.is_read is False
        assert sample_email.provider_source == "test"

    def test_sender_display_with_name(self, sample_email):
        """Test sender_display retourne le nom si disponible."""
        assert sample_email.sender_display == "Jean Client"

    def test_sender_display_without_name(self):
        """Test sender_display retourne l'email si pas de nom."""
        email = StandardEmail(
            id="test",
            sender="anonymous@example.com"
        )
        assert email.sender_display == "anonymous@example.com"

    def test_preview_short_body(self):
        """Test preview avec corps court."""
        email = StandardEmail(
            id="test",
            sender="test@example.com",
            body="Court message."
        )
        assert email.preview == "Court message."

    def test_preview_long_body(self):
        """Test preview avec corps long (troncature à 100 chars)."""
        long_body = "A" * 150
        email = StandardEmail(
            id="test",
            sender="test@example.com",
            body=long_body
        )
        assert len(email.preview) == 103  # 100 + "..."
        assert email.preview.endswith("...")

    def test_preview_empty_body(self):
        """Test preview avec corps vide."""
        email = StandardEmail(
            id="test",
            sender="test@example.com",
            body=""
        )
        assert email.preview == ""

    def test_str_representation(self, sample_email):
        """Test représentation string."""
        str_repr = str(sample_email)
        assert "test" in str_repr  # provider_source
        assert "client@example.com" in str_repr
        assert "Question sur votre service" in str_repr

    def test_default_lists(self):
        """Test que les listes par défaut sont indépendantes."""
        email1 = StandardEmail(id="1", sender="a@test.com")
        email2 = StandardEmail(id="2", sender="b@test.com")

        email1.to.append("recipient@test.com")

        assert len(email1.to) == 1
        assert len(email2.to) == 0  # Liste indépendante

    def test_raw_metadata(self, sample_email):
        """Test métadonnées brutes."""
        email = StandardEmail(
            id="test",
            sender="test@example.com",
            raw_metadata={"importance": "high", "custom_field": "value"}
        )
        assert email.raw_metadata["importance"] == "high"
        assert email.raw_metadata["custom_field"] == "value"

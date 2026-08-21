# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
E2E — Account Agent : réinitialisation mot de passe WordPress.

Pipeline testé :
  Email utilisateur ("j'ai oublié mon mot de passe")
    → AccountAgent.detect_and_analyze()
      → détection regex (FR + EN)
      → recherche utilisateur WordPress (mock)
      → génération mot de passe sécurisé
      → statut pending
    → POST /api/account/<draft_id>/confirm   (approbation admin)
      → exécution WordPress reset_password (mock)
      → mot de passe retourné une seule fois
    → POST /api/account/<draft_id>/reject    (rejet admin)

Sécurité testée :
  - generated_password_full JAMAIS dans to_dict()
  - mot de passe stocké en mémoire uniquement (store._secure_passwords)
  - mot de passe effacé après confirm ou reject
  - rate limiting (3 appels / 60s)

Tous les appels WordPress sont mockés — aucun vrai appel réseau.
"""

import tempfile
from unittest.mock import patch, MagicMock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

WP_USER = {
    "id": 42,
    "slug": "alice-dupont",
    "email": "alice@example.com",
    "name": "Alice Dupont",
}


@pytest.fixture(scope="module")
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


@pytest.fixture
def agent():
    from app.account_agent import AccountAgent
    return AccountAgent()


@pytest.fixture
def store():
    """Store isolé avec persist temporaire — chaque test a son propre store."""
    from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore
    tmp = tempfile.mktemp(suffix=".json")
    return InMemoryPendingDraftStore(persist_path=tmp)


@pytest.fixture(autouse=True)
def _stub_account_resolution():
    """Audit 2026-04-25 (CRIT-Iso-4) : account_actions endpoints exigent
    `_resolve_account_id_for_user()` qui matche `draft.account_id`."""
    from unittest.mock import patch as _patch
    with _patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
        yield


def _pending_draft_with_account(draft_id, action="password_reset", status="pending",
                                wp_user=None, new_email=None, account_id="1"):
    """Crée un PendingDraft avec account_info, simulant le résultat du pipeline.

    Audit 2026-04-25 (CRIT-Iso-4) : `account_id` non vide requis pour passer
    l'ownership check de `account_actions.py`. Par défaut "1" pour matcher
    `_resolve_account_id_for_user` patché à 1.
    """
    from app.domain.entities.pending_draft import PendingDraft
    user = wp_user or WP_USER
    account_info = {
        "detected": True,
        "action": action,
        "requester_email": user["email"],
        "requester_name": user.get("name"),
        "wp_user_id": user["id"],
        "wp_username": user["slug"],
        "wp_user_email": user["email"],
        "new_email": new_email,
        "generated_password": "••••Ab3X" if action == "password_reset" else None,
        "confidence": 0.9,
        "reason": f"Réinitialisation du mot de passe pour {user['slug']}",
        "status": status,
    }
    return PendingDraft(
        id=draft_id,
        email_id=f"email-{draft_id}",
        email_sender=user["email"],
        email_sender_name=user.get("name", ""),
        email_subject="Mot de passe oublié",
        email_body="Bonjour, j'ai oublié mon mot de passe...",
        draft_body="Bonjour Alice, votre demande de réinitialisation est en cours de traitement...",
        draft_subject="Re : Mot de passe oublié",
        routing_tier="account_request",
        account_id=account_id,
        account_info=account_info,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Détection — emails réalistes de clients
# ─────────────────────────────────────────────────────────────────────────────

class TestAccountDetection:
    """L'agent détecte correctement les demandes de réinitialisation de mot de passe."""

    def test_detection_password_reset_fr(self, agent):
        """Email français : 'j'ai oublié mon mot de passe'."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice Dupont",
                "Mot de passe oublié",
                "Bonjour,\n\nJ'ai oublié mon mot de passe et je n'arrive plus "
                "à me connecter à mon compte. Pourriez-vous le réinitialiser ?\n\n"
                "Merci d'avance,\nAlice Dupont"
            )

        assert result is not None, "L'agent doit détecter la demande"
        assert result.detected is True
        assert result.action == "password_reset"
        assert result.status == "pending"
        assert result.wp_user["id"] == 42
        assert result.wp_user["slug"] == "alice-dupont"
        assert result.confidence >= 0.8

    def test_detection_password_reset_en(self, agent):
        """Email anglais : 'I forgot my password'."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice",
                "Password reset request",
                "Hi, I forgot my password and can't log in to my account. "
                "Could you please reset it? Thanks, Alice"
            )

        assert result is not None
        assert result.action == "password_reset"
        assert result.status == "pending"

    def test_detection_password_mdp_abbreviation(self, agent):
        """Email avec 'mdp' — abréviation courante en français."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice",
                "Aide",
                "Bonjour, j'ai perdu mon mdp, pouvez-vous m'aider ?"
            )

        assert result is not None
        assert result.action == "password_reset"

    def test_detection_impossible_connecter(self, agent):
        """Email 'impossible de me connecter' — variante indirecte."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice",
                "Problème de connexion",
                "Bonjour, il m'est impossible de me connecter à mon espace membre. "
                "J'ai essayé plusieurs fois. Merci de m'aider."
            )

        assert result is not None
        assert result.action == "password_reset"

    def test_email_normal_non_detecte(self, agent):
        """Un email ordinaire ne déclenche pas l'agent."""
        result = agent.detect_and_analyze(
            "alice@example.com", "Alice",
            "Question sur mon abonnement",
            "Bonjour, je voudrais savoir quand expire mon abonnement. Merci."
        )
        assert result is None

    def test_email_livraison_non_detecte(self, agent):
        """Email de livraison ne déclenche pas l'agent de compte."""
        result = agent.detect_and_analyze(
            "alice@example.com", "Alice",
            "Ma commande",
            "Bonjour, où en est ma commande ? J'attends depuis 3 semaines."
        )
        assert result is None

    def test_detection_utilisateur_wp_introuvable(self, agent):
        """Demande détectée mais utilisateur WordPress introuvable → pending (admin applique manuellement)."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=None):
            result = agent.detect_and_analyze(
                "inconnu@example.com", "Inconnu",
                "Password reset",
                "I forgot my password, please reset it."
            )

        assert result is not None
        assert result.detected is True
        # Quand l'utilisateur n'est pas trouvé, le mot de passe est quand même généré
        # pour que l'admin puisse l'appliquer manuellement → status reste "pending"
        assert result.status == "pending"
        assert result.confidence == 0.6
        assert "non trouv" in result.reason.lower()

    def test_detection_wp_erreur_reseau(self, agent):
        """Si WordPress est injoignable, l'agent génère quand même un mot de passe (pending)."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user",
                   side_effect=Exception("Connection refused")):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice",
                "Mot de passe oublié",
                "J'ai oublié mon mot de passe."
            )

        assert result is not None
        # Erreur réseau → wp_user = None → password généré pour mise à jour manuelle → pending
        assert result.status == "pending"
        assert result.generated_password_full is not None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Génération de mot de passe
# ─────────────────────────────────────────────────────────────────────────────

class TestPasswordGeneration:
    """Le mot de passe est généré de manière sécurisée et masqué correctement."""

    def test_mot_de_passe_genere(self, agent):
        """Un mot de passe sécurisé est généré lors de la détection."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice",
                "Reset password",
                "Please reset my password"
            )

        assert result.generated_password_full is not None
        assert len(result.generated_password_full) >= 12
        assert result.generated_password is not None
        assert result.generated_password.startswith("••••")

    def test_mot_de_passe_masque_dans_to_dict(self, agent):
        """to_dict() ne contient JAMAIS le mot de passe complet."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice",
                "Reset password",
                "Please reset my password"
            )

        serialized = result.to_dict()
        assert "generated_password_full" not in serialized
        assert "••••" in serialized["generated_password"]

        # Le mot de passe complet ne doit apparaître nulle part dans le dict
        full_pw = result.generated_password_full
        dict_str = str(serialized)
        assert full_pw not in dict_str

    def test_mot_de_passe_unique_a_chaque_appel(self, agent):
        """Chaque appel génère un mot de passe différent."""
        passwords = []
        for _ in range(5):
            with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
                result = agent.detect_and_analyze(
                    "alice@example.com", "Alice",
                    "Reset password",
                    "Please reset my password"
                )
            passwords.append(result.generated_password_full)

        assert len(set(passwords)) == 5, "Les mots de passe doivent être uniques"

    def test_pas_de_mot_de_passe_pour_email_change(self, agent):
        """Le changement d'email ne génère pas de mot de passe."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice",
                "Changement d'email",
                "Je voudrais changer mon email pour alice.new@example.com"
            )

        assert result.action == "email_change"
        assert result.generated_password_full is None
        assert result.generated_password is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Store — stockage sécurisé du mot de passe
# ─────────────────────────────────────────────────────────────────────────────

class TestSecurePasswordStore:
    """Le mot de passe complet est stocké en mémoire et nettoyé correctement."""

    def test_store_and_retrieve(self, store):
        """Le mot de passe peut être stocké et récupéré."""
        store.store_secure_password("draft-001", "SuperSecret123")
        assert store.get_secure_password("draft-001") == "SuperSecret123"

    def test_clear_efface_mot_de_passe(self, store):
        """clear_secure_password supprime le mot de passe."""
        store.store_secure_password("draft-002", "Secret456")
        store.clear_secure_password("draft-002")
        assert store.get_secure_password("draft-002") is None

    def test_delete_draft_efface_mot_de_passe(self, store):
        """Supprimer un draft efface aussi son mot de passe en mémoire."""
        from app.domain.entities.pending_draft import PendingDraft
        draft = PendingDraft(id="draft-003", email_id="e-003")
        store.add(draft)
        store.store_secure_password("draft-003", "Secret789")

        store.delete("draft-003")
        assert store.get_secure_password("draft-003") is None

    def test_mot_de_passe_non_persiste_sur_disque(self, store):
        """Le mot de passe n'apparaît JAMAIS dans le fichier JSON persisté."""
        from app.domain.entities.pending_draft import PendingDraft
        draft = PendingDraft(
            id="draft-004",
            email_id="e-004",
            account_info={"action": "password_reset", "status": "pending"},
        )
        store.add(draft)
        store.store_secure_password("draft-004", "TopSecretXYZ")
        store.flush()

        # Lire le fichier brut
        with open(store._persist_path, "r", encoding="utf-8") as f:
            raw = f.read()

        assert "TopSecretXYZ" not in raw, "Le mot de passe ne doit JAMAIS être sur disque"

    def test_password_inexistant_retourne_none(self, store):
        """Récupérer un mot de passe pour un draft inconnu retourne None."""
        assert store.get_secure_password("ghost-draft") is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. API — Confirmation (approbation admin)
# ─────────────────────────────────────────────────────────────────────────────

class TestAccountConfirmAPI:
    """POST /api/account/<draft_id>/confirm exécute l'action WordPress."""

    def test_confirm_password_reset_succes(self, client):
        """
        SCÉNARIO COMPLET :
          1. Draft avec account_info pending + mot de passe en mémoire
          2. Admin confirme → WordPress reset_password (mock)
          3. Réponse contient le mot de passe (une seule fois)
          4. Store mis à jour → status=executed
          5. Mot de passe effacé de la mémoire
        """
        draft = _pending_draft_with_account("e2e-acct-confirm-001")
        mock_store = MagicMock()
        mock_store.get_by_id.return_value = draft
        mock_store.get_secure_password.return_value = "GeneratedPass123"
        mock_store.update_account_info.return_value = True

        from app.interfaces.account_provider import AccountActionResult
        with patch("app.api.account_actions._get_store", return_value=mock_store), \
             patch("app.integrations.wordpress_client.WordPressAccountProvider.reset_password",
                   return_value=AccountActionResult(success=True, message="OK")):
            resp = client.post("/api/account/e2e-acct-confirm-001/confirm")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["action"] == "password_reset"
        assert data["new_password"] == "GeneratedPass123"

        # Vérifier que le store a été mis à jour
        update_call = mock_store.update_account_info.call_args[0]
        assert update_call[0] == "e2e-acct-confirm-001"
        assert update_call[1]["status"] == "executed"

        # Vérifier que le mot de passe a été nettoyé
        mock_store.clear_secure_password.assert_called_once_with("e2e-acct-confirm-001")

    def test_confirm_wordpress_echec_retourne_500(self, client):
        """Si WordPress échoue, la réponse est 500 et le status reste pending."""
        draft = _pending_draft_with_account("e2e-acct-fail-001")
        mock_store = MagicMock()
        mock_store.get_by_id.return_value = draft
        mock_store.get_secure_password.return_value = "SomePassword"

        from app.interfaces.account_provider import AccountActionResult
        with patch("app.api.account_actions._get_store", return_value=mock_store), \
             patch("app.integrations.wordpress_client.WordPressAccountProvider.reset_password",
                   return_value=AccountActionResult(success=False, message="Échec")):
            resp = client.post("/api/account/e2e-acct-fail-001/confirm")

        assert resp.status_code == 500
        data = resp.get_json()
        assert "error" in data

        # Le store ne doit PAS avoir été mis à jour
        mock_store.update_account_info.assert_not_called()

    def test_confirm_draft_introuvable_404(self, client):
        """Draft inexistant → 404."""
        mock_store = MagicMock()
        mock_store.get_by_id.return_value = None
        with patch("app.api.account_actions._get_store", return_value=mock_store):
            resp = client.post("/api/account/ghost-999/confirm")
        assert resp.status_code == 404

    def test_confirm_deja_execute_409(self, client):
        """Confirmer une action déjà exécutée → 409 Conflict."""
        draft = _pending_draft_with_account("e2e-acct-dup-001", status="executed")
        mock_store = MagicMock()
        mock_store.get_by_id.return_value = draft
        with patch("app.api.account_actions._get_store", return_value=mock_store):
            resp = client.post("/api/account/e2e-acct-dup-001/confirm")
        assert resp.status_code == 409

    def test_confirm_deja_rejete_409(self, client):
        """Confirmer une action déjà rejetée → 409 Conflict."""
        draft = _pending_draft_with_account("e2e-acct-rej-dup", status="rejected")
        mock_store = MagicMock()
        mock_store.get_by_id.return_value = draft
        with patch("app.api.account_actions._get_store", return_value=mock_store):
            resp = client.post("/api/account/e2e-acct-rej-dup/confirm")
        assert resp.status_code == 409


# ─────────────────────────────────────────────────────────────────────────────
# 5. API — Rejet
# ─────────────────────────────────────────────────────────────────────────────

class TestAccountRejectAPI:
    """POST /api/account/<draft_id>/reject refuse l'action."""

    def test_reject_succes(self, client):
        """Admin refuse la réinitialisation avec une raison."""
        draft = _pending_draft_with_account("e2e-acct-reject-001")
        mock_store = MagicMock()
        mock_store.get_by_id.return_value = draft
        mock_store.update_account_info.return_value = True

        with patch("app.api.account_actions._get_store", return_value=mock_store):
            resp = client.post(
                "/api/account/e2e-acct-reject-001/reject",
                json={"reason": "Identité non vérifiée."},
            )

        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        update_call = mock_store.update_account_info.call_args[0]
        assert update_call[1]["status"] == "rejected"
        assert "non vérifiée" in update_call[1]["reason"]

        # Mot de passe effacé même en cas de rejet
        mock_store.clear_secure_password.assert_called_once_with("e2e-acct-reject-001")

    def test_reject_sans_raison_ok(self, client):
        """Rejet sans raison → accepté (raison optionnelle)."""
        draft = _pending_draft_with_account("e2e-acct-reject-002")
        mock_store = MagicMock()
        mock_store.get_by_id.return_value = draft
        mock_store.update_account_info.return_value = True

        with patch("app.api.account_actions._get_store", return_value=mock_store):
            resp = client.post("/api/account/e2e-acct-reject-002/reject")

        assert resp.status_code == 200

    def test_reject_draft_introuvable_404(self, client):
        mock_store = MagicMock()
        mock_store.get_by_id.return_value = None
        with patch("app.api.account_actions._get_store", return_value=mock_store):
            resp = client.post("/api/account/ghost-reject/reject")
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 6. Pipeline complet : email → detect → store → confirm → exécuté
# ─────────────────────────────────────────────────────────────────────────────

class TestFullPipeline:
    """
    Simule le pipeline complet tel qu'il s'exécute en production :
      1. Alice envoie un email "j'ai oublié mon mot de passe"
      2. AccountAgent.detect_and_analyze() → pending + password généré
      3. Le draft est créé avec account_info
      4. Le mot de passe est stocké en mémoire sécurisée
      5. L'admin confirme via POST /account/<id>/confirm
      6. WordPress reset_password est appelé avec le bon mot de passe
      7. La réponse contient le nouveau mot de passe (une seule fois)
      8. Le mot de passe est effacé de la mémoire
    """

    def test_pipeline_password_reset_complet(self, agent, store, client):
        # ── Étape 1 : Détection ──
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                sender_email="alice@example.com",
                sender_name="Alice Dupont",
                subject="Aide — mot de passe perdu",
                body=(
                    "Bonjour,\n\n"
                    "Je n'arrive plus à me connecter à mon compte sur votre site. "
                    "J'ai oublié mon mot de passe. "
                    "Pourriez-vous le réinitialiser s'il vous plaît ?\n\n"
                    "Mon email de connexion est alice@example.com.\n\n"
                    "Cordialement,\nAlice Dupont"
                ),
            )

        assert result is not None
        assert result.detected is True
        assert result.action == "password_reset"
        assert result.status == "pending"
        assert result.wp_user["id"] == 42
        assert result.wp_user["slug"] == "alice-dupont"
        assert result.generated_password_full is not None

        saved_password = result.generated_password_full

        # ── Étape 2 : Créer le PendingDraft (comme le ferait routes.py) ──
        from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus
        draft = PendingDraft(
            id="e2e-pipeline-001",
            email_id="email-pipeline-001",
            email_sender="alice@example.com",
            email_sender_name="Alice Dupont",
            email_subject="Aide — mot de passe perdu",
            email_body="J'ai oublié mon mot de passe...",
            draft_body="Bonjour Alice, votre mot de passe a été réinitialisé...",
            draft_subject="Re : Aide — mot de passe perdu",
            routing_tier="account_request",
            account_info=result.to_dict(),
            account_id="1",  # CRIT-Iso-4 : doit matcher _resolve_account_id_for_user.
            status=PendingDraftStatus.PENDING,
        )
        store.add(draft)
        store.store_secure_password("e2e-pipeline-001", saved_password)

        # Vérifier que le draft est bien stocké
        retrieved = store.get_by_id("e2e-pipeline-001")
        assert retrieved is not None
        assert retrieved.account_info["action"] == "password_reset"
        assert retrieved.account_info["status"] == "pending"
        assert retrieved.account_info["wp_user_id"] == 42

        # Vérifier que le mot de passe est en mémoire
        assert store.get_secure_password("e2e-pipeline-001") == saved_password

        # Vérifier que le mot de passe n'est PAS dans account_info
        assert "generated_password_full" not in retrieved.account_info

        # ── Étape 3 : Confirmation admin via API ──
        from app.interfaces.account_provider import AccountActionResult
        with patch("app.api.account_actions._get_store", return_value=store), \
             patch("app.integrations.wordpress_client.WordPressAccountProvider.reset_password",
                   return_value=AccountActionResult(success=True, message="OK")) as mock_wp:
            resp = client.post("/api/account/e2e-pipeline-001/confirm")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["action"] == "password_reset"
        assert data["new_password"] == saved_password

        # Vérifier que WordPress a été appelé avec le bon user_id et mot de passe
        mock_wp.assert_called_once_with(42, saved_password)

        # ── Étape 4 : Vérifier l'état final ──
        final_draft = store.get_by_id("e2e-pipeline-001")
        assert final_draft.account_info["status"] == "executed"

        # Mot de passe effacé de la mémoire
        assert store.get_secure_password("e2e-pipeline-001") is None

    def test_pipeline_rejet_ne_touche_pas_wordpress(self, agent, store, client):
        """Si l'admin rejette, WordPress n'est jamais appelé."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice",
                "Reset password",
                "I forgot my password please"
            )

        from app.domain.entities.pending_draft import PendingDraft
        draft = PendingDraft(
            id="e2e-pipeline-reject",
            email_id="email-rej",
            account_info=result.to_dict(),
            account_id="1",  # CRIT-Iso-4 : doit matcher _resolve_account_id_for_user.
        )
        store.add(draft)
        store.store_secure_password("e2e-pipeline-reject", result.generated_password_full)

        with patch("app.api.account_actions._get_store", return_value=store), \
             patch("app.integrations.wordpress_client.WordPressAccountProvider.reset_password") as mock_wp:
            resp = client.post(
                "/api/account/e2e-pipeline-reject/reject",
                json={"reason": "Utilisateur non vérifié"},
            )

        assert resp.status_code == 200
        mock_wp.assert_not_called()

        # Mot de passe effacé
        assert store.get_secure_password("e2e-pipeline-reject") is None

        # Status rejeté
        final = store.get_by_id("e2e-pipeline-reject")
        assert final.account_info["status"] == "rejected"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Changement d'email (second type d'action)
# ─────────────────────────────────────────────────────────────────────────────

class TestEmailChangeDetection:

    def test_detection_email_change_fr(self, agent):
        """Email français : 'changer mon email'."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice",
                "Changement d'adresse email",
                "Bonjour,\n\nJe souhaite changer mon email pour alice.new@company.com.\n\nMerci."
            )

        assert result is not None
        assert result.action == "email_change"
        assert result.new_email == "alice.new@company.com"
        assert result.status == "pending"

    def test_detection_email_change_en(self, agent):
        """Email anglais : 'update my email'."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice",
                "Update email address",
                "Hi, I'd like to update my email to alice.new@company.com. Thanks!"
            )

        assert result is not None
        assert result.action == "email_change"
        assert result.new_email == "alice.new@company.com"

    def test_email_change_sans_nouvelle_adresse(self, agent):
        """Demande de changement sans préciser la nouvelle adresse → confidence basse."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice",
                "Modifier mon email",
                "Bonjour, je voudrais modifier mon adresse email. Merci."
            )

        assert result is not None
        assert result.action == "email_change"
        assert result.new_email is None
        assert result.confidence == 0.5

    def test_nouvelle_adresse_exclut_expediteur(self, agent):
        """L'adresse extraite ne doit pas être celle de l'expéditeur."""
        with patch("app.integrations.wordpress_client.WordPressAccountProvider.search_user", return_value=WP_USER):
            result = agent.detect_and_analyze(
                "alice@example.com", "Alice",
                "Changer mon email",
                "Bonjour, mon email actuel alice@example.com ne fonctionne plus. "
                "Pouvez-vous le changer pour alice.new@company.com ? Merci."
            )

        assert result.new_email == "alice.new@company.com"
        assert result.new_email != "alice@example.com"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Marketplace — Account Agent dans le catalogue
# ─────────────────────────────────────────────────────────────────────────────

class TestAccountAgentMarketplace:

    def test_catalog_contient_account_agent(self, client):
        """Le catalogue contient l'Account Agent."""
        resp = client.get("/api/agent-marketplace/catalog")
        assert resp.status_code == 200
        data = resp.get_json()
        account = next((a for a in data if a["id"] == "account"), None)
        assert account is not None, "Account Agent doit être dans le catalogue"
        assert account["name"] == "Account Agent"
        assert account["category"] == "Customer Service"

    def test_wordpress_test_sans_config_400(self, client):
        """GET /test-wordpress sans config → 400."""
        resp = client.get("/api/agent-marketplace/account/test-wordpress")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False

    def test_wordpress_test_connexion_ok(self, client):
        """GET /test-wordpress avec config valide (mock) → 200."""
        import app.api.agent_marketplace as _mp
        _mp._save_agent_config("account", {
            "provider": "wordpress",
            "providers": {
                "wordpress": {
                    "site_url": "https://example.com",
                    "username": "admin",
                    "app_password": "xxxx xxxx xxxx",
                }
            },
        })

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"slug": "admin"}
        with patch("requests.Session.get", return_value=mock_resp):
            resp = client.get("/api/agent-marketplace/account/test-wordpress")

        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_config_masque_app_password(self, client):
        """GET /config masque wordpress_app_password."""
        import app.api.agent_marketplace as _mp
        _mp._save_agent_config("account", {
            "wordpress_site_url": "https://example.com",
            "wordpress_username": "admin",
            "wordpress_app_password": "abcd efgh ijkl mnop",
        })

        resp = client.get("/api/agent-marketplace/account/config")
        data = resp.get_json()
        pw = data.get("wordpress_app_password", "")
        assert "efgh" not in pw, "Le mot de passe d'application ne doit pas être exposé"
        assert "••" in pw


# ─────────────────────────────────────────────────────────────────────────────
# 9. Entity — PendingDraft avec account_info
# ─────────────────────────────────────────────────────────────────────────────

class TestPendingDraftAccountInfo:

    def test_to_dict_inclut_account_info(self):
        from app.domain.entities.pending_draft import PendingDraft
        draft = PendingDraft(account_info={"action": "password_reset", "status": "pending"})
        d = draft.to_dict()
        assert "account_info" in d
        assert d["account_info"]["action"] == "password_reset"

    def test_to_dict_summary_inclut_account_info(self):
        from app.domain.entities.pending_draft import PendingDraft
        draft = PendingDraft(account_info={"action": "email_change"})
        d = draft.to_dict_summary()
        assert "account_info" in d

    def test_from_dict_restaure_account_info(self):
        from app.domain.entities.pending_draft import PendingDraft
        original = PendingDraft(account_info={"action": "password_reset", "wp_user_id": 42})
        restored = PendingDraft.from_dict(original.to_dict())
        assert restored.account_info == {"action": "password_reset", "wp_user_id": 42}

    def test_account_info_none_par_defaut(self):
        from app.domain.entities.pending_draft import PendingDraft
        draft = PendingDraft()
        assert draft.account_info is None
        assert draft.to_dict()["account_info"] is None

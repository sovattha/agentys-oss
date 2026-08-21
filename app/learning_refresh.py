# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Coordinateur de rafraîchissement automatique de l'apprentissage.

Deux mécanismes complémentaires :
- Event-driven (post-send) : capture les corrections immédiates
- Périodique (scheduler) : détecte les patterns émergents sur le long terme
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================================
# Configuration — seuils par défaut
# ============================================================================

KB_REFRESH_INTERVAL = int(os.getenv("LEARNING_KB_REFRESH_INTERVAL", 10))
KB_REFRESH_COOLDOWN_HOURS = float(os.getenv("LEARNING_KB_COOLDOWN_HOURS", 2))
DEEP_REFRESH_INTERVAL_DAYS = int(os.getenv("LEARNING_DEEP_REFRESH_DAYS", 30))


def _state_path() -> Path:
    """Chemin du fichier d'état persisté."""
    state_dir = Path.home() / ".agentys"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "learning_refresh_state.json"


class LearningRefreshCoordinator:
    """Coordonne le rafraîchissement automatique de l'apprentissage.

    État persisté dans ~/.agentys/learning_refresh_state.json pour
    survivre aux redémarrages de l'API.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._refresh_guard = threading.Lock()  # prevents concurrent refresh threads
        self._state = self._load_state()

    # ── Persistence ──────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        path = _state_path()
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("État learning_refresh corrompu, réinitialisation")
        return {
            "event_counter": 0,
            "last_kb_refresh_at": None,
            "last_deep_refresh_at": None,
        }

    def _save_state(self) -> None:
        try:
            _state_path().write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Impossible de sauvegarder l'état learning_refresh: %s", e)

    # ── Event-driven : appelé après chaque envoi ─────────────────────────

    def _increment_and_check(
        self, account_id: Optional[int], user_email: Optional[str]
    ) -> int:
        """Incrémente le compteur unifié et déclenche un refresh si seuil atteint.

        Returns:
            La nouvelle valeur du compteur.
        """
        with self._lock:
            self._state["event_counter"] = self._state.get("event_counter", 0) + 1
            # Migrate legacy key if present
            self._state.pop("send_counter", None)
            counter = self._state["event_counter"]
            self._save_state()

        if counter % KB_REFRESH_INTERVAL == 0 and self._cooldown_ok():
            self._trigger_incremental_refresh(account_id, user_email, days=7)

        return counter

    def on_email_sent(
        self,
        email_id: str,
        contact: str,
        had_correction: bool,
        edit_ratio: float,
        account_id: Optional[int],
        user_email: Optional[str],
    ) -> None:
        """Appelé depuis _post_send_all_bg après le recording.

        Args:
            email_id: ID de l'email envoyé.
            contact: Adresse du destinataire.
            had_correction: True si l'utilisateur a modifié le brouillon.
            edit_ratio: Ratio d'édition (0.0 = inchangé, 1.0 = réécrit).
            account_id: ID du compte actif.
            user_email: Email de l'utilisateur.
        """
        self._increment_and_check(account_id, user_email)

        # Émettre event WS léger
        try:
            from app.api.websocket import emit_learning_correction_recorded
            emit_learning_correction_recorded(
                email_id,
                had_correction,
                edit_ratio,
                account_id=account_id,
            )
        except Exception as e:
            logger.debug("Échec emit correction_recorded: %s", e)

    def on_label_corrected(
        self,
        email_id: str,
        old_label: str,
        new_label: str,
        account_id: Optional[int],
        user_email: Optional[str],
    ) -> None:
        """Appelé après une correction de label par l'utilisateur.

        Args:
            email_id: ID de l'email corrigé.
            old_label: Label assigné par l'IA.
            new_label: Label choisi par l'utilisateur.
            account_id: ID du compte actif.
            user_email: Email de l'utilisateur.
        """
        self._increment_and_check(account_id, user_email)

        try:
            from app.api.websocket import emit_learning_label_corrected
            emit_learning_label_corrected(
                email_id,
                old_label,
                new_label,
                account_id=account_id,
            )
        except Exception as e:
            logger.debug("Échec emit label_corrected: %s", e)

    def _cooldown_ok(self) -> bool:
        """Vérifie que le cooldown entre deux refreshs KB est respecté."""
        last = self._state.get("last_kb_refresh_at")
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
            elapsed_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            return elapsed_hours >= KB_REFRESH_COOLDOWN_HOURS
        except Exception:
            return True

    def get_status(self) -> dict:
        """Retourne l'état courant du compteur pour l'API et l'UI.

        Returns:
            Dict avec event_counter, threshold, next_refresh_in, etc.
        """
        counter = self._state.get("event_counter", 0)
        next_in = KB_REFRESH_INTERVAL - (counter % KB_REFRESH_INTERVAL)
        return {
            "event_counter": counter,
            "threshold": KB_REFRESH_INTERVAL,
            "next_refresh_in": next_in,
            "last_refresh_at": self._state.get("last_kb_refresh_at"),
            "cooldown_active": not self._cooldown_ok(),
        }

    def _trigger_incremental_refresh(
        self, account_id: Optional[int], user_email: Optional[str], days: int = 7
    ) -> None:
        """Refresh KB incrémental via OnboardingManager.refresh()."""
        if not account_id or not user_email:
            logger.debug("Refresh KB ignoré: account_id ou user_email manquant")
            return

        if not self._refresh_guard.acquire(blocking=False):
            logger.debug("Refresh KB ignoré: un refresh est déjà en cours")
            return

        logger.info(
            "Learning refresh: refresh KB incrémental déclenché (envoi #%d, %d jours)",
            self._state["event_counter"],
            days,
        )

        def _bg_refresh():
            try:
                from app.api.onboarding import _get_manager
                # Audit (mother-of-all 2026-04-25) : passer account_id pour
                # router les WS events vers la bonne room. Sans ça, l'emit_fn
                # est None côté manager → progress silencieusement perdu côté
                # frontend (le user voit un spinner qui ne bouge plus).
                manager = _get_manager(account_id=account_id)
                manager.refresh(account_id, user_email, days=days)

                from app.api.websocket import emit_learning_refresh_completed
                emit_learning_refresh_completed(
                    account_id=account_id,
                    refresh_type="incremental",
                    summary=f"Refresh incrémental ({days}j)",
                )
            except Exception as e:
                logger.warning("Échec refresh KB incrémental: %s", e)
            finally:
                self._refresh_guard.release()

        threading.Thread(target=_bg_refresh, daemon=True, name="LearningKBRefresh").start()

    # ── Deep refresh check (appelé par le scheduler) ─────────────────────

    def check_deep_refresh_due(self) -> bool:
        """Vérifie si le refresh profond mensuel est dû."""
        last = self._state.get("last_deep_refresh_at")
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
            elapsed_days = (datetime.now(timezone.utc) - last_dt).total_seconds() / 86400
            return elapsed_days >= DEEP_REFRESH_INTERVAL_DAYS
        except Exception:
            return True

    def mark_deep_refresh_done(self) -> None:
        """Marque le deep refresh comme effectué."""
        with self._lock:
            self._state["last_deep_refresh_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state()

    def mark_refresh_done(self) -> None:
        """Marque qu'un refresh KB (manuel ou automatique) vient de se terminer.

        Remet le compteur à 0 et met à jour last_kb_refresh_at.
        Appelé depuis OnboardingManager après un refresh réussi.
        """
        with self._lock:
            self._state["last_kb_refresh_at"] = datetime.now(timezone.utc).isoformat()
            self._state["event_counter"] = 0
            self._save_state()

    def get_state(self) -> dict:
        """Retourne l'état courant (pour debug/API)."""
        return dict(self._state)


# ============================================================================
# Scheduler périodique (deep refresh)
# ============================================================================

CHECK_INTERVAL_HOURS = float(os.getenv("LEARNING_CHECK_INTERVAL_HOURS", 6))


class LearningRefreshScheduler:
    """Vérifie périodiquement si un deep refresh est nécessaire.

    Utilise un Timer-based pattern (comme RecapScheduler), pas APScheduler.
    """

    def __init__(self, coordinator: LearningRefreshCoordinator):
        self._coordinator = coordinator
        self._timer: Optional[threading.Timer] = None
        self._running = False

    def start(self) -> None:
        """Démarre la boucle de vérification."""
        self._running = True
        self._schedule_next_check()
        logger.info(
            "LearningRefreshScheduler démarré (vérification toutes les %.1fh)",
            CHECK_INTERVAL_HOURS,
        )

    def stop(self) -> None:
        """Arrête le scheduler."""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        logger.info("LearningRefreshScheduler arrêté")

    def _schedule_next_check(self) -> None:
        if not self._running:
            return
        interval_seconds = CHECK_INTERVAL_HOURS * 3600
        self._timer = threading.Timer(interval_seconds, self._check_and_refresh)
        self._timer.daemon = True
        self._timer.start()

    def _check_and_refresh(self) -> None:
        """Si > 30j depuis le dernier deep refresh → lancer pour chaque compte actif."""
        # Issue #577 item 4 Phase B — Timer-based (no while loop), so the
        # heartbeat lives in the per-fire callback. Tolerance 2× the
        # interval so a single skipped fire (very-long deep refresh, host
        # clock skew) does not trip the sentinel.
        from app.services.scheduler_heartbeat import record_heartbeat

        _interval = int(CHECK_INTERVAL_HOURS * 3600 * 2)
        record_heartbeat(
            "learning_refresh_scheduler",
            status="ok",
            expected_interval_seconds=_interval,
        )
        try:
            if self._coordinator.check_deep_refresh_due():
                logger.info("Deep refresh mensuel déclenché")
                self._run_deep_refresh()
        except Exception as e:
            logger.warning("Erreur lors du check deep refresh: %s", e)
            record_heartbeat(
                "learning_refresh_scheduler",
                status="error",
                expected_interval_seconds=_interval,
            )
        finally:
            self._schedule_next_check()

    def _run_deep_refresh(self) -> None:
        """Lance le deep refresh pour chaque compte actif."""
        try:
            from app.db.database import get_db_session_with_retry
            from app.db.repositories.account_repository import AccountRepository

            with get_db_session_with_retry() as session:
                accounts = AccountRepository(session).get_active_accounts()
                if not accounts:
                    logger.debug("Deep refresh: aucun compte actif")
                    return

            for account in accounts:
                try:
                    from app.api.onboarding import _get_manager
                    # Audit : router les WS events vers la room de ce compte.
                    manager = _get_manager(account_id=account.id)
                    manager.refresh(account.id, account.email or "", days=None)

                    from app.api.websocket import emit_learning_refresh_completed
                    emit_learning_refresh_completed(
                        account_id=account.id,
                        refresh_type="deep",
                        summary="Refresh profond mensuel (corpus complet)",
                    )
                except Exception as e:
                    logger.warning(
                        "Deep refresh échoué pour compte %s: %s", account.id, e
                    )

            self._coordinator.mark_deep_refresh_done()
        except Exception as e:
            logger.warning("Erreur deep refresh global: %s", e)


# ============================================================================
# Singleton
# ============================================================================

_coordinator: Optional[LearningRefreshCoordinator] = None
_coordinator_lock = threading.Lock()


def get_refresh_coordinator() -> LearningRefreshCoordinator:
    """Retourne le singleton du coordinateur de refresh."""
    global _coordinator
    if _coordinator is None:
        with _coordinator_lock:
            if _coordinator is None:
                _coordinator = LearningRefreshCoordinator()
    return _coordinator

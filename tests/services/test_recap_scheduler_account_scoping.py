# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Recap mensuel : flags lus/écrits PAR COMPTE (audit scalabilité 2026-05-29).

L'ancien scheduler lisait les settings GLOBAUX :
- ``monthly_recap_email_sent_month`` devenait un verrou partagé — le premier
  envoi réussi marquait le mois « fait » pour TOUS les autres tenants (récap
  silencieusement perdu pour les comptes 2..N) ;
- l'opt-out ``monthly_recap_email_enabled`` écrit par le PATCH /api/settings
  (scopé compte) était ignoré ;
- la bannière posée en global restait masquée à vie par un
  ``monthly_recap_banner_dismissed`` per-compte d'un mois précédent.

Ces tests sont discriminants : ils échouent sur l'ancien code global.
"""

from contextlib import ExitStack
from datetime import date, datetime
from unittest.mock import Mock, patch

from app.services.recap_scheduler import RecapScheduler


def _account(account_id: int) -> Mock:
    acc = Mock()
    acc.id = account_id
    acc.email = f"user{account_id}@example.com"
    return acc


def _run_scheduler(*, accounts, settings_by_account, send_success=True):
    """Exécute _check_and_trigger avec le stack de mocks standard.

    Returns (provider, save_calls) où save_calls = [(settings_dict_copy,
    account_id), ...] capturés à CHAQUE save_settings.
    """
    save_calls = []

    def _fake_load(account_id=None):
        # Copie fraîche par appel — le scheduler mute le dict retourné.
        return dict(settings_by_account.get(account_id, {}))

    def _fake_save(settings, account_id=None):
        save_calls.append((dict(settings), account_id))
        return True

    provider = Mock()
    provider.send_email.return_value = send_success

    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.services.recap_scheduler._should_trigger", return_value=True))
        mock_date = stack.enter_context(patch("app.services.recap_scheduler.date"))
        mock_date.today.return_value = date(2026, 6, 1)
        mock_dt = stack.enter_context(patch("app.services.recap_scheduler.datetime"))
        mock_dt.now.return_value = datetime(2026, 6, 1, 14, 0, 0)

        mock_sess = stack.enter_context(patch("app.db.database.get_db_session"))
        mock_sess.return_value.__enter__ = Mock(return_value=Mock())
        mock_sess.return_value.__exit__ = Mock(return_value=False)
        repo = stack.enter_context(patch(
            "app.db.repositories.account_repository.AccountRepository"))
        repo.return_value.get_active_accounts.return_value = accounts

        get_recap = stack.enter_context(patch(
            "app.services.recap_service.get_recap",
            return_value={"month_label": "MAY 2026", "emails_processed": 10, "best": {},
                          "comparison": {"message": ""}}))
        stack.enter_context(patch(
            "app.services.recap_scheduler._render_email", return_value="<html>r</html>"))
        stack.enter_context(patch(
            "app.providers.factory.get_email_provider", return_value=provider))
        stack.enter_context(patch("app.api.settings.load_settings", side_effect=_fake_load))
        stack.enter_context(patch("app.api.settings.save_settings", side_effect=_fake_save))

        RecapScheduler()._check_and_trigger()

    return provider, save_calls, get_recap


class TestPerAccountEmailSend:
    def test_second_account_still_gets_its_email(self):
        """Le bug d'origine : l'envoi du compte 1 verrouillait le mois pour
        tous les autres (flag global). Chaque compte doit recevoir SON email."""
        provider, _saves, _ = _run_scheduler(
            accounts=[_account(1), _account(2)],
            settings_by_account={1: {}, 2: {}},
        )
        sent_to = [c.kwargs["to"] for c in provider.send_email.call_args_list]
        assert sent_to == [["user1@example.com"], ["user2@example.com"]]

    def test_per_account_opt_out_is_respected(self):
        """L'opt-out écrit par PATCH /api/settings (scopé compte) doit être lu
        par le scheduler — l'ancien code lisait le flag global et envoyait."""
        provider, _saves, _ = _run_scheduler(
            accounts=[_account(1), _account(2)],
            settings_by_account={
                1: {"monthly_recap_email_enabled": False},
                2: {},
            },
        )
        sent_to = [c.kwargs["to"] for c in provider.send_email.call_args_list]
        assert sent_to == [["user2@example.com"]]

    def test_already_sent_account_is_not_resent(self):
        provider, _saves, _ = _run_scheduler(
            accounts=[_account(1), _account(2)],
            settings_by_account={
                1: {"monthly_recap_email_sent_month": "2026-05"},
                2: {},
            },
        )
        sent_to = [c.kwargs["to"] for c in provider.send_email.call_args_list]
        assert sent_to == [["user2@example.com"]]


class TestPerAccountPersistence:
    def test_every_save_is_account_scoped(self):
        """Aucune écriture GLOBALE : chaque save_settings porte un account_id."""
        _provider, saves, _ = _run_scheduler(
            accounts=[_account(1), _account(2)],
            settings_by_account={1: {}, 2: {}},
        )
        assert saves, "le scheduler doit persister les flags"
        assert all(aid in (1, 2) for _s, aid in saves)

    def test_sent_month_and_banner_saved_per_account(self):
        _provider, saves, _ = _run_scheduler(
            accounts=[_account(1)],
            settings_by_account={1: {}},
        )
        final = [s for s, aid in saves if aid == 1][-1]
        assert final["monthly_recap_banner_month"] == "2026-05"
        assert final["monthly_recap_banner_dismissed"] is False
        sent_saves = [s for s, _aid in saves if s.get("monthly_recap_email_sent_month") == "2026-05"]
        assert sent_saves, "l'envoi doit être marqué fait pour CE compte"

    def test_banner_set_even_when_email_disabled(self):
        """Opt-out email ≠ pas de bannière : la bannière in-app reste posée."""
        provider, saves, _ = _run_scheduler(
            accounts=[_account(1)],
            settings_by_account={1: {"monthly_recap_email_enabled": False}},
        )
        assert not provider.send_email.called
        assert any(
            s.get("monthly_recap_banner_month") == "2026-05" and aid == 1
            for s, aid in saves
        )


class TestPerAccountSkip:
    def test_fully_done_account_is_skipped_others_processed(self):
        """Un compte entièrement servi (bannière + email du mois) est sauté
        sans recalcul ; les autres comptes sont traités normalement."""
        _provider, _saves, get_recap = _run_scheduler(
            accounts=[_account(1), _account(2)],
            settings_by_account={
                1: {
                    "monthly_recap_banner_month": "2026-05",
                    "monthly_recap_email_sent_month": "2026-05",
                },
                2: {},
            },
        )
        recap_accounts = [c.kwargs.get("account_id") for c in get_recap.call_args_list]
        assert recap_accounts == [2]

    def test_one_account_failure_does_not_block_others(self):
        """Une exception sur le compte 1 (ex: recap service) n'empêche pas le
        compte 2 d'être servi — la boucle isole les échecs par compte."""
        accounts = [_account(1), _account(2)]
        with ExitStack() as stack:
            stack.enter_context(patch(
                "app.services.recap_scheduler._should_trigger", return_value=True))
            mock_date = stack.enter_context(patch("app.services.recap_scheduler.date"))
            mock_date.today.return_value = date(2026, 6, 1)
            mock_dt = stack.enter_context(patch("app.services.recap_scheduler.datetime"))
            mock_dt.now.return_value = datetime(2026, 6, 1, 14, 0, 0)
            mock_sess = stack.enter_context(patch("app.db.database.get_db_session"))
            mock_sess.return_value.__enter__ = Mock(return_value=Mock())
            mock_sess.return_value.__exit__ = Mock(return_value=False)
            repo = stack.enter_context(patch(
                "app.db.repositories.account_repository.AccountRepository"))
            repo.return_value.get_active_accounts.return_value = accounts

            def _recap(month, account_id=None):
                if account_id == 1:
                    raise RuntimeError("boom")
                return {"month_label": "MAY 2026", "emails_processed": 1, "best": {},
                        "comparison": {"message": ""}}

            stack.enter_context(patch(
                "app.services.recap_service.get_recap", side_effect=_recap))
            stack.enter_context(patch(
                "app.services.recap_scheduler._render_email", return_value="<html>r</html>"))
            provider = Mock()
            provider.send_email.return_value = True
            stack.enter_context(patch(
                "app.providers.factory.get_email_provider", return_value=provider))
            stack.enter_context(patch(
                "app.api.settings.load_settings", side_effect=lambda account_id=None: {}))
            stack.enter_context(patch(
                "app.api.settings.save_settings", return_value=True))

            RecapScheduler()._check_and_trigger()

        sent_to = [c.kwargs["to"] for c in provider.send_email.call_args_list]
        assert sent_to == [["user2@example.com"]]

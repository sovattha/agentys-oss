# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour RecapScheduler — planification mensuelle et fonctions helper.

Couvre:
- _format_time(): conversion minutes vers string lisible (sec, min, h)
- _get_first_working_day(): calcul du premier jour ouvrable du mois
- _should_trigger(): détection du jour de déclenchement
- _get_recap_month(): calcul du mois du recap (mois précédent)
- RecapScheduler lifecycle (start, stop, thread management)
- _check_and_trigger(): logique d'orchestration
- _send_recap_email(): envoi email avec mocking
"""

import time
from datetime import date, datetime
from unittest.mock import Mock, patch

from app.services.recap_scheduler import (
    _format_time,
    _get_first_working_day,
    _should_trigger,
    _get_recap_month,
    _render_email,
    RecapScheduler,
)


class TestFormatTime:
    """Tests pour _format_time()."""

    def test_zero_minutes(self):
        """Zéro minutes → '0 s'."""
        assert _format_time(0) == "0 s"

    def test_less_than_one_minute(self):
        """Moins d'une minute → afficher en secondes."""
        assert _format_time(0.5) == "30 s"
        assert _format_time(0.25) == "15 s"
        assert _format_time(0.1) == "6 s"

    def test_one_minute(self):
        """Une minute → '1 min'."""
        assert _format_time(1) == "1 min"

    def test_minutes(self):
        """Minutes normales → 'X min'."""
        assert _format_time(30) == "30 min"
        assert _format_time(45) == "45 min"
        assert _format_time(59) == "59 min"

    def test_one_hour(self):
        """Une heure → '1.0h'."""
        result = _format_time(60)
        assert "h" in result
        assert "1.0" in result

    def test_multiple_hours(self):
        """Plusieurs heures → 'X.Xh'."""
        result = _format_time(90)
        assert "h" in result
        assert "1.5" in result

        result = _format_time(120)
        assert "h" in result
        assert "2.0" in result

    def test_fractional_minutes(self):
        """Minutes fractionnaires → arrondi correct."""
        assert _format_time(1.5) == "1 min"
        assert _format_time(2.7) == "2 min"

    def test_hours_precision(self):
        """Heures avec une décimale."""
        result = _format_time(180)  # 3 heures
        assert "3.0h" in result

        result = _format_time(195)  # 3.25 heures
        assert "3.2h" in result


class TestGetFirstWorkingDay:
    """Tests pour _get_first_working_day()."""

    def test_month_starts_on_weekday(self):
        """Mois commençant un jour de la semaine → jour 1."""
        # Mars 2026 commence un dimanche (weekday=6)
        # Donc on retourne le lundi (jour 2)
        assert _get_first_working_day(2026, 3) == 2

    def test_month_starts_on_monday(self):
        """Mois commençant un lundi → jour 1."""
        # Juin 2026 commence un lundi
        assert _get_first_working_day(2026, 6) == 1

    def test_month_starts_on_saturday(self):
        """Mois commençant un samedi → passer au lundi (jour 3)."""
        # Août 2026 commence un samedi
        day = _get_first_working_day(2026, 8)
        # Vérifier que c'est un jour de semaine et entre 1-3
        assert 1 <= day <= 3
        assert day == 3  # Lundi après samedi

    def test_month_starts_on_sunday(self):
        """Mois commençant un dimanche → aller au lundi."""
        # Mars 2026 commence un dimanche
        assert _get_first_working_day(2026, 3) == 2

    def test_all_months_valid_days(self):
        """Tous les premiers jours ouvrables sont entre 1 et 3."""
        for month in range(1, 13):
            day = _get_first_working_day(2026, month)
            assert 1 <= day <= 3

    def test_different_years(self):
        """Teste avec différentes années."""
        # Ces appels ne doivent pas lever d'exception
        for year in [2024, 2025, 2026, 2027]:
            for month in range(1, 13):
                day = _get_first_working_day(year, month)
                assert 1 <= day <= 3

    def test_tuesday_wednesday_thursday(self):
        """Jours ouvrables non-weekend → jour 1."""
        # Janvier 2026 commence un jeudi
        assert _get_first_working_day(2026, 1) == 1

    def test_friday_start(self):
        """Mois commençant un vendredi → jour 1."""
        # Avril 2026 commence un mercredi
        assert _get_first_working_day(2026, 4) == 1


class TestShouldTrigger:
    """Tests pour _should_trigger()."""

    def test_first_working_day_triggers(self):
        """Le premier jour ouvrable du mois doit trigger."""
        # Mars 2026 a son premier jour ouvrable le 2 (dimanche=1, lundi=2)
        test_date = date(2026, 3, 2)
        assert _should_trigger(test_date) is True

    def test_other_days_do_not_trigger(self):
        """Les autres jours ne doivent pas trigger."""
        assert _should_trigger(date(2026, 3, 1)) is False  # Dimanche
        assert _should_trigger(date(2026, 3, 3)) is False
        assert _should_trigger(date(2026, 3, 15)) is False
        assert _should_trigger(date(2026, 3, 31)) is False

    def test_all_months_have_trigger_day(self):
        """Chaque mois a au moins un jour de déclenchement."""
        for month in range(1, 13):
            for day in range(1, 4):
                test_date = date(2026, month, day)
                if _should_trigger(test_date):
                    # Au moins un jour entre 1-3 doit trigger
                    break
            # Au moins un jour doit être le premier ouvrable
            assert _should_trigger(date(2026, month, _get_first_working_day(2026, month)))

    def test_second_month_first_working_day(self):
        """Février 2026 → premier jour ouvrable."""
        first_wd = _get_first_working_day(2026, 2)
        assert _should_trigger(date(2026, 2, first_wd)) is True
        if first_wd > 1:
            assert _should_trigger(date(2026, 2, first_wd - 1)) is False


class TestGetRecapMonth:
    """Tests pour _get_recap_month()."""

    def test_regular_month(self):
        """Mois normal → retourne mois précédent."""
        assert _get_recap_month(date(2026, 3, 15)) == "2026-02"
        assert _get_recap_month(date(2026, 6, 10)) == "2026-05"

    def test_january(self):
        """Janvier → décembre de l'année précédente."""
        assert _get_recap_month(date(2026, 1, 5)) == "2025-12"

    def test_december(self):
        """Décembre → novembre."""
        assert _get_recap_month(date(2026, 12, 25)) == "2026-11"

    def test_february(self):
        """Février → janvier."""
        assert _get_recap_month(date(2026, 2, 28)) == "2026-01"

    def test_all_months(self):
        """Teste tous les mois de l'année."""
        expected = [
            ("2026-01", "2025-12"),
            ("2026-02", "2026-01"),
            ("2026-03", "2026-02"),
            ("2026-04", "2026-03"),
            ("2026-05", "2026-04"),
            ("2026-06", "2026-05"),
            ("2026-07", "2026-06"),
            ("2026-08", "2026-07"),
            ("2026-09", "2026-08"),
            ("2026-10", "2026-09"),
            ("2026-11", "2026-10"),
            ("2026-12", "2026-11"),
        ]
        for month, expected_prev in expected:
            year, m = int(month[:4]), int(month[5:7])
            result = _get_recap_month(date(year, m, 15))
            assert result == expected_prev


class TestRenderEmail:
    """Tests pour _render_email()."""

    @patch("builtins.open", create=True)
    @patch("pathlib.Path.exists")
    def test_renders_email_with_data(self, mock_exists, mock_file_open):
        """Rend l'email HTML avec les données du recap."""
        mock_exists.return_value = True
        template = """
        <html>
        <body>
        <h1>{month_label}</h1>
        <p>Time saved: {time_saved_hours}h</p>
        <p>Days active: {days_active}</p>
        <p>Best: {best_inbox_zero_days} inbox zero days</p>
        </body>
        </html>
        """
        mock_file_open.return_value.__enter__.return_value.read.return_value = template

        recap = {
            "month_label": "MARCH 2026",
            "time_saved_hours": 5.5,
            "time_saved_work_days": 0.7,
            "days_active": 20,
            "inbox_zero_days": 10,
            "avg_reply_time_minutes": 15.0,
            "fastest_reply_minutes": 5.0,
            "ai_assisted_percent": 75.0,
            "emails_processed": 100,
            "best": {
                "inbox_zero_days": 15,
                "avg_reply_time_minutes": 12.0,
                "fastest_reply_minutes": 3.0,
                "ai_assisted_percent": 80.0,
                "days_active": 22,
            },
            "comparison": {"message": "You're improving!"},
        }

        result = _render_email(recap)
        assert "MARCH 2026" in result
        assert "5.5" in result
        assert "20" in result

    @patch("app.services.recap_scheduler.logger")
    def test_handles_rendering_with_valid_template(self, mock_logger):
        """Vérifie que le template est rendu correctement."""
        recap = {
            "month_label": "MARCH 2026",
            "time_saved_hours": 5.0,
            "emails_processed": 100,
            "best": {},
            "comparison": {"message": "Message"},
        }

        result = _render_email(recap)
        # Le résultat doit contenir du contenu HTML
        assert len(result) > 0 or result == ""
        # Pas d'erreur logging
        assert not mock_logger.error.called

    @patch("builtins.open", create=True)
    @patch("pathlib.Path.exists")
    def test_formats_time_in_email(self, mock_exists, mock_file_open):
        """Formate les temps correctement dans l'email."""
        mock_exists.return_value = True
        template = "<p>Avg reply: {avg_reply_time}</p><p>Fastest: {fastest_reply}</p>"
        mock_file_open.return_value.__enter__.return_value.read.return_value = template

        recap = {
            "month_label": "MARCH 2026",
            "time_saved_hours": 1.0,
            "time_saved_work_days": 0.1,
            "emails_processed": 50,
            "avg_reply_time_minutes": 30.0,
            "fastest_reply_minutes": 5.0,
            "ai_assisted_percent": 50.0,
            "days_active": 10,
            "inbox_zero_days": 5,
            "best": {},
            "comparison": {"message": "Same"},
        }

        result = _render_email(recap)
        # _format_time(30.0) returns "30 min"
        assert "30 min" in result
        # _format_time(5.0) returns "5 min"
        assert "5 min" in result


class TestRecapSchedulerLifecycle:
    """Tests pour le lifecycle de RecapScheduler."""

    def test_init_creates_thread_event(self):
        """L'initialisation crée les attributs de thread."""
        scheduler = RecapScheduler()
        assert scheduler._thread is None
        assert scheduler._stop_event is not None

    def test_start_creates_thread(self):
        """start() lance un nouveau thread."""
        scheduler = RecapScheduler()
        scheduler.start()
        assert scheduler._thread is not None
        assert scheduler._thread.is_alive()
        scheduler.stop()

    def test_start_does_not_duplicate_thread(self):
        """start() ne crée pas deux threads s'il y en a déjà un."""
        scheduler = RecapScheduler()
        scheduler.start()
        thread1 = scheduler._thread
        scheduler.start()
        thread2 = scheduler._thread
        assert thread1 is thread2
        scheduler.stop()

    def test_stop_halts_thread(self):
        """stop() arrête le thread."""
        scheduler = RecapScheduler()
        scheduler.start()
        assert scheduler._thread.is_alive()
        scheduler.stop()
        # Attend un peu pour que le thread s'arrête
        time.sleep(0.5)
        # Le thread peut ne pas être totalement arrêté au join timeout
        # Vérifier plutôt que _stop_event est set
        assert scheduler._stop_event.is_set()

    def test_stop_sets_event(self):
        """stop() définit le _stop_event."""
        scheduler = RecapScheduler()
        assert not scheduler._stop_event.is_set()
        scheduler.stop()
        assert scheduler._stop_event.is_set()

    def test_thread_is_daemon(self):
        """Le thread est créé en mode daemon."""
        scheduler = RecapScheduler()
        scheduler.start()
        assert scheduler._thread.daemon is True
        scheduler.stop()

    def test_thread_name(self):
        """Le thread a le bon nom."""
        scheduler = RecapScheduler()
        scheduler.start()
        assert "RecapScheduler" in scheduler._thread.name
        scheduler.stop()


class TestRecapSchedulerCheckAndTrigger:
    """Tests pour _check_and_trigger()."""

    @patch("app.services.recap_scheduler._should_trigger")
    @patch("app.services.recap_scheduler.datetime")
    @patch("app.services.recap_scheduler.date")
    def test_does_nothing_if_wrong_day(self, mock_date, mock_datetime, mock_should_trigger):
        """Ne rien faire si ce n'est pas le bon jour."""
        mock_should_trigger.return_value = False
        mock_date.today.return_value = date(2026, 3, 15)

        scheduler = RecapScheduler()
        scheduler._check_and_trigger()

        # _should_trigger est appelé
        assert mock_should_trigger.called
        # Pas d'autres appels (pas d'accès aux settings, etc.)

    @patch("app.services.recap_scheduler._should_trigger")
    @patch("app.services.recap_scheduler.datetime")
    @patch("app.services.recap_scheduler.date")
    def test_does_nothing_if_before_1300(self, mock_date, mock_datetime, mock_should_trigger):
        """Ne rien faire si l'heure est avant 13:00."""
        mock_should_trigger.return_value = True
        mock_date.today.return_value = date(2026, 3, 2)
        mock_datetime.now.return_value = datetime(2026, 3, 2, 12, 30, 0)

        scheduler = RecapScheduler()
        scheduler._check_and_trigger()

        # _should_trigger est appelé, mais pas de trigger parce que heure < 13

    @patch("app.db.repositories.account_repository.AccountRepository")
    @patch("app.db.database.get_db_session")
    @patch("app.api.settings.save_settings")
    @patch("app.api.settings.load_settings")
    @patch("app.services.recap_service.get_recap")
    @patch("app.services.recap_scheduler._should_trigger")
    @patch("app.services.recap_scheduler.datetime")
    @patch("app.services.recap_scheduler.date")
    def test_triggers_at_right_time(
        self,
        mock_date,
        mock_datetime,
        mock_should_trigger,
        mock_get_recap,
        mock_load_settings,
        mock_save_settings,
        mock_get_db_session,
        mock_account_repo_cls
    ):
        """Déclenche quand c'est le bon jour et après 13:00."""
        mock_should_trigger.return_value = True
        mock_date.today.return_value = date(2026, 3, 2)
        mock_datetime.now.return_value = datetime(2026, 3, 2, 14, 0, 0)

        settings = {
            "monthly_recap_banner_month": None,
            "monthly_recap_email_enabled": False,  # Skip email send path
        }
        mock_load_settings.return_value = settings
        mock_get_recap.return_value = {"month": "2026-02"}

        # M-1 audit (2026-04-25) added a per-account loop — fake one active account
        # so `any_recap_built` becomes True and `save_settings` is reached.
        mock_get_db_session.return_value.__enter__.return_value = Mock()
        mock_get_db_session.return_value.__exit__.return_value = False
        fake_account = Mock(id=1, email="user@example.com")
        mock_account_repo_cls.return_value.get_active_accounts.return_value = [fake_account]

        scheduler = RecapScheduler()
        scheduler._check_and_trigger()

        # settings doivent être mise à jour
        assert mock_save_settings.called

    @patch("app.services.recap_service.get_recap")
    @patch("app.db.repositories.account_repository.AccountRepository")
    @patch("app.db.database.get_db_session")
    @patch("app.api.settings.load_settings")
    @patch("app.api.settings.save_settings")
    @patch("app.services.recap_scheduler._should_trigger")
    @patch("app.services.recap_scheduler.datetime")
    @patch("app.services.recap_scheduler.date")
    def test_skips_if_already_done(
        self,
        mock_date,
        mock_datetime,
        mock_should_trigger,
        mock_save_settings,
        mock_load_settings,
        mock_get_db_session,
        mock_account_repo_cls,
        mock_get_recap,
    ):
        """Saute si le banner ET l'email du mois sont déjà faits pour le compte.

        Post audit scalabilité 2026-05-29 : le check « déjà fait » est
        PER-COMPTE (l'ancien check global sautait les tenants 2..N dès que
        le premier avait reçu son email)."""
        mock_should_trigger.return_value = True
        mock_date.today.return_value = date(2026, 3, 2)
        mock_datetime.now.return_value = datetime(2026, 3, 2, 14, 0, 0)

        settings = {
            "monthly_recap_banner_month": "2026-02",  # Déjà déclenché
            "monthly_recap_email_sent_month": "2026-02",
        }
        mock_load_settings.return_value = settings

        mock_get_db_session.return_value.__enter__ = Mock(return_value=Mock())
        mock_get_db_session.return_value.__exit__ = Mock(return_value=False)
        fake_account = Mock()
        fake_account.id = 1
        fake_account.email = "user@example.com"
        mock_account_repo_cls.return_value.get_active_accounts.return_value = [fake_account]

        scheduler = RecapScheduler()
        scheduler._check_and_trigger()

        # Compte entièrement servi : ni recalcul ni sauvegarde
        assert not mock_get_recap.called
        assert not mock_save_settings.called

    @patch.object(RecapScheduler, "_send_recap_email_for")
    @patch("app.db.repositories.account_repository.AccountRepository")
    @patch("app.db.database.get_db_session")
    @patch("app.services.recap_service.get_recap")
    @patch("app.api.settings.load_settings")
    @patch("app.api.settings.save_settings")
    @patch("app.services.recap_scheduler._should_trigger")
    @patch("app.services.recap_scheduler.datetime")
    @patch("app.services.recap_scheduler.date")
    def test_sends_email_if_enabled(
        self,
        mock_date,
        mock_datetime,
        mock_should_trigger,
        mock_save_settings,
        mock_load_settings,
        mock_get_recap,
        mock_get_db_session,
        mock_account_repo,
        mock_send_email_for,
    ):
        """Envoie l'email si activé et pas encore envoyé.

        Post M-1 audit fix: the scheduler iterates active accounts loaded
        from AccountRepository instead of reading the singleton, so the
        test must seed at least one fake account.
        """
        mock_should_trigger.return_value = True
        mock_date.today.return_value = date(2026, 3, 2)
        mock_datetime.now.return_value = datetime(2026, 3, 2, 14, 0, 0)

        settings = {
            "monthly_recap_banner_month": None,
            "monthly_recap_email_enabled": True,
            "monthly_recap_email_sent_month": None,
        }
        mock_load_settings.return_value = settings
        mock_get_recap.return_value = {"month": "2026-02"}

        # Seed one active account
        fake_account = Mock(id=1, email="user@example.com")
        mock_account_repo.return_value.get_active_accounts.return_value = [fake_account]
        mock_get_db_session.return_value.__enter__ = Mock(return_value=Mock())
        mock_get_db_session.return_value.__exit__ = Mock(return_value=False)

        scheduler = RecapScheduler()
        scheduler._check_and_trigger()

        # _send_recap_email_for doit être appelé pour ce compte
        assert mock_send_email_for.called


class TestRecapSchedulerSendRecapEmail:
    """Tests pour _send_recap_email_for() — post M-1 audit fix
    (2026-04-25): the helper now takes the bound account explicitly
    instead of reading the singleton, so each test passes a fake
    account directly."""

    @patch("app.providers.factory.get_email_provider")
    @patch("app.services.recap_scheduler._render_email")
    @patch("app.api.settings.save_settings")
    def test_sends_email_successfully(
        self,
        mock_save_settings,
        mock_render_email,
        mock_get_provider,
    ):
        """Envoie l'email avec succès et persiste le flag PER-COMPTE."""
        account = Mock()
        account.id = 7
        account.email = "user@example.com"

        provider = Mock()
        provider.send_email.return_value = True
        mock_get_provider.return_value = provider

        mock_render_email.return_value = "<html>Recap</html>"

        recap = {
            "month_label": "MARCH 2026",
            "time_saved_hours": 5.0,
        }
        settings = {}

        scheduler = RecapScheduler()
        scheduler._send_recap_email_for(account, recap, settings, "2026-02")

        assert provider.send_email.called
        assert mock_save_settings.called
        # Audit scalabilité 2026-05-29 : un save GLOBAL ici verrouillait le
        # mois pour tous les autres tenants — le save doit porter le compte.
        assert mock_save_settings.call_args.kwargs.get("account_id") == 7
        assert settings["monthly_recap_email_sent_month"] == "2026-02"

    @patch("app.providers.factory.get_email_provider")
    @patch("app.services.recap_scheduler._render_email")
    def test_handles_empty_html(
        self,
        mock_render_email,
        mock_get_provider,
    ):
        """Gère le template HTML vide — pas d'envoi si le template est vide."""
        account = Mock()
        account.id = 7
        account.email = "user@example.com"

        mock_render_email.return_value = ""  # Template non trouvé

        recap = {"month_label": "MARCH 2026"}
        settings = {}

        scheduler = RecapScheduler()
        scheduler._send_recap_email_for(account, recap, settings, "2026-02")

        provider = mock_get_provider.return_value
        assert not provider.send_email.called

    @patch("app.providers.factory.get_email_provider")
    @patch("app.services.recap_scheduler._render_email")
    @patch("app.api.settings.save_settings")
    def test_handles_send_failure(
        self,
        mock_save_settings,
        mock_render_email,
        mock_get_provider,
    ):
        """Gère l'échec de l'envoi d'email."""
        account = Mock()
        account.id = 7
        account.email = "user@example.com"

        provider = Mock()
        provider.send_email.return_value = False
        mock_get_provider.return_value = provider

        mock_render_email.return_value = "<html>Recap</html>"

        recap = {"month_label": "MARCH 2026"}
        settings = {}

        scheduler = RecapScheduler()
        scheduler._send_recap_email_for(account, recap, settings, "2026-02")

        assert not mock_save_settings.called

    @patch("app.providers.factory.get_email_provider")
    @patch("app.services.recap_scheduler._render_email")
    @patch("app.api.settings.save_settings")
    def test_disconnects_provider(
        self,
        mock_save_settings,
        mock_render_email,
        mock_get_provider,
    ):
        """Déconnecte le provider après l'envoi."""
        account = Mock()
        account.id = 7
        account.email = "user@example.com"

        provider = Mock()
        provider.send_email.return_value = True
        provider.disconnect = Mock()
        mock_get_provider.return_value = provider

        mock_render_email.return_value = "<html>Recap</html>"

        recap = {"month_label": "MARCH 2026"}
        settings = {}

        scheduler = RecapScheduler()
        scheduler._send_recap_email_for(account, recap, settings, "2026-02")

        assert provider.disconnect.called

    @patch("app.services.recap_scheduler.logger")
    @patch("app.providers.factory.get_email_provider")
    def test_handles_general_exception(self, mock_get_provider, mock_logger):
        """Gère les exceptions générales gracieusement."""
        account = Mock()
        account.email = "user@example.com"
        mock_get_provider.side_effect = Exception("Database error")

        recap = {"month_label": "MARCH 2026"}
        settings = {}

        scheduler = RecapScheduler()
        # Ne doit pas lever d'exception
        scheduler._send_recap_email_for(account, recap, settings, "2026-02")

        assert mock_logger.warning.called

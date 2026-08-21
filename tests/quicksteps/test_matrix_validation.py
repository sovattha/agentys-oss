# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Matrice de validation exhaustive Quick Steps — chaque condition × chaque action.

Validation 2026-06-09 : un seul fichier qui prouve que CHAQUE type de
condition (15) et CHAQUE type d'action (14) fonctionne réellement, pas
seulement qu'il est déclaré dans le schéma.

Part A — conditions, via ``auto_trigger._match_condition`` (l'implémentation
unique partagée par les triggers de step ET les guards ``if`` d'action —
cf. ``engine._evaluate_action_guard``) : tous les ``match_mode``, les deux
polarités, et ``negate``. Les deux conditions SQL-backed
(``no_reply_after_days``, ``thread_has_user_reply``) ont leur chemin SQL
couvert par ``test_no_reply_after_days.py`` / ``test_thread_has_user_reply.py``
— ici on verrouille leurs gardes pures (pas de session requise).

Part B — actions, via ``engine.execute`` (le vrai moteur, pas le handler nu),
provider + stores doublés : happy path + effet de bord observable pour chacune.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.quicksteps import engine
from app.quicksteps.auto_trigger import _match_condition


# --------------------------------------------------------------------------- #
# Email factice — chaque attribut que le matcher ou un handler peut lire.
# --------------------------------------------------------------------------- #

@dataclass
class MatrixEmail:
    sender: str = "boss@example.com"
    sender_name: str = "The Boss"
    subject: str = "Invoice #42"
    recipients: str = "a@x.com, b@y.com"
    # Forme sent-side (SentEmailRef) — le handler followup lit le singulier.
    recipient: str = ""
    cc: str = ""
    body: str = "please pay the invoice"
    body_html: str = "<p>please pay the invoice</p>"
    body_text: str = "please pay the invoice"
    attachments_meta: str = ""
    is_read: bool = False
    deadline_at: Any = None
    emoji_marker_json: str = ""
    thread_id: str = "thread-1"
    conversation_id: str = ""
    id: str = "msg-1"
    date: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    labels: Any = None
    headers: Any = None
    in_reply_to: Any = None
    references: Any = None
    original_email_id: Any = None


def _m(condition: dict, email: MatrixEmail, **kw) -> bool:
    return _match_condition(condition, email, **kw)


# --------------------------------------------------------------------------- #
# Part A — les 15 conditions
# --------------------------------------------------------------------------- #

class TestSenderConditions:
    def test_sender_is_matches_case_insensitive(self):
        c = {"type": "sender", "match_mode": "is", "value": " Boss@Example.com "}
        assert _m(c, MatrixEmail()) is True

    def test_sender_is_no_match(self):
        c = {"type": "sender", "match_mode": "is", "value": "other@x.com"}
        assert _m(c, MatrixEmail()) is False

    def test_sender_contains(self):
        assert _m({"type": "sender", "match_mode": "contains", "value": "boss"}, MatrixEmail()) is True
        assert _m({"type": "sender", "match_mode": "contains", "value": "zzz"}, MatrixEmail()) is False

    def test_sender_matches_regex(self):
        assert _m({"type": "sender", "match_mode": "matches", "value": "^boss@"}, MatrixEmail()) is True
        assert _m({"type": "sender", "match_mode": "matches", "value": "^zzz"}, MatrixEmail()) is False

    def test_sender_negate_flips(self):
        c = {"type": "sender", "match_mode": "is", "value": "boss@example.com", "negate": True}
        assert _m(c, MatrixEmail()) is False

    def test_empty_value_never_matches(self):
        assert _m({"type": "sender", "match_mode": "is", "value": ""}, MatrixEmail()) is False


class TestSenderDomainConditions:
    def test_domain_is(self):
        assert _m({"type": "sender_domain", "match_mode": "is", "value": "example.com"}, MatrixEmail()) is True
        assert _m({"type": "sender_domain", "match_mode": "is", "value": "other.com"}, MatrixEmail()) is False

    def test_domain_contains(self):
        assert _m({"type": "sender_domain", "match_mode": "contains", "value": "ample"}, MatrixEmail()) is True

    def test_domain_matches_regex(self):
        assert _m(
            {"type": "sender_domain", "match_mode": "matches", "value": r"example\.(com|org)$"},
            MatrixEmail(),
        ) is True

    def test_no_at_sign_means_no_domain(self):
        assert _m(
            {"type": "sender_domain", "match_mode": "is", "value": "example.com"},
            MatrixEmail(sender="not-an-email"),
        ) is False


class TestRecipientConditions:
    def test_recipient_is_matches_one_parsed_address(self):
        assert _m({"type": "recipient", "match_mode": "is", "value": "b@y.com"}, MatrixEmail()) is True
        # "is" = égalité d'une adresse, pas substring du champ joint
        assert _m({"type": "recipient", "match_mode": "is", "value": "y.com"}, MatrixEmail()) is False

    def test_recipient_contains(self):
        assert _m({"type": "recipient", "match_mode": "contains", "value": "y.com"}, MatrixEmail()) is True

    def test_recipient_matches_regex(self):
        assert _m({"type": "recipient", "match_mode": "matches", "value": r"b@y\."}, MatrixEmail()) is True


class TestEmailTextConditions:
    def test_subject_scope(self):
        assert _m({"type": "email_text", "match_mode": "subject", "value": "invoice"}, MatrixEmail()) is True
        assert _m({"type": "email_text", "match_mode": "subject", "value": "pay the"}, MatrixEmail()) is False

    def test_body_scope(self):
        assert _m({"type": "email_text", "match_mode": "body", "value": "pay the"}, MatrixEmail()) is True
        assert _m({"type": "email_text", "match_mode": "body", "value": "#42"}, MatrixEmail()) is False

    def test_anywhere_scope(self):
        assert _m({"type": "email_text", "match_mode": "anywhere", "value": "#42"}, MatrixEmail()) is True
        assert _m({"type": "email_text", "match_mode": "anywhere", "value": "pay the"}, MatrixEmail()) is True
        assert _m({"type": "email_text", "match_mode": "anywhere", "value": "licorne"}, MatrixEmail()) is False

    def test_sent_side_body_preview_fallback(self):
        # SentEmailRef expose body_preview, pas body — le matcher doit retomber dessus.
        @dataclass
        class SentRef:
            sender: str = "me@x.com"
            subject: str = "Suivi"
            body_preview: str = "merci de confirmer la facture"
        assert _m({"type": "email_text", "match_mode": "body", "value": "facture"}, SentRef()) is True


class TestBooleanAttributeConditions:
    def test_has_attachment_both_polarities(self):
        with_att = MatrixEmail(attachments_meta='[{"name": "f.pdf"}]')
        without = MatrixEmail(attachments_meta="")
        assert _m({"type": "has_attachment", "value": "true"}, with_att) is True
        assert _m({"type": "has_attachment", "value": "true"}, without) is False
        assert _m({"type": "has_attachment", "value": "false"}, without) is True
        assert _m({"type": "has_attachment", "value": "false"}, with_att) is False

    def test_is_read_both_polarities(self):
        assert _m({"type": "is_read", "value": "true"}, MatrixEmail(is_read=True)) is True
        assert _m({"type": "is_read", "value": "true"}, MatrixEmail(is_read=False)) is False
        assert _m({"type": "is_read", "value": "false"}, MatrixEmail(is_read=False)) is True

    def test_has_deadline_detected_both_polarities(self):
        soon = datetime.now(timezone.utc) + timedelta(days=3)
        assert _m({"type": "has_deadline_detected", "value": "true"}, MatrixEmail(deadline_at=soon)) is True
        assert _m({"type": "has_deadline_detected", "value": "true"}, MatrixEmail()) is False
        assert _m({"type": "has_deadline_detected", "value": "false"}, MatrixEmail()) is True

    def test_has_emoji_marker_both_polarities(self):
        marked = MatrixEmail(emoji_marker_json='{"emoji": "💰"}')
        assert _m({"type": "has_emoji_marker", "value": "true"}, marked) is True
        assert _m({"type": "has_emoji_marker", "value": "true"}, MatrixEmail()) is False
        assert _m({"type": "has_emoji_marker", "value": "false"}, MatrixEmail()) is True


class TestHasLabelCondition:
    def test_snapshot_frozenset_path(self):
        email = MatrixEmail(labels=frozenset({"facture"}))
        assert _m({"type": "has_label", "value": "Facture"}, email) is True
        assert _m({"type": "has_label", "value": "newsletter"}, email) is False

    def test_store_lookup_path(self, monkeypatch):
        from app.quicksteps import auto_trigger
        monkeypatch.setattr(
            auto_trigger, "_get_email_label_names",
            lambda _eid, _aid: {"newsletter"},
        )
        email = MatrixEmail(labels=None)
        assert _m({"type": "has_label", "value": "newsletter"}, email,
                  account_id=1, email_id="msg-1") is True
        assert _m({"type": "has_label", "value": "facture"}, email,
                  account_id=1, email_id="msg-1") is False


class TestCalendarInviteCondition:
    def test_any_matches_ics_block(self):
        email = MatrixEmail(body="BEGIN:VCALENDAR\nVERSION:2.0")
        assert _m({"type": "calendar_invite", "match_mode": "any", "value": "true"}, email) is True

    def test_any_matches_subject_pattern(self):
        email = MatrixEmail(subject="Invitation: point projet")
        assert _m({"type": "calendar_invite", "match_mode": "any", "value": "true"}, email) is True

    def test_any_matches_meet_url(self):
        email = MatrixEmail(body_html='<a href="https://meet.google.com/abc-defg">join</a>')
        assert _m({"type": "calendar_invite", "match_mode": "any", "value": "true"}, email) is True

    def test_any_matches_brand_mention(self):
        email = MatrixEmail(body="Join the Microsoft Teams meeting tomorrow")
        assert _m({"type": "calendar_invite", "match_mode": "any", "value": "true"}, email) is True

    def test_any_rejects_plain_email(self):
        assert _m({"type": "calendar_invite", "match_mode": "any", "value": "true"}, MatrixEmail()) is False

    def test_free_matches_when_user_free(self, monkeypatch):
        from app.quicksteps import auto_trigger
        start = datetime.now(timezone.utc) + timedelta(days=1)
        monkeypatch.setattr(auto_trigger, "_extract_invite_window",
                            lambda _aid, _e, _eid: (start, start + timedelta(hours=1)))
        monkeypatch.setattr(auto_trigger, "_is_user_busy_window",
                            lambda _aid, _s, _e: False)
        assert _m({"type": "calendar_invite", "match_mode": "free", "value": "true"},
                  MatrixEmail(), account_id=1) is True

    def test_free_rejects_when_busy(self, monkeypatch):
        from app.quicksteps import auto_trigger
        start = datetime.now(timezone.utc) + timedelta(days=1)
        monkeypatch.setattr(auto_trigger, "_extract_invite_window",
                            lambda _aid, _e, _eid: (start, start + timedelta(hours=1)))
        monkeypatch.setattr(auto_trigger, "_is_user_busy_window",
                            lambda _aid, _s, _e: True)
        assert _m({"type": "calendar_invite", "match_mode": "free", "value": "true"},
                  MatrixEmail(), account_id=1) is False

    def test_free_fails_closed_without_window(self, monkeypatch):
        from app.quicksteps import auto_trigger
        monkeypatch.setattr(auto_trigger, "_extract_invite_window",
                            lambda _aid, _e, _eid: None)
        assert _m({"type": "calendar_invite", "match_mode": "free", "value": "true"},
                  MatrixEmail(), account_id=1) is False


class TestTemporalConditions:
    def test_email_older_than_days(self):
        old = MatrixEmail(date=datetime.now(timezone.utc) - timedelta(days=10))
        recent = MatrixEmail(date=datetime.now(timezone.utc) - timedelta(days=2))
        assert _m({"type": "email_older_than_days", "value": "7"}, old) is True
        assert _m({"type": "email_older_than_days", "value": "7"}, recent) is False

    def test_email_older_than_days_naive_datetime_assumed_utc(self):
        old_naive = MatrixEmail(date=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10))
        assert _m({"type": "email_older_than_days", "value": "7"}, old_naive) is True

    def test_email_older_than_days_invalid_value(self):
        old = MatrixEmail(date=datetime.now(timezone.utc) - timedelta(days=10))
        assert _m({"type": "email_older_than_days", "value": "abc"}, old) is False

    def test_no_reply_after_days_pure_guards(self):
        # account_id=0 / value non-int → jamais de requête SQL, False.
        # Le chemin SQL est couvert par test_no_reply_after_days.py.
        assert _m({"type": "no_reply_after_days", "value": "3"}, MatrixEmail()) is False
        assert _m({"type": "no_reply_after_days", "value": "abc"}, MatrixEmail(), account_id=1) is False


class TestThreadShapeConditions:
    def test_is_new_thread_true_for_initiator(self):
        assert _m({"type": "is_new_thread", "value": "true"}, MatrixEmail()) is True

    def test_is_new_thread_false_for_reply(self):
        reply = MatrixEmail(in_reply_to="<orig@x.com>")
        assert _m({"type": "is_new_thread", "value": "true"}, reply) is False
        assert _m({"type": "is_new_thread", "value": "false"}, reply) is True

    def test_is_new_thread_headers_dict_detected(self):
        reply = MatrixEmail(headers={"In-Reply-To": "<orig@x.com>"})
        assert _m({"type": "is_new_thread", "value": "true"}, reply) is False

    def test_is_new_thread_negate(self):
        assert _m({"type": "is_new_thread", "value": "true", "negate": True}, MatrixEmail()) is False

    def test_thread_has_user_reply_pure_guards(self):
        # Sans account_id la requête SQL ne part jamais → has_reply=False.
        # value "true" ne matche pas ; value "false" matche (sémantique
        # "je n'ai pas répondu"). Chemin SQL : test_thread_has_user_reply.py.
        assert _m({"type": "thread_has_user_reply", "value": "true"}, MatrixEmail()) is False
        assert _m({"type": "thread_has_user_reply", "value": "false"}, MatrixEmail()) is True


class TestWorkflowConditions:
    def test_previously_auto_actioned_by(self, monkeypatch):
        from app.quicksteps import auto_trigger
        step_uuid = "22222222-2222-4222-8222-222222222222"
        monkeypatch.setattr(auto_trigger, "_step_fired_on_thread",
                            lambda _aid, sid, _tid: sid == step_uuid)
        c = {"type": "previously_auto_actioned_by", "value": step_uuid}
        assert _m(c, MatrixEmail(), account_id=1) is True
        other = {"type": "previously_auto_actioned_by", "value": "33333333-3333-4333-8333-333333333333"}
        assert _m(other, MatrixEmail(), account_id=1) is False

    def test_previously_auto_actioned_by_requires_thread(self, monkeypatch):
        from app.quicksteps import auto_trigger
        monkeypatch.setattr(auto_trigger, "_step_fired_on_thread",
                            lambda *_a: True)
        c = {"type": "previously_auto_actioned_by", "value": "22222222-2222-4222-8222-222222222222"}
        assert _m(c, MatrixEmail(thread_id=""), account_id=1) is False


class TestLegacyConditionMigration:
    def test_legacy_subject_keyword_still_matches(self):
        # v1: le type encodait l'opérateur — migré en interne avant matching.
        assert _m({"type": "subject_keyword", "value": "invoice"}, MatrixEmail()) is True

    def test_legacy_is_calendar_invite_still_matches(self):
        email = MatrixEmail(body="BEGIN:VCALENDAR")
        assert _m({"type": "is_calendar_invite", "value": "true"}, email) is True


# --------------------------------------------------------------------------- #
# Part B — les 14 actions, via engine.execute
# --------------------------------------------------------------------------- #

class MatrixProvider:
    """Provider doublé couvrant chaque méthode que les 14 handlers touchent."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def archive_email(self, raw_id):
        self.calls.append(("archive", {"raw_id": raw_id}))
        return True

    def move_to_inbox(self, raw_id):
        self.calls.append(("move_to_inbox", {"raw_id": raw_id}))
        return True

    def delete_email(self, raw_id):
        self.calls.append(("delete", {"raw_id": raw_id}))
        return True

    def mark_as_read(self, raw_id):
        self.calls.append(("mark_as_read", {"raw_id": raw_id}))
        return True

    def mark_as_unread(self, raw_id):
        self.calls.append(("mark_as_unread", {"raw_id": raw_id}))
        return True

    def move_to_spam(self, raw_id):
        self.calls.append(("move_to_spam", {"raw_id": raw_id}))
        return True

    def send_reply_directly(self, **kwargs):
        self.calls.append(("reply", kwargs))
        return "sent-reply-1"

    def send_new_directly(self, **kwargs):
        self.calls.append(("forward", kwargs))
        return "sent-fwd-1"

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)


def _step(actions, step_id="11111111-1111-4111-8111-111111111111"):
    return {"id": step_id, "name": "matrix", "actions": actions, "enabled": True}


def _run(step, *, email=None, email_id="msg-1", account_id=1):
    provider = MatrixProvider()
    report = engine.execute(
        account_id=account_id,
        step=step,
        email_id=email_id,
        idempotency_key=None,
        provider_factory=lambda: provider,
        email_loader=lambda _p, _eid, _aid: email if email is not None else MatrixEmail(),
        account_loader=lambda _aid: ("me@example.com", "Me"),
    )
    return report, provider


@pytest.fixture(autouse=True)
def _fresh_idempotency():
    engine._idem_clear_for_tests()
    yield
    engine._idem_clear_for_tests()


@contextmanager
def _noop():
    yield


class _FakeAccount:
    def __init__(self):
        self.pinned_email_ids_json = "[]"


class _FakeDbSession:
    """Double minimal de session SQLAlchemy pour pin/mark_with_emoji."""

    def __init__(self, account=None):
        self.account = account
        self.committed = False

    def get(self, _model, _pk):
        return self.account

    def commit(self):
        self.committed = True


class TestProviderBackedActions:
    def test_archive(self):
        report, p = _run(_step([{"type": "archive"}]))
        assert report.success is True
        assert p.called("archive")

    def test_unarchive(self):
        report, p = _run(_step([{"type": "unarchive"}]))
        assert report.success is True
        assert p.called("move_to_inbox")

    def test_delete(self):
        report, p = _run(_step([{"type": "delete"}]))
        assert report.success is True
        assert p.called("delete")

    def test_mark_read_true_and_false(self):
        report, p = _run(_step([{"type": "mark_read", "payload": {"value": True}}]))
        assert report.success is True
        assert p.called("mark_as_read")
        report2, p2 = _run(_step([{"type": "mark_read", "payload": {"value": False}}]))
        assert report2.success is True
        assert p2.called("mark_as_unread")

    def test_move_to_spam(self):
        report, p = _run(_step([{"type": "move_to_spam"}]))
        assert report.success is True
        assert p.called("move_to_spam")

    def test_reply_template_with_variable(self):
        report, p = _run(_step([{
            "type": "reply_template",
            "payload": {"body": "Merci {sender.firstname} !", "replyAll": False, "includeQuoted": True},
        }]))
        assert report.success is True
        assert p.called("reply")
        kwargs = next(c[1] for c in p.calls if c[0] == "reply")
        body_blob = json.dumps(kwargs, default=str)
        assert "The" in body_blob  # {sender.firstname} résolu depuis "The Boss"

    def test_forward_direct_recipients(self):
        report, p = _run(_step([{
            "type": "forward",
            "payload": {"to": ["dest@x.com"], "subject_prefix": "Fwd:"},
        }]))
        assert report.success is True
        assert p.called("forward")


class TestStoreBackedActions:
    def test_pin_persists_to_account_row(self, monkeypatch):
        import app.api.routes_helpers as routes_helpers
        account = _FakeAccount()
        session = _FakeDbSession(account=account)

        @contextmanager
        def fake_session():
            yield session

        monkeypatch.setattr(routes_helpers, "get_db_session", fake_session)
        report, _ = _run(_step([{"type": "pin"}]))
        assert report.success is True
        assert "msg-1" in json.loads(account.pinned_email_ids_json)
        assert session.committed is True

    def test_mark_with_emoji_stamps_row(self, monkeypatch):
        import app.api.routes_helpers as routes_helpers
        import app.db.repositories.email_repository as email_repo_module

        row = type("Row", (), {"emoji_marker_json": ""})()
        session = _FakeDbSession()

        @contextmanager
        def fake_session():
            yield session

        class FakeRepo:
            def __init__(self, _session):
                pass

            def get_by_email_id(self, _eid, account_id=None):
                return row

        monkeypatch.setattr(routes_helpers, "get_db_session", fake_session)
        monkeypatch.setattr(email_repo_module, "EmailRepository", FakeRepo)
        report, _ = _run(_step([{
            "type": "mark_with_emoji",
            "payload": {"emoji": "💰", "text": "Stripe"},
        }]))
        assert report.success is True
        marker = json.loads(row.emoji_marker_json)
        assert marker == {"emoji": "💰", "text": "Stripe"}
        assert session.committed is True

    def test_apply_label_saves_assignment(self, monkeypatch):
        import app.infrastructure.container as container_module

        saved = {}

        class FakeLabelStore:
            def get_assignment(self, _eid):
                return None

            def save_assignment(self, assignment):
                saved["assignment"] = assignment

        class FakeContainer:
            def get_label_store(self, account_id=None):
                return FakeLabelStore()

        monkeypatch.setattr(container_module, "get_container", lambda: FakeContainer())
        report, _ = _run(_step([{
            "type": "apply_label",
            "payload": {"label": "Facture"},
        }]))
        assert report.success is True
        assert "Facture" in saved["assignment"].labels

    def test_rsvp_meeting_happy_path(self, monkeypatch):
        # test_rsvp_handler.py ne couvre QUE les échecs du bridge OAuth —
        # le happy path complet (rsvp_event ok) est verrouillé ici.
        from app import multi_accounts
        from app.providers import calendar_factory
        import app.infrastructure.container as container_module

        class _Cfg:
            id = "hex-abc"

        class _Mgr:
            def get_account_by_email(self, _email):
                return _Cfg()

        class _FakeCal:
            def rsvp_event(self, raw_id, response):
                return {"ok": True, "event_id": f"evt-{raw_id}-{response}"}

        class _NoLabelContainer:
            def get_label_store(self, account_id=None):
                return None  # relabel post-RSVP best-effort → early return

        monkeypatch.setattr(multi_accounts, "get_account_manager", lambda: _Mgr())
        monkeypatch.setattr(calendar_factory, "create_calendar_provider", lambda _id: _FakeCal())
        monkeypatch.setattr(container_module, "get_container", lambda: _NoLabelContainer())

        report, _ = _run(_step([{
            "type": "rsvp_meeting",
            "payload": {"response": "accepted"},
        }]))
        assert report.success is True

    def test_create_reminder_from_deadline(self, monkeypatch):
        import app.services.reminder_service as reminder_service

        captured = {}

        def fake_add_reminder(*, email_id, subject, reminder_date_iso, account_id, reminder_type):
            captured.update(email_id=email_id, reminder_type=reminder_type,
                            fire_at=reminder_date_iso)
            return "rem-1"

        monkeypatch.setattr(reminder_service, "add_reminder", fake_add_reminder)
        deadline = datetime.now(timezone.utc) + timedelta(days=10)
        report, _ = _run(
            _step([{"type": "create_reminder", "payload": {"days_before": 2}}]),
            email=MatrixEmail(deadline_at=deadline),
        )
        assert report.success is True
        assert captured["reminder_type"] == "deadline"
        assert captured["email_id"] == "msg-1"

    def test_create_reminder_fails_without_deadline(self, monkeypatch):
        # Pas de deadline_at ni d'extraction live sur ce body → échec propre.
        import app.quicksteps.deadline_extractor as extractor
        monkeypatch.setattr(extractor, "extract_deadline",
                            lambda **_kw: None)
        report, _ = _run(
            _step([{"type": "create_reminder", "payload": {"days_before": 2}}]),
            email=MatrixEmail(deadline_at=None),
        )
        assert report.success is False
        assert report.error == "no_deadline_detected"

    def test_create_calendar_event_from_deadline(self, monkeypatch):
        from app import multi_accounts
        from app.providers import calendar_factory

        class _Cfg:
            id = "hex-abc"

        class _Mgr:
            def get_account_by_email(self, _email):
                return _Cfg()

        created = {}

        class _FakeCal:
            def create_event(self, event):
                created["title"] = event.title
                created["start"] = event.start
                return {"event_id": "evt-9"}

        monkeypatch.setattr(multi_accounts, "get_account_manager", lambda: _Mgr())
        monkeypatch.setattr(calendar_factory, "create_calendar_provider", lambda _id: _FakeCal())

        deadline = datetime.now(timezone.utc) + timedelta(days=10)
        report, _ = _run(
            _step([{
                "type": "create_calendar_event",
                "payload": {"days_before": 2, "duration_minutes": 30},
            }]),
            email=MatrixEmail(deadline_at=deadline),
        )
        assert report.success is True
        assert created["title"].startswith("⏰")

    def test_create_snoozed_followup_draft(self, monkeypatch):
        import app.infrastructure.container as container_module
        import app.services.reminder_service as reminder_service

        drafts = {}

        class FakeDraftStore:
            def add(self, draft):
                drafts[draft.id] = draft
                return draft.id

            def delete(self, draft_id):
                return drafts.pop(draft_id, None) is not None

            def get_by_id(self, draft_id):
                return drafts.get(draft_id)

        class FakeContainer:
            def get_pending_draft_store(self):
                return FakeDraftStore()

        reminders = {}

        def fake_add_reminder(*, email_id, subject, reminder_date_iso, account_id, reminder_type):
            reminders.update(type=reminder_type, date=reminder_date_iso)
            return "rem-2"

        monkeypatch.setattr(container_module, "get_container", lambda: FakeContainer())
        monkeypatch.setattr(reminder_service, "add_reminder", fake_add_reminder)

        sent_email = MatrixEmail(
            sender="me@example.com",
            recipient="alex.doe@acme.com",
            recipients="alex.doe@acme.com",
            subject="Proposition Q3",
            thread_id="thread-sent-1",
        )
        report, _ = _run(
            _step([{
                "type": "create_snoozed_followup_draft",
                "payload": {"body": "Bonjour {{recipient_first_name}}, des nouvelles de {{original_subject}} ?",
                            "delay_days": 7},
            }]),
            email=sent_email,
            email_id="sent-1",
        )
        assert report.success is True
        assert len(drafts) == 1
        draft = next(iter(drafts.values()))
        assert "Alex" in draft.draft_body
        assert "Proposition Q3" in draft.draft_body


class TestActionGuards:
    def test_guard_not_satisfied_skips_action_but_chain_succeeds(self):
        step = _step([
            {
                "type": "archive",
                "if": {"operator": "AND",
                       "triggers": [{"type": "sender", "match_mode": "is", "value": "nobody@x.com"}]},
            },
            {"type": "mark_read", "payload": {"value": True}},
        ])
        report, p = _run(step)
        assert report.success is True
        assert report.actions[0].error == "skipped"
        assert report.actions[0].ok is True
        assert not p.called("archive")
        assert p.called("mark_as_read")

    def test_guard_satisfied_runs_action(self):
        step = _step([{
            "type": "archive",
            "if": {"operator": "OR",
                   "triggers": [
                       {"type": "sender", "match_mode": "is", "value": "nobody@x.com"},
                       {"type": "email_text", "match_mode": "subject", "value": "invoice"},
                   ]},
        }])
        report, p = _run(step)
        assert report.success is True
        assert p.called("archive")


class TestSchemaMatrixParity:
    def test_every_allowed_action_has_a_handler(self):
        from app.quicksteps.schema import _ALLOWED_ACTION_TYPES
        from app.quicksteps.registry import ACTION_HANDLERS
        assert set(_ALLOWED_ACTION_TYPES) == set(ACTION_HANDLERS.keys())

    def test_every_condition_type_reaches_a_matcher_branch(self):
        # Chaque type validé par le schéma doit avoir une branche dans
        # _match_condition — un type sans branche tombe au `return` final
        # avec raw_match=False et ne matcherait JAMAIS (rule morte silencieuse).
        import inspect
        from app.quicksteps.schema import _TRIGGER_CONDITION_TYPES
        from app.quicksteps import auto_trigger
        src = inspect.getsource(auto_trigger._match_condition)
        for ctype in _TRIGGER_CONDITION_TYPES:
            assert f'"{ctype}"' in src, f"condition {ctype} sans branche matcher"

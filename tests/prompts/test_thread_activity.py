"""Tests pour thread_activity (#189).

Le helper génère un signal d'activité que le DrafterAgent utilise pour
décider d'omettre la salutation dans un thread actif. Les tests couvrent :
- Profondeurs limites (0, 1, 2, N)
- Gaps temporels (récent / ancien)
- Dates manquantes ou invalides (tolérance)
- Sérialisation du bloc prompt
"""

from datetime import datetime, timedelta, timezone


from app.prompts.thread_activity import (
    ACTIVE_THREAD_MAX_GAP_MINUTES,
    ACTIVE_THREAD_MIN_MESSAGES,
    ThreadActivity,
    analyze,
    build_thread_activity_block,
)


def _msg(date: datetime | str | None, body: str = "x") -> dict:
    return {"date": date.isoformat() if isinstance(date, datetime) else date, "body": body}


class TestAnalyze:
    def test_empty_history(self):
        a = analyze(None)
        assert a.depth == 0
        assert not a.is_active

    def test_single_message_history(self):
        a = analyze([_msg(datetime.now(timezone.utc))])
        assert a.depth == 1
        assert not a.is_active

    def test_two_messages_recent_not_yet_active(self):
        # Seuil est ≥3 — 2 messages ne suffisent pas.
        now = datetime.now(timezone.utc)
        history = [
            _msg(now - timedelta(minutes=30)),
            _msg(now),
        ]
        a = analyze(history)
        assert a.depth == 2
        assert not a.is_active

    def test_three_messages_within_window_is_active(self):
        now = datetime.now(timezone.utc)
        history = [
            _msg(now - timedelta(minutes=60)),
            _msg(now - timedelta(minutes=30)),
            _msg(now),
        ]
        a = analyze(history)
        assert a.depth == 3
        assert a.last_gap_minutes is not None
        assert a.last_gap_minutes <= 60
        assert a.is_active

    def test_three_messages_with_long_gap_not_active(self):
        now = datetime.now(timezone.utc)
        history = [
            _msg(now - timedelta(days=2)),
            _msg(now - timedelta(days=1)),
            _msg(now),  # Gap 24h >> 120min
        ]
        a = analyze(history)
        assert a.depth == 3
        assert a.last_gap_minutes is not None
        assert a.last_gap_minutes > ACTIVE_THREAD_MAX_GAP_MINUTES
        assert not a.is_active

    def test_missing_dates_fallback(self):
        history = [_msg(None), _msg(None), _msg(None)]
        a = analyze(history)
        assert a.depth == 3
        assert a.last_gap_minutes is None
        assert not a.is_active

    def test_invalid_date_strings_ignored(self):
        history = [_msg("not-a-date"), _msg("also-garbage")]
        a = analyze(history)
        assert a.last_gap_minutes is None
        assert not a.is_active

    def test_dates_sorted_regardless_of_input_order(self):
        now = datetime.now(timezone.utc)
        history = [
            _msg(now),
            _msg(now - timedelta(minutes=45)),
            _msg(now - timedelta(minutes=15)),
        ]
        a = analyze(history)
        # gap = 15min entre now-15 et now.
        assert a.last_gap_minutes is not None
        assert 14 < a.last_gap_minutes < 16

    def test_threshold_constants_are_consistent(self):
        assert ACTIVE_THREAD_MIN_MESSAGES >= 2
        assert ACTIVE_THREAD_MAX_GAP_MINUTES > 0


class TestPromptBlock:
    def test_empty_history_produces_no_block(self):
        assert build_thread_activity_block(None) == ""

    def test_single_message_produces_no_block(self):
        # Avec moins de 2 messages, inutile de polluer le prompt.
        now = datetime.now(timezone.utc)
        assert build_thread_activity_block([_msg(now)]) == ""

    def test_active_thread_recommends_skip(self):
        now = datetime.now(timezone.utc)
        history = [_msg(now - timedelta(minutes=i * 10)) for i in range(4)]
        block = build_thread_activity_block(history)
        assert "profondeur=4" in block
        assert "omettre_salutation=true" in block

    def test_cold_thread_recommends_keep_greeting(self):
        now = datetime.now(timezone.utc)
        history = [
            _msg(now - timedelta(days=5)),
            _msg(now - timedelta(days=4)),
            _msg(now),
        ]
        block = build_thread_activity_block(history)
        assert "omettre_salutation=false" in block


class TestRecommendation:
    def test_recommend_mirrors_is_active(self):
        assert ThreadActivity(5, 10.0, True).recommend_skip_greeting()
        assert not ThreadActivity(5, 1000.0, False).recommend_skip_greeting()

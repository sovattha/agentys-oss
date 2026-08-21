from tests.load.load_rate_gate import RateGate
from tests.load.load_account_pool import AccountPool, account_id_for_index


def test_rate_gate_allows_unlimited_when_target_is_not_set(monkeypatch):
    monkeypatch.delenv("LOAD_TARGET_DRAFTS_PER_MINUTE", raising=False)

    gate = RateGate()

    assert gate.allow() is True
    assert gate.allow() is True


def test_rate_gate_throttles_when_burst_is_exhausted(monkeypatch):
    monkeypatch.setenv("LOAD_TARGET_DRAFTS_PER_MINUTE", "60")
    monkeypatch.setenv("LOAD_DRAFT_RATE_BURST", "1")

    gate = RateGate()

    assert gate.allow() is True
    assert gate.allow() is False


def test_account_pool_uses_round_robin_ids():
    assert [account_id_for_index(i, pool_size=3, start=10) for i in range(5)] == [
        "10",
        "11",
        "12",
        "10",
        "11",
    ]


def test_account_pool_returns_none_when_disabled():
    pool = AccountPool(pool_size=0)

    assert pool.next_account_id() is None

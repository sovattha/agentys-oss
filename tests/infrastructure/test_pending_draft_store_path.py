from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore


def test_pending_draft_store_honors_agentys_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path))

    store = InMemoryPendingDraftStore()

    assert store._persist_path == str(tmp_path / "pending_drafts.json")

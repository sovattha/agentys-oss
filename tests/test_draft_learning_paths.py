from app import draft_learning


def test_draft_learning_store_honors_agentys_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path))

    store = draft_learning.DraftLearningStore()

    assert store._path == str(tmp_path / "draft_corrections.json")


def test_account_draft_learning_path_honors_agentys_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path))

    assert draft_learning._path_for_account(42) == str(
        tmp_path / "draft_corrections" / "42.json"
    )

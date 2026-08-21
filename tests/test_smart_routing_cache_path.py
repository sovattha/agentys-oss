from app import smart_routing


def test_draft_cache_honors_agentys_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AGENTYS_DRAFT_CACHE_PATH", raising=False)
    monkeypatch.setattr(smart_routing, "_CACHE_FILE", None)

    assert smart_routing._get_cache_path() == tmp_path / "draft_cache.json"


def test_draft_cache_honors_explicit_path(tmp_path, monkeypatch):
    explicit = tmp_path / "nested" / "draft-cache.json"
    monkeypatch.setenv("AGENTYS_DRAFT_CACHE_PATH", str(explicit))
    monkeypatch.setattr(smart_routing, "_CACHE_FILE", None)

    assert smart_routing._get_cache_path() == explicit
    assert explicit.parent.exists()

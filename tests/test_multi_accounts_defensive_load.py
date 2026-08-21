import json

from app.multi_accounts import AccountManager


def test_account_manager_heals_empty_accounts_file(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text("", encoding="utf-8")

    manager = AccountManager(filepath=path)

    assert manager.accounts == {}
    assert json.loads(path.read_text(encoding="utf-8"))["accounts"] == []

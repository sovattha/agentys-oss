from __future__ import annotations

import json
from pathlib import Path

from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus
from app.draft_correction import CorrectionPattern, DraftCorrection, DraftCorrectionManager
from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore
from app.services.privacy_retention import redact_application_logs


def test_pending_drafts_delete_by_account_removes_only_target(tmp_path):
    store = InMemoryPendingDraftStore(persist_path=str(tmp_path / "pending.json"))
    store.add(PendingDraft(
        id="d1",
        email_id="e1",
        email_sender="sender@example.com",
        email_subject="Subject",
        draft_subject="Re: Subject",
        draft_body="Draft one",
        status=PendingDraftStatus.PENDING,
        account_id="1",
    ))
    store.add(PendingDraft(
        id="d2",
        email_id="e2",
        email_sender="sender@example.com",
        email_subject="Subject",
        draft_subject="Re: Subject",
        draft_body="Draft two",
        status=PendingDraftStatus.PENDING,
        account_id="2",
    ))

    assert store.delete_by_account(1) == 1

    remaining = store.get_all()
    assert [draft.id for draft in remaining] == ["d2"]


def test_draft_corrections_delete_by_account_filters_contexts(tmp_path):
    manager = DraftCorrectionManager(data_dir=tmp_path)
    manager.corrections = [
        DraftCorrection(
            id="c1",
            original_text="",
            corrected_text="",
            correction_type="tone",
            context={"account_id": 1},
        ),
        DraftCorrection(
            id="c2",
            original_text="",
            corrected_text="",
            correction_type="tone",
            context={"account_id": 2},
        ),
    ]
    manager.patterns = [
        CorrectionPattern(
            id="p1",
            pattern_type="tone_adjustment",
            original_pattern="formal",
            replacement="friendly",
            contexts=[
                json.dumps({"account_id": 1}),
                json.dumps({"account_id": 2}),
            ],
        )
    ]

    deleted = manager.delete_by_account(1)

    assert deleted["corrections"] == 1
    assert deleted["pattern_contexts"] == 1
    assert [correction.id for correction in manager.corrections] == ["c2"]
    assert manager.patterns[0].contexts == [json.dumps({"account_id": 2})]


def test_draft_learning_store_delete_removes_account_file(tmp_path, monkeypatch):
    from app import draft_learning

    # _path_for_account() derives the per-account file from the _default_path()
    # FUNCTION, not the _DEFAULT_PATH module constant — monkeypatch the function
    # so this test stays isolated under tmp_path instead of the real ~/.agentys.
    monkeypatch.setattr(
        draft_learning,
        "_default_path",
        lambda: str(tmp_path / "draft_corrections.json"),
    )
    draft_learning._stores.clear()
    path = Path(draft_learning._path_for_account(42))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"corrections": []}', encoding="utf-8")

    assert draft_learning.delete_draft_learning_store(42) is True
    assert not path.exists()


def test_redact_application_logs_rewrites_email_content(tmp_path):
    raw_body = "Bonjour Alice, le contrat secret ACME est prêt pour demain"
    log_file = tmp_path / "agentys.log"
    log_file.write_text(f'Provider payload: {{"body_text": "{raw_body}"}}\n', encoding="utf-8")

    assert redact_application_logs(logs_dir=tmp_path) == 1

    redacted = log_file.read_text(encoding="utf-8")
    assert raw_body not in redacted
    assert "[EMAIL_CONTENT_REDACTED]" in redacted

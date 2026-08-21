from __future__ import annotations


class _NoProfileContainer:
    def get_writing_style_profile(self, account_id=1):
        return None


def test_route_streaming_queues_batch_for_non_interactive_off_hours(monkeypatch):
    from app.smart_routing import SmartRouter

    monkeypatch.setattr(
        "app.infrastructure.container.get_container",
        lambda: _NoProfileContainer(),
    )
    monkeypatch.setattr("app.api.websocket.emit_draft_stage", lambda *a, **kw: None)
    monkeypatch.setattr("app.smart_routing.should_use_batch", lambda tier, force=False: not force)
    monkeypatch.setattr(SmartRouter, "_generate_simple", lambda self, *a, **kw: "")

    captured: dict = {}

    def fake_enqueue_for_batch(**kwargs):
        captured.update(kwargs)
        return "batch-item-12345678"

    monkeypatch.setattr("app.smart_routing.enqueue_for_batch", fake_enqueue_for_batch)

    body = (
        "Bonjour,\n\n"
        "Nous devons répondre à plusieurs points : le planning, le budget, "
        "les risques de migration et la prochaine étape avec l'équipe juridique. "
        "Peux-tu me faire une réponse structurée et professionnelle ?\n\n"
        "Merci."
    )

    result = SmartRouter().route_streaming(
        email_id="email-batch-1",
        email_content=body,
        sender="client@example.com",
        subject="Questions projet",
        body=body,
        account_id=42,
        force=False,
    )

    assert result.status == "BATCH_QUEUED"
    assert result.draft == ""
    assert captured["email_id"] == "email-batch-1"
    assert captured["account_id"] == 42
    assert "planning" in captured["user_prompt"]


def test_enqueue_for_batch_persists_account_id(monkeypatch, tmp_path):
    from app.batch_queue import BatchQueue
    from app.smart_routing import RoutingTier, enqueue_for_batch

    queue = BatchQueue(str(tmp_path / "batch_queue.db"))
    monkeypatch.setattr("app.batch_queue.get_batch_queue", lambda: queue)

    item_id = enqueue_for_batch(
        email_id="email-1",
        tier=RoutingTier.STANDARD,
        sender="sender@example.com",
        subject="Sujet",
        body="Corps",
        system_prompt="system",
        user_prompt="user",
        account_id=42,
    )

    row = queue.get_by_email_id("email-1", account_id="42")

    assert row is not None
    assert row["id"] == item_id
    assert row["account_id"] == "42"

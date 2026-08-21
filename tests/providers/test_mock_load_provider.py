from app.providers.mock_load_provider import LoadTestEmailProvider, provider_kind_override


def test_load_test_email_provider_returns_synthetic_email():
    provider = LoadTestEmailProvider()

    email = provider.get_message_by_id("load-email-1")

    assert provider.authenticate() is True
    assert email.id == "load-email-1"
    assert email.provider_source == "mock-load"
    assert "Pouvez-vous" in email.body


def test_load_test_email_provider_supports_drafts_and_quota_context():
    provider = LoadTestEmailProvider()

    with provider.limited_quota_wait(0):
        draft_id = provider.create_draft(
            to=["client@example.com"],
            subject="Re: Test",
            body="Bonjour",
            reply_to_id="load-email-1",
        )

    assert draft_id.startswith("mock-draft-")
    assert provider.send_draft(draft_id) is True


def test_load_test_email_provider_can_simulate_detail_quota_backoff(monkeypatch):
    from app.providers.mock_load_provider import LoadTestQuotaBackoffError

    LoadTestEmailProvider.reset_quota_state()
    monkeypatch.setenv("AGENTYS_MOCK_GMAIL_DETAIL_BACKOFF_EVERY", "1")
    monkeypatch.setenv("AGENTYS_MOCK_GMAIL_BACKOFF_SECONDS", "9")
    provider = LoadTestEmailProvider()

    try:
        provider.get_message_by_id("load-email-1")
    except LoadTestQuotaBackoffError as exc:
        assert exc.code == "GMAIL_QUOTA_BACKOFF"
        assert exc.retry_after == 9
    else:
        raise AssertionError("expected synthetic quota backoff")

    assert provider.low_priority_quota_retry_after_seconds() > 0
    LoadTestEmailProvider.reset_quota_state()


def test_load_test_email_provider_can_simulate_outlook_kind_and_list_backoff(monkeypatch):
    from app.providers.mock_load_provider import LoadTestQuotaBackoffError

    LoadTestEmailProvider.reset_quota_state()
    monkeypatch.setenv("AGENTYS_MOCK_EMAIL_PROVIDER_KIND", "outlook")
    monkeypatch.setenv("AGENTYS_MOCK_OUTLOOK_LIST_BACKOFF_EVERY", "1")
    monkeypatch.setenv("AGENTYS_MOCK_OUTLOOK_BACKOFF_SECONDS", "6")
    provider = LoadTestEmailProvider()

    assert provider.provider_name == "outlook"
    try:
        provider.get_messages(limit=1)
    except LoadTestQuotaBackoffError as exc:
        assert exc.retry_after == 6
        assert exc.provider == "outlook"
    else:
        raise AssertionError("expected synthetic Outlook quota backoff")
    finally:
        LoadTestEmailProvider.reset_quota_state()


def test_load_test_email_provider_kind_override_is_request_scoped(monkeypatch):
    monkeypatch.setenv("AGENTYS_MOCK_EMAIL_PROVIDER_KIND", "outlook")
    provider = LoadTestEmailProvider()

    assert provider.provider_name == "outlook"
    with provider_kind_override("gmail"):
        assert provider.provider_name == "gmail"
        assert provider.get_message_by_id("load-email-1").provider_source == "gmail"
    assert provider.provider_name == "outlook"


def test_load_test_email_provider_limited_quota_wait_fails_fast(monkeypatch):
    from app.providers.mock_load_provider import LoadTestQuotaBackoffError

    LoadTestEmailProvider.reset_quota_state()
    monkeypatch.setenv("AGENTYS_MOCK_GMAIL_SENT_BACKOFF_EVERY", "1")
    monkeypatch.setenv("AGENTYS_MOCK_GMAIL_BACKOFF_SECONDS", "8")
    provider = LoadTestEmailProvider()

    try:
        provider.get_sent_emails(limit=1)
    except LoadTestQuotaBackoffError:
        pass
    else:
        raise AssertionError("expected synthetic sent quota backoff")

    try:
        with provider.limited_quota_wait(1):
            pass
    except LoadTestQuotaBackoffError as exc:
        assert exc.retry_after >= 7
    else:
        raise AssertionError("expected limited quota wait to fail fast")
    finally:
        LoadTestEmailProvider.reset_quota_state()

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Outlook inline (cid:) image resolution — audit fix 2026-06-02.

Outlook/Graph ships inline images as separate inline attachments, not inline
MIME parts, so cid: references in the HTML body rendered as broken placeholders.
These tests cover the new fetch-and-resolve path and its cost gates.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.providers.outlook_adapter import OutlookAdapter


@pytest.fixture
def adapter():
    # account_id => OAuth web mode, skips the Azure env-var validation in __init__.
    a = OutlookAdapter(account_id="test-account", user_id="user@example.com")
    a._access_token = "fake-token"
    return a


def _graph_response(value):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"value": value}
    return resp


HTML_WITH_CID = '<p>hi</p><img src="cid:logo123" alt="logo">'


class TestGating:
    def test_no_cid_skips_fetch(self, adapter):
        with patch("app.providers.outlook_adapter._graph_request_with_retry") as m:
            out = adapter._resolve_outlook_inline_images(
                "msg1", "<p>no images here</p>", has_attachments=True
            )
        assert out == "<p>no images here</p>"
        m.assert_not_called()

    def test_no_attachments_skips_fetch(self, adapter):
        with patch("app.providers.outlook_adapter._graph_request_with_retry") as m:
            out = adapter._resolve_outlook_inline_images(
                "msg1", HTML_WITH_CID, has_attachments=False
            )
        assert out == HTML_WITH_CID
        m.assert_not_called()

    def test_empty_body_returns_as_is(self, adapter):
        with patch("app.providers.outlook_adapter._graph_request_with_retry") as m:
            assert adapter._resolve_outlook_inline_images("msg1", None, True) is None
        m.assert_not_called()


class TestResolution:
    def test_cid_replaced_with_data_uri(self, adapter):
        value = [{
            "id": "att1",
            "name": "logo.png",
            "contentType": "image/png",
            "contentId": "<logo123>",
            "contentBytes": "QUJD",  # base64 for "ABC"
            "isInline": True,
        }]
        with patch(
            "app.providers.outlook_adapter._graph_request_with_retry",
            return_value=_graph_response(value),
        ):
            out = adapter._resolve_outlook_inline_images("msg1", HTML_WITH_CID, True)
        assert 'src="data:image/png;base64,QUJD"' in out
        assert "cid:logo123" not in out

    def test_missing_inline_attachment_leaves_body(self, adapter):
        # cid: present but Graph returns no inline attachments -> body unchanged.
        with patch(
            "app.providers.outlook_adapter._graph_request_with_retry",
            return_value=_graph_response([]),
        ):
            out = adapter._resolve_outlook_inline_images("msg1", HTML_WITH_CID, True)
        assert out == HTML_WITH_CID

    def test_delta_dict_mapper_resolves_cid(self, adapter):
        value = [{
            "contentType": "image/gif",
            "contentId": "logo123",  # already without angle brackets
            "contentBytes": "R0lG",
            "isInline": True,
        }]
        raw = {
            "id": "msg-delta",
            "from": {"emailAddress": {"address": "a@x.com", "name": "A"}},
            "subject": "hi",
            "hasAttachments": True,
            "body": {"contentType": "html", "content": HTML_WITH_CID},
        }
        with patch(
            "app.providers.outlook_adapter._graph_request_with_retry",
            return_value=_graph_response(value),
        ):
            std = adapter._map_raw_dict_to_standard_email(raw)
        assert std.body_html is not None
        assert "data:image/gif;base64,R0lG" in std.body_html
        assert "cid:logo123" not in std.body_html

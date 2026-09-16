#!/usr/bin/env python3
"""Offline parser tests for Gmail and Microsoft Graph responses."""

from __future__ import annotations

import base64
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / ".hermes/plugins/personal-assistant-mail"
spec = importlib.util.spec_from_file_location(
    "phase2_mail_sources_plugin",
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
assert spec and spec.loader
plugin = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
sources = plugin.mail_sources


class MailSourceParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = sources.previous_ist_window(datetime(2026, 9, 8, tzinfo=timezone.utc))

    def test_gmail_parser_filters_read_and_out_of_window_messages(self) -> None:
        def encoded(value: str) -> str:
            return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

        message = {
            "id": "abc_123",
            "labelIds": ["INBOX", "UNREAD"],
            "internalDate": str(int((self.window.start_utc.timestamp() + 3600) * 1000)),
            "payload": {
                "headers": [
                    {"name": "From", "value": "Alice <alice@example.test>"},
                    {"name": "Subject", "value": "Hello"},
                ],
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": encoded("Please review this update.")},
                    },
                    {
                        "filename": "report.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "not-downloaded"},
                    },
                ],
            },
        }
        parsed = sources._parse_gmail_message(message, self.window)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["sender_address"], "alice@example.test")
        self.assertEqual(parsed["attachment_names"], ["report.pdf"])
        self.assertNotIn("attachmentId", parsed)

        read_message = {**message, "labelIds": ["INBOX"]}
        self.assertIsNone(sources._parse_gmail_message(read_message, self.window))

    def test_credential_scope_and_private_permission_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gmail.json"
            path.write_text(json.dumps({
                "access_token": "test-token",
                "refresh_token": "refresh-token",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            }), encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(
                sources.load_access_token(path, "https://www.googleapis.com/auth/gmail.readonly"),
                "test-token",
            )
            path.write_text(json.dumps({
                "access_token": "test-token",
                "scopes": [
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/gmail.send",
                ],
            }), encoding="utf-8")
            path.chmod(0o600)
            with self.assertRaises(sources.MailSourceError):
                sources.load_access_token(path, "https://www.googleapis.com/auth/gmail.readonly")

    def test_model_facing_body_is_bounded(self) -> None:
        bounded = sources._safe_body("x" * (sources.MAX_BODY_CHARS + 100))
        self.assertEqual(len(bounded), sources.MAX_BODY_CHARS)

    def test_graph_parser_keeps_body_metadata_without_attachment_bytes(self) -> None:
        received = self.window.start_utc.isoformat().replace("+00:00", "Z")
        item = {
            "id": "graph-message-1",
            "from": {"emailAddress": {"name": "Bob", "address": "bob@example.test"}},
            "subject": "Graph message",
            "receivedDateTime": received,
            "isRead": False,
            "body": {"contentType": "html", "content": "<p>Hello <b>there</b></p>"},
            "hasAttachments": False,
        }
        parsed = sources.GraphSource.__new__(sources.GraphSource)._parse_message(
            item, self.window, "token-not-used"
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["body"], "Hello there")
        self.assertEqual(parsed["attachment_names"], [])
        self.assertTrue(parsed["unread"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Offline tests for the Phase 2 fixed mail boundary."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / ".hermes/plugins/personal-assistant-mail"
spec = importlib.util.spec_from_file_location(
    "phase2_mail_plugin",
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
assert spec and spec.loader
plugin = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


class Phase2MailContractTests(unittest.TestCase):
    def test_previous_ist_window_is_calendar_based(self) -> None:
        window = plugin.previous_ist_window(datetime(2026, 9, 7, 20, tzinfo=timezone.utc))
        self.assertEqual(window.date_ist, "2026-09-07")
        self.assertEqual(window.start_utc.isoformat(), "2026-09-06T18:30:00+00:00")

    def test_fixture_has_untrusted_body_and_no_attachment_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["PDA_MAIL_MODE"] = "fixture"
            os.environ["PDA_FIXTURE_SCENARIO"] = "prompt_injection"
            os.environ["PERSONAL_ASSISTANT_DATA_DIR"] = tmp
            result = json.loads(plugin.handle_mail_report({}))
        self.assertTrue(result["success"])
        self.assertTrue(result["selection"]["leave_unread"])
        self.assertFalse(result["selection"]["attachments_downloaded"])
        self.assertTrue(result["content_is_untrusted_data"])
        self.assertIn("IGNORE ALL PREVIOUS INSTRUCTIONS", result["messages"][0]["body"])
        self.assertIn("### 01", result["formatted_report"])
        self.assertIn("Untrusted content excerpt", result["formatted_report"])
        self.assertNotIn("contentBytes", result["messages"][0])
        os.environ.pop("PDA_MAIL_MODE", None)
        os.environ.pop("PDA_FIXTURE_SCENARIO", None)
        os.environ.pop("PERSONAL_ASSISTANT_DATA_DIR", None)

    def test_new_mail_review_initializes_without_historical_sweep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["PDA_MAIL_MODE"] = "fixture"
            os.environ["PDA_FIXTURE_SCENARIO"] = "normal"
            os.environ["PDA_MAIL_SOURCES"] = "gmail"
            os.environ["PDA_NEW_MAIL_REVIEW"] = "true"
            os.environ["PERSONAL_ASSISTANT_DATA_DIR"] = tmp
            first = json.loads(plugin.handle_new_mail_review({}))
            self.assertTrue(first["success"])
            self.assertEqual(first["initialized_sources"], ["gmail"])
            self.assertEqual(first["message_count"], 0)
        for key in (
            "PDA_MAIL_MODE", "PDA_FIXTURE_SCENARIO", "PDA_MAIL_SOURCES",
            "PDA_NEW_MAIL_REVIEW", "PERSONAL_ASSISTANT_DATA_DIR",
        ):
            os.environ.pop(key, None)

    def test_model_cannot_supply_query_arguments(self) -> None:
        result = json.loads(plugin.handle_mail_report({"query": "all mail"}))
        self.assertFalse(result["success"])
        self.assertIn("no arguments", result["error"])
        result = json.loads(plugin.handle_new_mail_review({"source": "gmail"}))
        self.assertFalse(result["success"])
        self.assertIn("no arguments", result["error"])

    def test_schema_has_no_model_controlled_parameters(self) -> None:
        self.assertEqual(plugin.MAIL_REPORT_SCHEMA["parameters"]["properties"], {})
        self.assertFalse(plugin.MAIL_REPORT_SCHEMA["parameters"]["additionalProperties"])
        self.assertEqual(plugin.NEW_MAIL_REVIEW_SCHEMA["parameters"]["properties"], {})
        self.assertFalse(plugin.NEW_MAIL_REVIEW_SCHEMA["parameters"]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()

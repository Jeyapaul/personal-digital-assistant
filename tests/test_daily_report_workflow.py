"""Tests for the model-mode daily mail workflow contract."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / ".hermes/plugins/personal-assistant-mail"
spec = importlib.util.spec_from_file_location(
    "personal_assistant_mail_workflow_test",
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
assert spec and spec.loader
plugin = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


class ModelModeWorkflowTests(unittest.TestCase):
    def test_model_payload_is_bounded_and_id_free(self) -> None:
        message = {
            "id": "provider-secret-id",
            "source": "gmail",
            "sender": "sender@example.test",
            "subject": "Update",
            "received_at_ist": "2026-09-17 10:00:00",
            "unread": True,
            "body": "x" * 1000,
            "attachment_names": ["update.pdf"],
        }
        payload = plugin._model_messages([message])[0]
        self.assertNotIn("id", payload)
        self.assertEqual(len(payload["body"]), plugin.MODEL_BODY_CHARS)
        self.assertEqual(payload["attachment_names"], ["update.pdf"])

    def test_every_rendered_message_has_summary_and_action(self) -> None:
        messages = [
            {
                "source": "gmail",
                "received_at_ist": "2026-09-17 10:00:00",
                "unread": True,
                "sender": "sender@example.test",
                "subject": "Update",
                "body": "Please review the update.",
                "model_summary": "An update is ready for review.",
                "suggested_action": "Review manually; no action was taken.",
                "attachment_names": [],
            }
        ]
        rendered = plugin.format_report(messages)
        self.assertIn("An update is ready for review.", rendered)
        self.assertIn("**Suggested:** Review manually", rendered)

    def test_mail_report_rejects_model_arguments(self) -> None:
        result = json.loads(plugin.handle_mail_report({"date": "2026-09-17"}))
        self.assertFalse(result["success"])
        self.assertIn("accepts no arguments", result["error"])

    def test_cron_installer_uses_deterministic_delivery_with_local_model_summaries(self) -> None:
        installer = (ROOT / "scripts/install-report-cron.py").read_text(encoding="utf-8")
        self.assertIn('"no_agent": False', installer)
        self.assertIn('"enabled_toolsets": ["personal-assistant-mail"]', installer)
        self.assertIn("Script Output", installer)
        self.assertIn("pre-run script", installer)


if __name__ == "__main__":
    unittest.main()

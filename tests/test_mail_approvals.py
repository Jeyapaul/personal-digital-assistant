#!/usr/bin/env python3
"""Approval and mutation-boundary tests for new-mail organization."""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / ".hermes/plugins/personal-assistant-mail"
spec = importlib.util.spec_from_file_location(
    "mail_approval_plugin", PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)]
)
assert spec and spec.loader
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


class MailApprovalTests(unittest.TestCase):
    def test_approval_requires_matching_reply_and_records_dry_run_decision(self) -> None:
        batch_id = "new-20260921T100000Z-abcdef"
        recommendation_id = "rec-0123456789abcdef"
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            connection = plugin.open_state(data_dir)
            plugin.mail_management._ensure_tables(connection)
            expires = ""
            connection.execute(
                "INSERT INTO management_batches(batch_id,created_at_utc,expires_at_utc,status) VALUES(?,?,?,'proposed')",
                (batch_id, datetime.now(timezone.utc).isoformat(), expires),
            )
            connection.execute(
                "INSERT INTO management_recommendations "
                "(recommendation_id,batch_id,source,message_id,sender,subject,action,category,reason,confidence,target,status,created_at_utc) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (recommendation_id, batch_id, "gmail", "message-1", "sender@example.test",
                 "Newsletter", "archive", "Newsletter", "Periodic newsletter; archive reduces inbox noise.",
                 0.9, "", "pending", datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()
            connection.close()
            plugin.mail_management.record_approval_request(data_dir, batch_id, "dm-1", "approval-1", expires)
            os.environ["DISCORD_ALLOWED_USERS"] = "42"
            os.environ["PDA_MAIL_MUTATION_ENABLED"] = "false"
            rejected = plugin.mail_management.process_discord_approval(
                data_dir, f"APPROVE {recommendation_id}", "42", "dm-1", "reply-1", "wrong-message"
            )
            self.assertFalse(rejected["success"])
            accepted = plugin.mail_management.process_discord_approval(
                data_dir, f"APPROVE {recommendation_id}", "42", "dm-1", "reply-2", "approval-1"
            )
            self.assertTrue(accepted["success"])
            self.assertEqual(accepted["results"][0]["status"], "approved_dry_run")
            check = sqlite3.connect(data_dir / "state.db")
            self.assertEqual(check.execute(
                "SELECT status FROM management_recommendations WHERE recommendation_id = ?", (recommendation_id,)
            ).fetchone()[0], "approved_dry_run")
            self.assertEqual(check.execute("SELECT decision FROM management_approval_audit").fetchone()[0], "approved_dry_run")
            check.close()
        os.environ.pop("DISCORD_ALLOWED_USERS", None)
        os.environ.pop("PDA_MAIL_MUTATION_ENABLED", None)

    def test_unsubscribe_parser_keeps_only_https_and_mailto_targets(self) -> None:
        targets = plugin.mail_sources._unsubscribe_targets([
            {"name": "List-Unsubscribe", "value": "<https://example.test/u?id=1>, <mailto:leave@example.test>"},
            {"name": "List-Unsubscribe-Post", "value": "List-Unsubscribe=One-Click"},
        ])
        self.assertEqual(targets["https"], ["https://example.test/u?id=1"])
        self.assertEqual(targets["mailto"], ["mailto:leave@example.test"])
        self.assertTrue(targets["one_click"])


if __name__ == "__main__":
    unittest.main()

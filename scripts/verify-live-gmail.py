#!/usr/bin/env python3
"""Run one bounded live mail collection without invoking the language model.

The command prints counts and policy checks only; it never prints message
bodies or credential contents.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get(
    "PERSONAL_ASSISTANT_DATA_DIR",
    str(Path.home() / ".hermes/personal-assistant-data"),
))
PLUGIN_DIR = ROOT / ".hermes/plugins/personal-assistant-mail"

os.environ["PERSONAL_ASSISTANT_DATA_DIR"] = str(DATA_DIR)
os.environ["PDA_MAIL_MODE"] = "real"
os.environ.setdefault("PDA_MAIL_SOURCES", "gmail")

spec = importlib.util.spec_from_file_location(
    "live_gmail_plugin",
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
if not spec or not spec.loader:
    raise SystemExit("could not load mail plugin")
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)

result = json.loads(plugin.handle_mail_report({}))
messages = result.get("messages", [])
counts = Counter(str(item.get("source", "unknown")) for item in messages)
summary = {
    "success": result.get("success"),
    "operation": result.get("operation"),
    "runtime_mode": result.get("runtime_mode"),
    "date_ist": result.get("selection", {}).get("date_ist"),
    "message_count": len(messages),
    "source_counts": dict(counts),
    "source_errors": result.get("source_errors", {}),
    "all_unread": all(item.get("unread") is True for item in messages),
    "leave_unread": result.get("selection", {}).get("leave_unread") is True,
    "attachments_downloaded": result.get("selection", {}).get("attachments_downloaded"),
    "attachment_name_count": sum(len(item.get("attachment_names", [])) for item in messages),
}
print(json.dumps(summary, indent=2, sort_keys=True))
if summary["source_errors"] or not summary["success"]:
    raise SystemExit(1)

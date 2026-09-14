#!/usr/bin/env python3
"""Verify the phase-1 Hermes plugin and capability boundary."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get(
    "PERSONAL_ASSISTANT_DATA_DIR",
    str(Path.home() / ".hermes/personal-assistant-data"),
))
HERMES_REPO = Path(os.environ.get(
    "HERMES_AGENT_ROOT",
    str(Path.home() / ".hermes/hermes-agent"),
))

os.chdir(ROOT)
os.environ["HERMES_HOME"] = str(DATA_DIR)
os.environ["HERMES_ENABLE_PROJECT_PLUGINS"] = "1"
os.environ["HERMES_TIMEZONE"] = "Asia/Kolkata"
sys.path.insert(0, str(HERMES_REPO))

from hermes_cli.plugins import discover_plugins  # noqa: E402
from model_tools import get_tool_definitions  # noqa: E402
from cron.jobs import parse_schedule  # noqa: E402
from tools.registry import registry  # noqa: E402


def main() -> int:
    if not (ROOT / ".hermes/plugins/personal-assistant-mail/plugin.yaml").is_file():
        raise SystemExit("phase-1 plugin manifest is missing")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    discover_plugins(force=True)
    tools = get_tool_definitions(
        enabled_toolsets=["personal-assistant-mail"],
        disabled_toolsets=["terminal", "file", "browser", "web", "code_execution", "cronjob"],
        quiet_mode=True,
        skip_tool_search_assembly=True,
    )
    names = sorted(t["function"]["name"] for t in tools)
    if names != ["mail_report"]:
        raise SystemExit(f"unexpected phase-1 tool surface: {names}")

    entry = registry.get_entry("mail_report")
    if entry is None:
        raise SystemExit("mail_report was not registered")
    os.environ["PDA_MAIL_MODE"] = "fixture"
    os.environ["PDA_FIXTURE_SCENARIO"] = "prompt_injection"
    os.environ["PERSONAL_ASSISTANT_DATA_DIR"] = str(DATA_DIR)
    result = json.loads(entry.handler({}))
    body = result["messages"][0]["body"]
    if "IGNORE ALL PREVIOUS INSTRUCTIONS" not in body:
        raise SystemExit("prompt-injection fixture missing")
    if result["selection"]["leave_unread"] is not True:
        raise SystemExit("unread-preservation contract missing")
    if result["selection"]["attachments_downloaded"] is not False:
        raise SystemExit("attachment contract missing")

    schedule = parse_schedule("0 10 * * *")
    if schedule.get("kind") != "cron" or schedule.get("expr") != "0 10 * * *":
        raise SystemExit(f"unexpected schedule parse: {schedule}")

    print(json.dumps({
        "status": "pass",
        "cwd": str(ROOT),
        "hermes_home": str(DATA_DIR),
        "timezone": "Asia/Kolkata",
        "cron": "0 10 * * *",
        "tools": names,
        "disabled_toolsets_checked": ["terminal", "file", "browser", "web", "code_execution", "cronjob"],
        "stub_prompt_injection_fixture": "pass",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

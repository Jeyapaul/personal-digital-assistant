#!/usr/bin/env python3
"""Deterministic bridge for replies to recorded mail-approval Discord DMs."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path("/opt/personal-assistant") if Path("/opt/personal-assistant").is_dir() else Path(__file__).resolve().parents[1]
PLUGIN = ROOT / ".hermes/plugins/personal-assistant-mail"


def main() -> int:
    if len(sys.argv) != 6:
        print(json.dumps({"success": False, "error": "invalid approval bridge arguments"}))
        return 2
    spec = importlib.util.spec_from_file_location(
        "personal_assistant_mail_approval_bridge",
        PLUGIN / "__init__.py",
        submodule_search_locations=[str(PLUGIN)],
    )
    if not spec or not spec.loader:
        print(json.dumps({"success": False, "error": "mail plugin unavailable"}))
        return 2
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    result = module.handle_discord_approval(*sys.argv[1:])
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate narrow OAuth credential shape and permissions without printing secrets."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get(
    "PERSONAL_ASSISTANT_DATA_DIR",
    str(Path.home() / ".hermes/personal-assistant-data"),
))
FILES = {
    "gmail": (DATA_DIR / "credentials/gmail.json", "https://www.googleapis.com/auth/gmail.readonly", {"https://www.googleapis.com/auth/gmail.readonly"}),
    "microsoft": (DATA_DIR / "credentials/microsoft.json", "Mail.Read", {"Mail.Read", "offline_access", "openid", "profile"}),
}


def scopes(payload: dict) -> set[str]:
    raw = payload.get("scopes") or payload.get("scope") or []
    if isinstance(raw, str):
        return set(raw.split())
    return {str(value) for value in raw} if isinstance(raw, list) else set()


def check(name: str, path: Path, required_scope: str, allowed_scopes: set[str]) -> dict:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return {"source": name, "ok": False, "error": "missing or unreadable"}
    if mode & 0o077:
        return {"source": name, "ok": False, "error": "permissions must exclude group/other"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"source": name, "ok": False, "error": "invalid JSON"}
    if not isinstance(payload, dict):
        return {"source": name, "ok": False, "error": "credential is not an object"}
    granted = scopes(payload)
    if required_scope not in granted:
        return {"source": name, "ok": False, "error": f"missing required scope: {required_scope}"}
    if not granted <= allowed_scopes:
        return {"source": name, "ok": False, "error": "credential has broader scopes than allowed"}
    if not (payload.get("access_token") or payload.get("token")):
        return {"source": name, "ok": False, "error": "access token is missing"}
    if not payload.get("refresh_token"):
        return {"source": name, "ok": False, "error": "refresh token is missing"}
    return {"source": name, "ok": True, "mode": oct(mode), "required_scope": required_scope}


parser = argparse.ArgumentParser()
parser.add_argument("--source", choices=["gmail", "microsoft", "all"], default="gmail")
args = parser.parse_args()
selected = FILES if args.source == "all" else {args.source: FILES[args.source]}
results = [check(name, path, scope, allowed) for name, (path, scope, allowed) in selected.items()]
print(json.dumps(results, indent=2))
sys.exit(0 if all(item["ok"] for item in results) else 1)

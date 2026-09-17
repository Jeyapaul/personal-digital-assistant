#!/usr/bin/env python3
"""Refresh OAuth credentials and alert the fixed Discord DM on failure.

This is an operator-side health check, not an agent tool. It never reads mail,
prints tokens, or sends through a model-selected recipient. Access-token
refresh is attempted at most hourly per provider; failures are retried every
five minutes until resolved.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import ssl
import stat
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get(
    "PERSONAL_ASSISTANT_DATA_DIR",
    str(Path.home() / ".hermes/personal-assistant-data"),
))
CREDENTIAL_DIR = DATA_DIR / "credentials"
STATE_PATH = DATA_DIR / "lifecycle/credential-health.json"
CHECK_INTERVAL_SECONDS = 3600
RETRY_INTERVAL_SECONDS = 300
ALERT_REPEAT_SECONDS = 21600

SOURCES = {
    "gmail": {
        "label": "Google Gmail",
        "path": CREDENTIAL_DIR / "gmail.json",
        "scope": "https://www.googleapis.com/auth/gmail.readonly",
        "command": "python3 scripts/google-gmail-oauth.py --auth-url",
    },
    "microsoft": {
        "label": "Microsoft Hotmail",
        "path": CREDENTIAL_DIR / "microsoft.json",
        "scope": "Mail.Read",
        "command": "python3 scripts/microsoft-mail-oauth.py --auth --client-id YOUR_APPLICATION_CLIENT_ID --tenant consumers",
    },
}


def _now() -> int:
    return int(time.time())


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _enabled_sources() -> list[str]:
    requested = {
        item.strip().lower()
        for item in os.environ.get("PDA_MAIL_SOURCES", "gmail").split(",")
        if item.strip()
    }
    return [name for name in SOURCES if name in requested]


def _load_state() -> dict[str, Any]:
    try:
        mode = stat.S_IMODE(STATE_PATH.stat().st_mode)
        if mode & 0o077:
            return {}
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_name(f".{STATE_PATH.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, STATE_PATH)
    STATE_PATH.chmod(0o600)


def _load_mail_sources_module() -> Any:
    plugin_path = ROOT / ".hermes/plugins/personal-assistant-mail/mail_sources.py"
    spec = importlib.util.spec_from_file_location("pda_mail_sources", plugin_path)
    if not spec or not spec.loader:
        raise RuntimeError("mail source module unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _discord_context() -> tuple[str, str]:
    token_path = CREDENTIAL_DIR / "discord-bot-token"
    runtime_path = CREDENTIAL_DIR / "discord-runtime.json"
    token_mode = stat.S_IMODE(token_path.stat().st_mode)
    if token_mode & 0o077:
        raise RuntimeError("Discord token permissions are too broad")
    token = token_path.read_text(encoding="utf-8").strip()
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    channel_id = str(runtime.get("dm_channel_id", ""))
    if runtime.get("dm_only") is not True or not channel_id.isdigit() or not token:
        raise RuntimeError("DM-only Discord runtime is not configured")
    return token, channel_id


def _send_discord(content: str) -> None:
    token, channel_id = _discord_context()
    request = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=json.dumps({"content": content}).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "HermesPersonalAssistant/0.1 (credential-health)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
            if response.status not in {200, 201, 204}:
                raise RuntimeError("Discord rejected the alert")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Discord alert delivery failed") from exc


def _should_check(record: dict[str, Any], now: int) -> bool:
    last_check = int(record.get("last_check", 0) or 0)
    interval = RETRY_INTERVAL_SECONDS if record.get("active") else CHECK_INTERVAL_SECONDS
    return now - last_check >= interval


def main() -> int:
    module = _load_mail_sources_module()
    state = _load_state()
    now = _now()
    changed = False
    failures = 0

    for name in _enabled_sources():
        definition = SOURCES[name]
        record = state.get(name, {}) if isinstance(state.get(name), dict) else {}
        if not _should_check(record, now):
            if record.get("active"):
                failures += 1
            continue

        try:
            module.load_access_token(
                definition["path"],
                definition["scope"],
                force_refresh=True,
            )
        except Exception as exc:  # safe alert; never expose exception text
            failures += 1
            fingerprint = hashlib.sha256(
                f"{name}:{type(exc).__name__}".encode("utf-8")
            ).hexdigest()[:16]
            should_alert = (
                not record.get("active")
                or record.get("fingerprint") != fingerprint
                or now - int(record.get("alerted_at", 0) or 0) >= ALERT_REPEAT_SECONDS
            )
            record = {
                "active": True,
                "fingerprint": fingerprint,
                "last_check": now,
                "alerted_at": int(record.get("alerted_at", 0) or 0),
            }
            if should_alert:
                message = (
                    f"⚠️ Personal Assistant OAuth alert\n"
                    f"{definition['label']} could not refresh its OAuth credential.\n"
                    f"Manual authorization is required before this source can be used.\n\n"
                    f"Run locally: {definition['command']}"
                )
                try:
                    _send_discord(message)
                    record["alerted_at"] = now
                    print(f"{name}: refresh failed; Discord alert sent")
                except Exception:
                    print(f"{name}: refresh failed; Discord alert unavailable")
            state[name] = record
            changed = True
            continue

        if record.get("active"):
            try:
                _send_discord(
                    f"✅ Personal Assistant OAuth recovery\n"
                    f"{definition['label']} refreshed successfully again."
                )
                print(f"{name}: refresh recovered; Discord alert sent")
            except Exception:
                print(f"{name}: refresh recovered; Discord alert unavailable")
        state[name] = {
            "active": False,
            "fingerprint": "",
            "last_check": now,
            "alerted_at": 0,
        }
        changed = True

    if changed:
        _write_state(state)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

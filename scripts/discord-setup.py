#!/usr/bin/env python3
"""Configure and validate one-user Discord DM delivery.

The bot token is read interactively or from a private file and is never
printed. The script creates/resolves a DM channel for exactly one user and
writes the profile-scoped Hermes .env plus non-secret runtime metadata.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import ssl
import stat
import urllib.error
import urllib.request
from pathlib import Path

DATA_DIR = Path(os.environ.get(
    "PERSONAL_ASSISTANT_DATA_DIR",
    str(Path.home() / ".hermes/personal-assistant-data"),
))
CREDENTIAL_DIR = DATA_DIR / "credentials"
TOKEN_PATH = CREDENTIAL_DIR / "discord-bot-token"
ENV_PATH = DATA_DIR / ".env"
RUNTIME_PATH = CREDENTIAL_DIR / "discord-runtime.json"
DISCORD_API = "https://discord.com/api/v10"
ID_RE = re.compile(r"^[0-9]{15,22}$")


def _ssl_context() -> ssl.SSLContext:
    cafile = os.environ.get("SSL_CERT_FILE")
    if not cafile:
        try:
            import certifi
            cafile = certifi.where()
        except ImportError:
            candidates = sorted(Path.home().glob(".hermes/hermes-agent/venv/lib/python*/site-packages/certifi/cacert.pem"))
            if candidates:
                cafile = str(candidates[-1])
    return ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()


def _private_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(0o600)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def _read_token(path: Path) -> str:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise SystemExit(f"Discord token file is unavailable: {path}") from exc
    if mode & 0o077:
        raise SystemExit("Discord token file permissions must be 0600")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("Discord token file is empty")
    return token


def _request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = None
    headers = {
        "Authorization": f"Bot {token}",
        "Accept": "application/json",
        "User-Agent": "HermesPersonalAssistant/0.1 (local setup)",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(DISCORD_API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20, context=_ssl_context()) as response:
            payload = json.loads(response.read(256 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            error_payload = json.loads(exc.read(64 * 1024).decode("utf-8"))
            if isinstance(error_payload, dict):
                detail = str(error_payload.get("message") or error_payload.get("code") or "")
        except (ValueError, UnicodeError, OSError):
            pass
        suffix = f" ({detail})" if detail else ""
        raise SystemExit(f"Discord API request failed for {path}: HTTP {exc.code}{suffix}") from exc
    except urllib.error.URLError as exc:
        reason = type(exc.reason).__name__ if exc.reason else "network error"
        raise SystemExit(f"Discord API request failed for {path} before response ({reason})") from exc
    except (TimeoutError, ValueError) as exc:
        raise SystemExit(f"Discord API request failed for {path} before response") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Discord API returned an invalid response")
    return payload


def setup(user_id: str, token_file: Path, replace_token: bool = False) -> None:
    if not ID_RE.fullmatch(user_id):
        raise SystemExit("Discord user ID must be a numeric snowflake")
    if token_file.exists() and not replace_token:
        token = _read_token(token_file)
    else:
        token = getpass.getpass("Discord bot token (input hidden): ").strip()
        if not token:
            raise SystemExit("Discord bot token is empty")
        _private_write(token_file, token + "\n")
    bot = _request("GET", "/users/@me", token)
    dm = _request("POST", "/users/@me/channels", token, {"recipient_id": user_id})
    channel_id = str(dm.get("id", ""))
    if not ID_RE.fullmatch(channel_id):
        raise SystemExit("Discord did not return a valid DM channel ID")
    _private_write(ENV_PATH, "\n".join([
        f"DISCORD_BOT_TOKEN={token}",
        f"DISCORD_ALLOWED_USERS={user_id}",
        f"DISCORD_HOME_CHANNEL={channel_id}",
        "DISCORD_ALLOW_ALL_USERS=false",
        "",
    ]))
    _private_write(RUNTIME_PATH, json.dumps({
        "enabled": True,
        "dm_only": True,
        "allowed_user_id": user_id,
        "dm_channel_id": channel_id,
        "bot_user_id": str(bot.get("id", "")),
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": "configured",
        "dm_only": True,
        "allowed_user_id": user_id,
        "dm_channel_id": channel_id,
        "bot_user_id": str(bot.get("id", "")),
        "env_file": str(ENV_PATH),
    }, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True, help="Your Discord numeric user ID")
    parser.add_argument("--token-file", type=Path, default=TOKEN_PATH)
    parser.add_argument("--replace-token", action="store_true", help="Prompt for a new token even if one is stored")
    args = parser.parse_args()
    setup(args.user_id, args.token_file.expanduser(), args.replace_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

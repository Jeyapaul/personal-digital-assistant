#!/usr/bin/env python3
"""Microsoft Graph Mail.Read device-code OAuth bootstrap."""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get(
    "PERSONAL_ASSISTANT_DATA_DIR",
    str(Path.home() / ".hermes/personal-assistant-data"),
))
CREDENTIAL_DIR = DATA_DIR / "credentials"
TOKEN_PATH = CREDENTIAL_DIR / "microsoft.json"
REQUIRED_SCOPE = "Mail.Read"
SCOPES = "Mail.Read offline_access openid profile"
TENANT_RE = re.compile(r"^[A-Za-z0-9.-]+$")


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


def _private_json(path: Path, payload: dict) -> None:
    _private_write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _load_json(path: Path) -> dict:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise SystemExit(f"Credential file is unavailable: {path}") from exc
    if mode & 0o077:
        raise SystemExit(f"Credential file permissions are too broad: {path} (need 0600)")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Invalid JSON in {path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return payload


def _tenant(value: str) -> str:
    if not TENANT_RE.fullmatch(value) or value in {".", ".."}:
        raise SystemExit("Invalid Microsoft tenant value")
    return value


def _post_form(url: str, values: dict[str, str]) -> dict:
    body = urllib.parse.urlencode(values).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20, context=_ssl_context()) as response:
            payload = json.loads(response.read(128 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Microsoft returns useful, non-secret diagnostics for bad tenant,
        # client-registration, and consent configuration. Never print the
        # submitted form, authorization code, access token, or refresh token.
        try:
            raw = exc.read(16 * 1024).decode("utf-8", errors="replace")
            detail = json.loads(raw) if raw else {}
        except (OSError, ValueError):
            detail = {}
        if isinstance(detail, dict) and detail.get("error"):
            # The device-code token endpoint intentionally returns HTTP 400
            # with authorization_pending and slow_down while the user has not
            # completed consent. Let authenticate() handle those poll states.
            if detail.get("error") in {"authorization_pending", "slow_down"}:
                return detail
            code = str(detail.get("error"))
            description = str(detail.get("error_description") or "").replace("\\n", " ").strip()
            if len(description) > 300:
                description = description[:300] + "..."
            suffix = f": {code}"
            if description:
                suffix += f" — {description}"
        else:
            suffix = ": http_error"
        raise SystemExit(f"Microsoft OAuth request failed (HTTP {exc.code}){suffix}") from exc
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", "network error"))
        if len(reason) > 240:
            reason = reason[:240] + "..."
        raise SystemExit(f"Microsoft OAuth request failed before a response: {reason}") from exc
    except (TimeoutError, ssl.SSLError) as exc:
        raise SystemExit(f"Microsoft OAuth request failed before a response: {exc}") from exc
    except ValueError as exc:
        raise SystemExit("Microsoft OAuth returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Microsoft OAuth returned an invalid response")
    return payload


def _endpoints(tenant: str) -> tuple[str, str]:
    tenant = _tenant(tenant)
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
    return f"{base}/devicecode", f"{base}/token"


def authenticate(client_id: str, tenant: str) -> None:
    if not re.fullmatch(r"[A-Fa-f0-9-]{10,}", client_id):
        raise SystemExit("Client ID does not look like a Microsoft application ID")
    device_url, token_url = _endpoints(tenant)
    device = _post_form(device_url, {"client_id": client_id, "scope": SCOPES})
    if device.get("error"):
        raise SystemExit(f"Microsoft device-code error: {device['error']}")
    print(device.get("message") or f"Open {device.get('verification_uri')} and enter {device.get('user_code')}")
    interval = max(int(device.get("interval", 5)), 5)
    deadline = time.monotonic() + int(device.get("expires_in", 900))
    while time.monotonic() < deadline:
        time.sleep(interval)
        result = _post_form(token_url, {
            "client_id": client_id,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": str(device["device_code"]),
        })
        error = result.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error:
            raise SystemExit(f"Microsoft authorization failed: {error}")
        access_token = result.get("access_token")
        refresh_token = result.get("refresh_token")
        granted = set(str(result.get("scope", SCOPES)).split())
        if not access_token or not refresh_token or REQUIRED_SCOPE not in granted:
            raise SystemExit("Microsoft token did not include Mail.Read and refresh support")
        if not granted <= set(SCOPES.split()):
            raise SystemExit("Microsoft token contained scopes outside the approved mail-only set")
        expiry = datetime.now(timezone.utc) + timedelta(seconds=int(result.get("expires_in", 3600)))
        _private_json(TOKEN_PATH, {
            "access_token": str(access_token),
            "token": str(access_token),
            "refresh_token": str(refresh_token),
            "client_id": client_id,
            "tenant": tenant,
            "token_uri": token_url,
            "expiry": expiry.isoformat(),
            "scopes": sorted(granted),
        })
        print(f"Microsoft Mail.Read credentials stored at {TOKEN_PATH}")
        return
    raise SystemExit("Microsoft device code expired before authorization completed")


def check() -> None:
    payload = _load_json(TOKEN_PATH)
    scopes = set(payload.get("scopes") or str(payload.get("scope", "")).split())
    if REQUIRED_SCOPE not in scopes:
        raise SystemExit("Microsoft credential is missing Mail.Read")
    if not payload.get("refresh_token"):
        raise SystemExit("Microsoft credential has no refresh token")
    print(f"OK: Microsoft Mail.Read credential is valid at {TOKEN_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--auth", action="store_true")
    group.add_argument("--check", action="store_true")
    parser.add_argument("--client-id")
    parser.add_argument("--tenant", default="organizations")
    args = parser.parse_args()
    if args.auth:
        if not args.client_id:
            parser.error("--client-id is required with --auth")
        authenticate(args.client_id, args.tenant)
    else:
        check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

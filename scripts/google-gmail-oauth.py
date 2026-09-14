#!/usr/bin/env python3
"""Narrow Gmail read-only OAuth bootstrap for the personal assistant.

This intentionally does not reuse Hermes' broad Google Workspace scope list.
It uses desktop OAuth + PKCE and stores a refreshable authorized-user payload
under the persistent assistant data directory.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import ssl
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_HOST = "accounts.google.com"
TOKEN_HOST = "oauth2.googleapis.com"
REDIRECT_URI = "http://localhost:1/"
DATA_DIR = Path(os.environ.get(
    "PERSONAL_ASSISTANT_DATA_DIR",
    str(Path.home() / ".hermes/personal-assistant-data"),
))
CREDENTIAL_DIR = DATA_DIR / "credentials"
CLIENT_PATH = CREDENTIAL_DIR / "google-gmail-client.json"
TOKEN_PATH = CREDENTIAL_DIR / "gmail.json"
PENDING_PATH = CREDENTIAL_DIR / "google-gmail-pending.json"
LAST_URL_PATH = CREDENTIAL_DIR / "google-gmail-last-url.txt"


def _ssl_context() -> ssl.SSLContext:
    """Use certifi when the macOS system Python lacks a CA bundle."""
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


def _client(payload: dict) -> tuple[str, str, str, str]:
    section = payload.get("installed") or payload.get("web")
    if not isinstance(section, dict):
        raise SystemExit("OAuth client JSON must contain an installed or web object")
    client_id = section.get("client_id")
    client_secret = section.get("client_secret", "")
    auth_uri = section.get("auth_uri", "https://accounts.google.com/o/oauth2/v2/auth")
    token_uri = section.get("token_uri", "https://oauth2.googleapis.com/token")
    parsed_auth = urllib.parse.urlparse(str(auth_uri))
    parsed_token = urllib.parse.urlparse(str(token_uri))
    if parsed_auth.scheme != "https" or parsed_auth.hostname != AUTH_HOST:
        raise SystemExit("OAuth client auth endpoint is not an approved Google endpoint")
    if parsed_token.scheme != "https" or parsed_token.hostname != TOKEN_HOST:
        raise SystemExit("OAuth client token endpoint is not an approved Google endpoint")
    if not client_id or not client_secret:
        raise SystemExit("OAuth client JSON is missing client_id or client_secret")
    return str(client_id), str(client_secret), str(auth_uri), str(token_uri)


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
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read(64 * 1024).decode("utf-8"))
        except (ValueError, UnicodeError):
            error_payload = {}
        error = error_payload.get("error", "http_error")
        description = error_payload.get("error_description", "")
        detail = f": {description}" if description else ""
        if error == "invalid_grant":
            raise SystemExit(
                "Google OAuth authorization code was rejected (expired, already used, "
                "or redirect/client mismatch). Run --auth-url again and exchange only "
                "the newest redirect URL once."
            ) from exc
        raise SystemExit(f"Google OAuth token request failed ({error}){detail}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SystemExit("Google OAuth token request failed before a response was received") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Google OAuth returned an invalid token response")
    if payload.get("error"):
        description = payload.get("error_description", "")
        detail = f": {description}" if description else ""
        raise SystemExit(f"Google OAuth error: {payload['error']}{detail}")
    return payload


def store_client_secret(path: str) -> None:
    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Invalid OAuth client JSON: {source}") from exc
    _client(payload)
    _private_json(CLIENT_PATH, payload)
    print(f"Google OAuth client stored at {CLIENT_PATH}")


def create_auth_url() -> None:
    client_id, _secret, auth_uri, _token_uri = _client(_load_json(CLIENT_PATH))
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    query = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    url = f"{auth_uri}?{query}"
    _private_json(PENDING_PATH, {
        "client_id": client_id,
        "state": state,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT_URI,
    })
    _private_write(LAST_URL_PATH, url + "\n")
    print(url)


def _code_from_value(value: str) -> tuple[str, str | None]:
    if not value.startswith("http"):
        return value, None
    query = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
    if query.get("error"):
        raise SystemExit(f"Google authorization failed: {query['error'][0]}")
    if not query.get("code"):
        raise SystemExit("Redirect URL does not contain an authorization code")
    return query["code"][0], (query.get("state") or [None])[0]


def exchange(value: str) -> None:
    pending = _load_json(PENDING_PATH)
    client = _load_json(CLIENT_PATH)
    client_id, client_secret, _auth_uri, token_uri = _client(client)
    if pending.get("client_id") != client_id:
        raise SystemExit("Pending OAuth session does not match the stored client")
    code, returned_state = _code_from_value(value)
    if returned_state and returned_state != pending.get("state"):
        raise SystemExit("OAuth state mismatch; run --auth-url again")
    response = _post_form(token_uri, {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "code_verifier": str(pending["code_verifier"]),
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    })
    access_token = response.get("access_token")
    refresh_token = response.get("refresh_token")
    if not access_token or not refresh_token:
        raise SystemExit("Google did not return both access and refresh tokens; rerun --auth-url with consent")
    granted = set(str(response.get("scope", SCOPE)).split())
    if granted != {SCOPE}:
        raise SystemExit("Google token contained scopes outside Gmail read-only access")
    expiry = datetime.now(timezone.utc) + timedelta(seconds=int(response.get("expires_in", 3600)))
    token = {
        "type": "authorized_user",
        "access_token": str(access_token),
        "token": str(access_token),
        "refresh_token": str(refresh_token),
        "client_id": client_id,
        "client_secret": client_secret,
        "token_uri": token_uri,
        "expiry": expiry.isoformat(),
        "scopes": sorted(granted),
    }
    _private_json(TOKEN_PATH, token)
    PENDING_PATH.unlink(missing_ok=True)
    print(f"Gmail read-only credentials stored at {TOKEN_PATH}")


def check() -> None:
    payload = _load_json(TOKEN_PATH)
    scopes = set(payload.get("scopes") or str(payload.get("scope", "")).split())
    if SCOPE not in scopes:
        raise SystemExit("Gmail credential is missing the required read-only scope")
    if not payload.get("refresh_token"):
        raise SystemExit("Gmail credential has no refresh token")
    print(f"OK: Gmail read-only credential is valid at {TOKEN_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--client-secret")
    group.add_argument("--auth-url", action="store_true")
    group.add_argument("--auth-code")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.client_secret:
        store_client_secret(args.client_secret)
    elif args.auth_url:
        create_auth_url()
    elif args.auth_code:
        exchange(args.auth_code)
    else:
        check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

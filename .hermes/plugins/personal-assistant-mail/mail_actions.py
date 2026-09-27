"""Fixed provider mutation adapters for explicitly approved mail batches."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from .mail_sources import (
    GMAIL_MODIFY_SCOPE,
    GRAPH_HOST,
    GRAPH_MANAGEMENT_SCOPE,
    GMAIL_HOST,
    _assert_api_url,
    _ssl_context,
    load_access_token,
)

ALLOWED_ACTIONS = {"label", "archive", "spam", "unsubscribe"}
UNSUBSCRIBE_ALLOWED_HOSTS = {
    item.strip().lower()
    for item in __import__("os").environ.get("PDA_UNSUBSCRIBE_ALLOWED_HOSTS", "").split(",")
    if item.strip()
}
LABELS = {
    "Action needed": "PDA/Action Needed",
    "Finance": "PDA/Finance",
    "Newsletter": "PDA/Newsletter",
    "Promotional": "PDA/Promotional",
    "Travel": "PDA/Travel",
    "Review": "PDA/Review",
}
PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9_=+/.-]{1,512}$")


class MailActionError(RuntimeError):
    """A safe action failure without credential or message-body contents."""


def _request_json(
    method: str,
    url: str,
    host: str,
    token: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    _assert_api_url(url, host)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20, context=_ssl_context()) as response:
            raw = response.read(256 * 1024).decode("utf-8")
            if not raw:
                return {}
            value = json.loads(raw)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise MailActionError(f"{host} mail action failed") from exc
    if not isinstance(value, dict):
        raise MailActionError(f"{host} returned an invalid action response")
    return value


def _message_id(value: str) -> str:
    if not isinstance(value, str) or not PROVIDER_ID_RE.fullmatch(value):
        raise MailActionError("invalid provider message identifier")
    return value


def _gmail_label_id(token: str, label_name: str) -> str:
    labels = _request_json(
        "GET",
        "https://gmail.googleapis.com/gmail/v1/users/me/labels",
        GMAIL_HOST,
        token,
    )
    for label in labels.get("labels") or []:
        if isinstance(label, dict) and label.get("name") == label_name:
            label_id = str(label.get("id") or "")
            if label_id:
                return label_id
    created = _request_json(
        "POST",
        "https://gmail.googleapis.com/gmail/v1/users/me/labels",
        GMAIL_HOST,
        token,
        {"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
    )
    label_id = str(created.get("id") or "")
    if not label_id:
        raise MailActionError("Gmail label creation returned no label identifier")
    return label_id


def _apply_gmail(message_id: str, action: str, category: str, token: str) -> None:
    message_id = _message_id(message_id)
    body: Dict[str, Any] = {"addLabelIds": [], "removeLabelIds": []}
    if action == "label":
        label_name = LABELS.get(category)
        if not label_name:
            raise MailActionError("message category is not an approved label")
        body["addLabelIds"] = [_gmail_label_id(token, label_name)]
    elif action == "archive":
        body["removeLabelIds"] = ["INBOX"]
    elif action == "spam":
        body["addLabelIds"] = ["SPAM"]
    elif action == "unsubscribe":
        raise MailActionError("Gmail unsubscribe requires an approved HTTPS List-Unsubscribe target")
    else:
        raise MailActionError("action is not enabled")
    _request_json(
        "POST",
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
        + urllib.parse.quote(message_id, safe="")
        + "/modify",
        GMAIL_HOST,
        token,
        body,
    )


def _graph_message_url(message_id: str) -> str:
    return "https://graph.microsoft.com/v1.0/me/messages/" + urllib.parse.quote(
        _message_id(message_id), safe=""
    )


def _apply_graph(message_id: str, action: str, category: str, token: str) -> None:
    message_url = _graph_message_url(message_id)
    if action == "label":
        label_name = LABELS.get(category)
        if not label_name:
            raise MailActionError("message category is not an approved category")
        current = _request_json(
            "GET", message_url + "?$select=categories", GRAPH_HOST, token,
        )
        categories = [str(item) for item in current.get("categories") or []]
        if label_name not in categories:
            categories.append(label_name)
        _request_json("PATCH", message_url, GRAPH_HOST, token, {"categories": categories})
    elif action in {"archive", "spam"}:
        destination = "archive" if action == "archive" else "junkemail"
        _request_json(
            "POST",
            message_url + "/move",
            GRAPH_HOST,
            token,
            {"destinationId": destination},
        )
    elif action == "unsubscribe":
        raise MailActionError("Microsoft unsubscribe requires an approved HTTPS List-Unsubscribe target")
    else:
        raise MailActionError("action is not enabled")


def _mark_gmail_read(message_id: str, token: str) -> None:
    _request_json(
        "POST",
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
        + urllib.parse.quote(_message_id(message_id), safe="")
        + "/modify",
        GMAIL_HOST,
        token,
        {"removeLabelIds": ["UNREAD"]},
    )


def _mark_graph_read(message_id: str, token: str) -> None:
    _request_json(
        "PATCH",
        _graph_message_url(message_id),
        GRAPH_HOST,
        token,
        {"isRead": True},
    )


def mark_messages_read(refs: list[Dict[str, str]], data_dir: Path) -> Dict[str, Any]:
    """Mark exactly the messages in a delivered report read.

    This operation is deliberately separate from the approval-gated organizer
    actions. It is called only by the post-delivery finalizer and is idempotent.
    """
    grouped: Dict[str, list[str]] = {"gmail": [], "microsoft": []}
    for ref in refs:
        source = str(ref.get("source", ""))
        message_id = str(ref.get("message_id", ""))
        if source not in grouped or not message_id:
            return {"success": False, "marked": 0, "error": "invalid report message reference"}
        try:
            _message_id(message_id)
        except MailActionError:
            return {"success": False, "marked": 0, "error": "invalid report message reference"}
        grouped[source].append(message_id)

    marked = 0
    errors: Dict[str, str] = {}
    for source, message_ids in grouped.items():
        if not message_ids:
            continue
        try:
            if source == "gmail":
                token = load_access_token(
                    data_dir / "credentials/gmail-management.json", GMAIL_MODIFY_SCOPE
                )
                for message_id in message_ids:
                    _mark_gmail_read(message_id, token)
            else:
                token = load_access_token(
                    data_dir / "credentials/microsoft-management.json", GRAPH_MANAGEMENT_SCOPE
                )
                for message_id in message_ids:
                    _mark_graph_read(message_id, token)
            marked += len(message_ids)
        except Exception as exc:  # noqa: BLE001 - return a safe retryable error
            errors[source] = str(exc)[:240]

    return {
        "success": not errors,
        "marked": marked,
        "requested": len(refs),
        "errors": errors,
    }


def _apply_unsubscribe(target: str) -> None:
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.lower() not in UNSUBSCRIBE_ALLOWED_HOSTS:
        raise MailActionError("unsubscribe target is not on the configured HTTPS host allowlist")
    request = urllib.request.Request(
        target, data=b"", headers={
            "User-Agent": "PersonalAssistant/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "List-Unsubscribe": "One-Click",
        }, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=20, context=__import__("ssl").create_default_context()) as response:
            if int(getattr(response, "status", 200)) >= 400:
                raise MailActionError("unsubscribe endpoint rejected the request")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MailActionError("unsubscribe endpoint failed") from exc


def apply_action(
    source: str,
    message_id: str,
    action: str,
    category: str,
    data_dir: Path,
    target: str = "",
) -> None:
    """Apply exactly one allowlisted action to exactly one stored message ID."""
    if action not in ALLOWED_ACTIONS:
        raise MailActionError("action is not enabled; delete, trash, send, and arbitrary read actions are unavailable")
    if action == "unsubscribe":
        _apply_unsubscribe(target)
        return
    if source == "gmail":
        token = load_access_token(
            data_dir / "credentials/gmail-management.json", GMAIL_MODIFY_SCOPE
        )
        _apply_gmail(message_id, action, category, token)
    elif source == "microsoft":
        token = load_access_token(
            data_dir / "credentials/microsoft-management.json", GRAPH_MANAGEMENT_SCOPE
        )
        _apply_graph(message_id, action, category, token)
    else:
        raise MailActionError("mail source is not enabled")

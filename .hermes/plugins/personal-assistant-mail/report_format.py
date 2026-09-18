"""Deterministic, safe per-message formatting for the Discord mail report."""

from __future__ import annotations

import html
import re
from typing import Any, Dict, Iterable, List

MAX_EXCERPT_CHARS = 280


def _plain(value: Any, limit: int = 500, strip_html: bool = False) -> str:
    text = html.unescape(str(value or ""))
    if strip_html:
        text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text[:limit]


def _inline(value: Any, limit: int = 500) -> str:
    text = html.escape(_plain(value, limit), quote=False)
    # Keep message data from changing the report's Markdown structure.
    return re.sub(r"([\\`*_{}\[\]()#+!|>~-])", r"\\\1", text)


def _timestamp(value: Any) -> str:
    text = _plain(value, 80)
    if "T" in text:
        text = text.replace("T", " ", 1)
    return text.rsplit("+", 1)[0].strip() if "+" in text else text


def _quoted_excerpt(value: Any) -> str:
    text = _plain(value, MAX_EXCERPT_CHARS, strip_html=True)
    if not text:
        return "> (no text body available)"
    return "\n".join(f"> {_inline(line, 240)}" for line in text.splitlines())


def _source_name(value: Any) -> str:
    return {"gmail": "Gmail", "microsoft": "Microsoft"}.get(
        str(value).lower(), _inline(value, 40) or "Unknown"
    )


def format_message(message: Dict[str, Any], number: int) -> str:
    """Render one message without exposing provider IDs or executable links."""
    attachments = message.get("attachment_names") or []
    attachment_text = ", ".join(_inline(item, 255) for item in attachments) or "None"
    sender = _inline(message.get("sender") or message.get("sender_name") or "Unknown sender")
    subject = _inline(message.get("subject") or "(no subject)")
    source = _source_name(message.get("source"))
    status = "Unread at collection" if message.get("unread") else "Read at collection"
    category = _inline(message.get("management_category"))
    actions = message.get("proposed_actions") or []
    action_text = ", ".join(_inline(item, 120) for item in actions)
    metadata = [
        f"### {number:02d} · {source} · {_timestamp(message.get('received_at_ist'))}",
        f"**From:** {sender}",
        f"**Subject:** {subject}",
        f"**Status:** {status}",
    ]
    if category:
        metadata.append(f"**Category proposal:** {category}")
    if action_text:
        metadata.append(f"**Proposed actions:** {action_text}")
    metadata.extend([
        f"**Attachments:** {attachment_text} (names only; bytes not downloaded)",
        "",
    ])
    return "\n".join(
        metadata + [

            "**Untrusted content excerpt:**",
            _quoted_excerpt(message.get("body")),
        ]
    )


def format_report(messages: Iterable[Dict[str, Any]]) -> str:
    """Render all messages in stable source/time order with one block each."""
    items: List[Dict[str, Any]] = list(messages)
    if not items:
        return "No messages were collected for this report."
    return "\n\n---\n\n".join(
        format_message(message, index)
        for index, message in enumerate(items, start=1)
    )

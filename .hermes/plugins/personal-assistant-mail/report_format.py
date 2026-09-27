"""Deterministic, concise, safe formatting for Discord mail messages."""

from __future__ import annotations

import html
import re
from typing import Any, Dict, Iterable, List

MAX_SUMMARY_CHARS = 180
MAX_ACTION_CHARS = 120
MAX_REASON_CHARS = 150
MAX_SENDER_CHARS = 100
MAX_SUBJECT_CHARS = 160


def _plain(value: Any, limit: int = 500, strip_html: bool = False) -> str:
    text = html.unescape(str(value or ""))
    if strip_html:
        text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = " ".join(text.split())
    return text[:limit]


def _inline(value: Any, limit: int = 500) -> str:
    text = html.escape(_plain(value, limit), quote=False)
    # Keep untrusted mail data from changing the report's Markdown structure.
    return re.sub(r"([\\`*_{}\[\]()#+!|>~-])", r"\\\1", text)


def _source_name(value: Any) -> str:
    return {"gmail": "Gmail", "microsoft": "Microsoft"}.get(
        str(value).lower(), _inline(value, 40) or "Mail"
    )


def _time(value: Any) -> str:
    text = _plain(value, 80)
    if "T" in text:
        text = text.replace("T", " ", 1)
    text = text.rsplit("+", 1)[0].strip()
    return text[-8:] if len(text) >= 8 and re.fullmatch(r"\d{2}:\d{2}:\d{2}", text[-8:]) else text


def _action(value: Any) -> str:
    text = _plain(value, MAX_ACTION_CHARS)
    text = re.sub(r"[.;,]?\s*no action was taken\.?", "", text, flags=re.I).strip(" .;,")
    return text or "Review"


def _human_action(value: Any) -> str:
    text = _plain(value, MAX_ACTION_CHARS)
    if text.startswith("label:"):
        return f'Add the “{text.split(":", 1)[1]}” label'
    replacements = {
        "review for archive": "Archive",
        "review for spam": "Mark as spam",
        "manual unsubscribe review": "Review unsubscribe options",
        "unsubscribe": "Unsubscribe",
    }
    return replacements.get(text.lower(), text)


def format_message(message: Dict[str, Any], number: int) -> str:
    """Render one compact message without provider IDs or raw body excerpts."""
    sender = _inline(message.get("sender") or message.get("sender_name") or "Unknown sender", MAX_SENDER_CHARS)
    subject = _inline(message.get("subject") or "(no subject)", MAX_SUBJECT_CHARS)
    source = _source_name(message.get("source"))
    timestamp = _time(message.get("received_at_ist"))
    summary = _inline(message.get("model_summary"), MAX_SUMMARY_CHARS)
    action = _action(message.get("suggested_action"))
    lines = [f"**{number}. {sender}** — {subject}", f"_{source} · {timestamp}_"]
    if summary:
        lines.append(f"{summary}")
    if action and not message.get("proposed_actions"):
        lines.append(f"**Suggested:** {action}")

    attachments = [_inline(item, 100) for item in (message.get("attachment_names") or [])]
    if attachments:
        lines.append("**Attachment:** " + ", ".join(attachments))

    proposed = [_human_action(item) for item in (message.get("proposed_actions") or [])]
    if proposed:
        lines.append("**Suggested action:** " + ", ".join(_inline(item, 120) for item in proposed))
    if message.get("management_reason"):
        reason = _plain(message.get("management_reason"), MAX_REASON_CHARS)
        match = re.search(r"as ([^.]+)\.$", reason)
        if reason.startswith("Classified from sender, subject, and a bounded body excerpt") and match:
            reason = f"This message appears to relate to {match.group(1)}."
        lines.append(f"**Why:** {_inline(reason, MAX_REASON_CHARS)}")
    return "\n".join(lines)


def format_report(messages: Iterable[Dict[str, Any]], start_number: int = 1) -> str:
    """Render every message as a compact, numbered block."""
    items: List[Dict[str, Any]] = list(messages)
    if not items:
        return "📭 No unread messages found."
    return "\n\n".join(
        format_message(message, index)
        for index, message in enumerate(items, start=start_number)
    )

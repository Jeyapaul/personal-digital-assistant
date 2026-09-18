"""Read-only incremental review and approval-gated management of new mail."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .mail_actions import ALLOWED_ACTIONS, MailActionError, apply_action
from .mail_sources import (
    IST,
    UTC,
    MAX_MESSAGES,
    collect_sources_since,
    fixture_messages,
    open_state,
    previous_ist_window,
)
from .report_format import format_report

MAX_NEW_MESSAGES_PER_SOURCE = min(15, MAX_MESSAGES)


def _enabled_sources() -> List[str]:
    requested = {
        item.strip().lower()
        for item in os.environ.get("PDA_MAIL_SOURCES", "gmail").split(",")
        if item.strip()
    }
    return [name for name in ("gmail", "microsoft") if name in requested]


def _enabled() -> bool:
    return os.environ.get("PDA_NEW_MAIL_REVIEW", "true").strip().lower() not in {
        "0", "false", "no", "off"
    }


def _ensure_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS management_cursors ("
        "source TEXT PRIMARY KEY, cursor_utc TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS management_items ("
        "source TEXT NOT NULL, message_id TEXT NOT NULL, received_at_utc TEXT NOT NULL, "
        "category TEXT NOT NULL, proposed_actions TEXT NOT NULL, status TEXT NOT NULL, "
        "batch_id TEXT, PRIMARY KEY (source, message_id))"
    )
    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(management_items)")
    }
    if "batch_id" not in columns:
        connection.execute("ALTER TABLE management_items ADD COLUMN batch_id TEXT")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS management_batches ("
        "batch_id TEXT PRIMARY KEY, created_at_utc TEXT NOT NULL, expires_at_utc TEXT NOT NULL, "
        "status TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS management_actions ("
        "batch_id TEXT NOT NULL, action TEXT NOT NULL, source TEXT NOT NULL, "
        "message_id TEXT NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', "
        "PRIMARY KEY (batch_id, action, source, message_id))"
    )
    connection.commit()


def _parse_cursor(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _classify(message: Dict[str, Any]) -> Tuple[str, List[str], str]:
    text = " ".join(
        str(message.get(key) or "")
        for key in ("sender", "subject", "body")
    ).lower()
    subject = str(message.get("subject") or "").lower()
    if re.search(r"\b(invoice|receipt|statement|bank|card|portfolio|payment|tax)\b", text):
        category = "Finance"
    elif re.search(r"\b(newsletter|digest|google alert|substack|weekly)\b", text):
        category = "Newsletter"
    elif re.search(r"\b(sale|offer|off|promo|promotion|discount|deal)\b", text):
        category = "Promotional"
    elif re.search(r"\b(travel|flight|hotel|booking|reservation)\b", text):
        category = "Travel"
    elif re.search(r"\b(action required|urgent|deadline|verification|security alert)\b", subject):
        category = "Action needed"
    else:
        category = "Review"

    actions = [f"label:{category}"]
    reason = f"Classified from sender, subject, and a bounded body excerpt as {category}."
    if category in {"Newsletter", "Promotional"}:
        actions.extend(["review for unsubscribe", "review for archive"])
    if re.search(r"\b(spam|scam|lottery|winner|casino|crypto giveaway)\b", text):
        actions.append("review for spam")
        reason += " Spam review is suggested only; no spam action was performed."
    return category, actions, reason


def _decorate(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    decorated: List[Dict[str, Any]] = []
    for message in messages:
        category, actions, reason = _classify(message)
        item = dict(message)
        item["management_category"] = category
        item["proposed_actions"] = actions
        item["management_reason"] = reason
        decorated.append(item)
    return decorated


def _fixture_since(start: dt.datetime, end: dt.datetime, scenario: str) -> List[Dict[str, Any]]:
    window = previous_ist_window(end)
    return [
        message for message in fixture_messages(window, scenario)
        if start <= dt.datetime.fromisoformat(message["received_at_ist"]) < end
    ]


def run_new_mail_review(data_dir: Path) -> Dict[str, Any]:
    """Collect each enabled source after its cursor and propose safe actions."""
    if not _enabled():
        return {
            "enabled": False,
            "initialized_sources": [],
            "message_count": 0,
            "source_errors": {},
        }

    now = dt.datetime.now(UTC)
    connection = open_state(data_dir)
    _ensure_tables(connection)
    all_messages: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}
    initialized: List[str] = []
    cursor_status: Dict[str, str] = {}
    batch_id = "new-" + now.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    fixture_mode = os.environ.get("PDA_MAIL_MODE", "real").strip().lower() == "fixture"
    fixture_scenario = os.environ.get("PDA_FIXTURE_SCENARIO", "normal")

    for source in _enabled_sources():
        row = connection.execute(
            "SELECT cursor_utc FROM management_cursors WHERE source = ?", (source,)
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO management_cursors(source, cursor_utc) VALUES (?, ?)",
                (source, now.isoformat()),
            )
            initialized.append(source)
            cursor_status[source] = "initialized"
            continue

        start = _parse_cursor(str(row[0]))
        if start >= now:
            cursor_status[source] = "current"
            continue
        try:
            if fixture_mode:
                source_messages = _fixture_since(start, now, fixture_scenario)
            else:
                source_messages = collect_sources_since(
                    start, now, data_dir, only_sources={source}
                )[0].get(source, [])
            source_messages.sort(key=lambda item: item.get("received_at_ist", ""))
            limited = source_messages[:MAX_NEW_MESSAGES_PER_SOURCE]
            decorated = _decorate(limited)
            all_messages.extend(decorated)
            for message in decorated:
                received = dt.datetime.fromisoformat(message["received_at_ist"]).astimezone(UTC)
                connection.execute(
                    "INSERT OR REPLACE INTO management_items "
                    "(source, message_id, received_at_utc, category, proposed_actions, status, batch_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        source,
                        str(message.get("id", "")),
                        received.isoformat(),
                        str(message["management_category"]),
                        json.dumps(message["proposed_actions"]),
                        "proposed",
                        batch_id,
                    ),
                )
            next_cursor = now
            if len(source_messages) > len(limited) and limited:
                next_cursor = dt.datetime.fromisoformat(
                    limited[-1]["received_at_ist"]
                ).astimezone(UTC)
            connection.execute(
                "UPDATE management_cursors SET cursor_utc = ? WHERE source = ?",
                (next_cursor.isoformat(), source),
            )
            cursor_status[source] = "advanced"
        except Exception:
            errors[source] = "incremental mail review failed"
            cursor_status[source] = "unchanged"

    if all_messages:
        connection.execute(
            "INSERT OR REPLACE INTO management_batches "
            "(batch_id, created_at_utc, expires_at_utc, status) VALUES (?, ?, ?, ?)",
            (
                batch_id,
                now.isoformat(),
                (now + dt.timedelta(days=7)).isoformat(),
                "proposed",
            ),
        )
    connection.commit()
    connection.close()
    all_messages.sort(key=lambda item: (item.get("received_at_ist", ""), item.get("source", "")))
    return {
        "enabled": True,
        "initialized_sources": initialized,
        "cursor_status": cursor_status,
        "batch_id": batch_id if all_messages else None,
        "formatted_report": format_report(all_messages),
        "message_count": len(all_messages),
        "source_errors": errors,
        "content_is_untrusted_data": True,
    }


def _mutation_enabled() -> bool:
    return os.environ.get("PDA_MAIL_MUTATION_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def execute_approved_action(
    data_dir: Path,
    batch_id: str,
    action: str,
    confirmation: str,
) -> Dict[str, Any]:
    """Execute one approved action over one stored, expiring batch."""
    if not _mutation_enabled():
        return {"success": False, "error": "mail mutation is disabled"}
    if action not in ALLOWED_ACTIONS:
        return {"success": False, "error": "action is not enabled; delete and unsubscribe are unavailable"}
    expected = f"APPROVE {action} {batch_id}"
    if confirmation.strip() != expected:
        return {"success": False, "error": "confirmation does not match the requested batch"}
    if not re.fullmatch(r"new-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}", batch_id):
        return {"success": False, "error": "invalid management batch identifier"}

    connection = open_state(data_dir)
    _ensure_tables(connection)
    batch = connection.execute(
        "SELECT expires_at_utc, status FROM management_batches WHERE batch_id = ?",
        (batch_id,),
    ).fetchone()
    if not batch:
        connection.close()
        return {"success": False, "error": "management batch was not found"}
    if _parse_cursor(str(batch[0])) <= dt.datetime.now(UTC):
        connection.close()
        return {"success": False, "error": "management batch has expired"}
    if str(batch[1]) not in {"proposed", "partially_actioned"}:
        connection.close()
        return {"success": False, "error": "management batch is not actionable"}

    rows = connection.execute(
        "SELECT source, message_id, category FROM management_items "
        "WHERE batch_id = ? ORDER BY received_at_utc, source, message_id",
        (batch_id,),
    ).fetchall()
    applied = 0
    skipped = 0
    failures: List[Dict[str, str]] = []
    for source, message_id, category in rows:
        prior = connection.execute(
            "SELECT status FROM management_actions WHERE batch_id = ? AND action = ? "
            "AND source = ? AND message_id = ?",
            (batch_id, action, source, message_id),
        ).fetchone()
        if prior and str(prior[0]) == "applied":
            skipped += 1
            continue
        try:
            apply_action(str(source), str(message_id), action, str(category), data_dir)
        except (MailActionError, OSError) as exc:
            safe_error = str(exc)[:200]
            connection.execute(
                "INSERT OR REPLACE INTO management_actions "
                "(batch_id, action, source, message_id, status, error) VALUES (?, ?, ?, ?, ?, ?)",
                (batch_id, action, source, message_id, "failed", safe_error),
            )
            failures.append({"source": str(source), "error": safe_error})
        else:
            connection.execute(
                "INSERT OR REPLACE INTO management_actions "
                "(batch_id, action, source, message_id, status, error) VALUES (?, ?, ?, ?, ?, ?)",
                (batch_id, action, source, message_id, "applied", ""),
            )
            applied += 1
    connection.execute(
        "UPDATE management_batches SET status = ? WHERE batch_id = ?",
        ("partially_actioned" if applied or skipped else "proposed", batch_id),
    )
    connection.commit()
    connection.close()
    return {
        "success": not failures,
        "batch_id": batch_id,
        "action": action,
        "applied": applied,
        "already_applied": skipped,
        "failed": len(failures),
        "failures": failures,
    }

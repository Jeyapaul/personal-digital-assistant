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
    connection.execute(
        "CREATE TABLE IF NOT EXISTS management_recommendations ("
        "recommendation_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, source TEXT NOT NULL, "
        "message_id TEXT NOT NULL, sender TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '', "
        "action TEXT NOT NULL, category TEXT NOT NULL, reason TEXT NOT NULL, confidence REAL NOT NULL, "
        "target TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', created_at_utc TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS management_approval_audit ("
        "audit_id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, "
        "recommendation_id TEXT, event TEXT NOT NULL, decision TEXT NOT NULL, "
        "discord_user_id TEXT NOT NULL, discord_message_id TEXT, approval_message_id TEXT, "
        "details TEXT NOT NULL DEFAULT '', created_at_utc TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS management_approval_requests ("
        "batch_id TEXT PRIMARY KEY, discord_channel_id TEXT NOT NULL, "
        "discord_message_id TEXT NOT NULL, created_at_utc TEXT NOT NULL, "
        "expires_at_utc TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open')"
    )
    # Approval requests are intentionally indefinite. Clear the legacy 24-hour
    # deadline from any still-open rows created before this policy changed.
    connection.execute(
        "UPDATE management_approval_requests SET expires_at_utc='' WHERE status='open'"
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
        unsubscribe = message.get("unsubscribe_targets") or {}
        if unsubscribe.get("https") and unsubscribe.get("one_click"):
            actions.append("unsubscribe")
        elif unsubscribe.get("https") or unsubscribe.get("mailto"):
            actions.append("manual unsubscribe review")
        actions.append("review for archive")
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


def _expire_approval_requests(connection: sqlite3.Connection, now: dt.datetime) -> None:
    expired = connection.execute(
        "SELECT batch_id FROM management_approval_requests "
        "WHERE status='open' AND expires_at_utc <> '' AND expires_at_utc <= ?",
        (now.isoformat(),),
    ).fetchall()
    for (batch_id,) in expired:
        pending = connection.execute(
            "SELECT recommendation_id FROM management_recommendations WHERE batch_id = ? AND status='pending'",
            (batch_id,),
        ).fetchall()
        for (recommendation_id,) in pending:
            connection.execute(
                "UPDATE management_recommendations SET status='denied' WHERE recommendation_id = ?",
                (recommendation_id,),
            )
            _audit(connection, str(batch_id), str(recommendation_id), "expiry", "denied", "system", "", "", "unmentioned recommendation denied at expiry")
        connection.execute("UPDATE management_approval_requests SET status='closed' WHERE batch_id = ?", (batch_id,))


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
    _expire_approval_requests(connection, now)
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
                recommendations = []
                for proposed in message.get("proposed_actions") or []:
                    action = (
                        "archive" if proposed == "review for archive" else
                        "spam" if proposed == "review for spam" else
                        proposed.split(":", 1)[0]
                    )
                    if action not in {"label", "archive", "spam", "unsubscribe"}:
                        continue
                    targets = message.get("unsubscribe_targets") or {}
                    target = (targets.get("https") or targets.get("mailto") or [""])[0] if action == "unsubscribe" else ""
                    recommendation_id = "rec-" + secrets.token_hex(8)
                    confidence = 0.92 if action in {"label", "archive"} else 0.85
                    reason = str(message["management_reason"])
                    if action == "archive":
                        reason = f"{reason} Archiving is suggested because this category is generally informational or promotional and does not require inbox attention."
                    elif action == "spam":
                        reason = f"{reason} Spam is suggested because the bounded content contains suspicious spam indicators."
                    elif action == "unsubscribe":
                        reason = f"{reason} Unsubscribe is suggested because the sender supplied an explicit List-Unsubscribe target."
                    connection.execute(
                        "INSERT INTO management_recommendations "
                        "(recommendation_id,batch_id,source,message_id,sender,subject,action,category,reason,confidence,target,status,created_at_utc) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (recommendation_id, batch_id, source, str(message.get("id", "")),
                         str(message.get("sender") or message.get("sender_name") or ""),
                         str(message.get("subject") or ""), action,
                         str(message["management_category"]), reason,
                         confidence, target, "pending", now.isoformat()),
                    )
                    recommendations.append(recommendation_id)
                message["recommendation_ids"] = recommendations
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
                "",
                "proposed",
            ),
        )
    recommendations = [
        {"recommendation_id": str(row[0]), "action": str(row[1]), "category": str(row[2]),
         "reason": str(row[3]), "confidence": float(row[4]), "source": str(row[5]),
         "message_id": str(row[6]), "sender": str(row[7]), "subject": str(row[8])}
        for row in connection.execute(
            "SELECT recommendation_id, action, category, reason, confidence, source, message_id, sender, subject "
            "FROM management_recommendations WHERE batch_id = ? ORDER BY recommendation_id", (batch_id,)
        ).fetchall()
    ] if all_messages else []
    connection.commit()
    connection.close()
    all_messages.sort(key=lambda item: (item.get("received_at_ist", ""), item.get("source", "")))
    return {
        "enabled": True,
        "initialized_sources": initialized,
        "cursor_status": cursor_status,
        "batch_id": batch_id if all_messages else None,
        "formatted_report": format_report(all_messages),
        "recommendations": recommendations,
        "message_count": len(all_messages),
        "source_errors": errors,
        "content_is_untrusted_data": True,
    }


def record_approval_request(
    data_dir: Path, batch_id: str, channel_id: str, message_id: str, expires_at: str = ""
) -> None:
    connection = open_state(data_dir)
    _ensure_tables(connection)
    connection.execute(
        "INSERT OR REPLACE INTO management_approval_requests "
        "(batch_id,discord_channel_id,discord_message_id,created_at_utc,expires_at_utc,status) "
        "VALUES (?,?,?,?,?, 'open')",
        (batch_id, channel_id, message_id, dt.datetime.now(UTC).isoformat(), expires_at),
    )
    connection.commit()
    connection.close()


def _audit(connection: sqlite3.Connection, batch_id: str, recommendation_id: str | None,
           event: str, decision: str, user_id: str, message_id: str, approval_id: str,
           details: str = "") -> None:
    connection.execute(
        "INSERT INTO management_approval_audit "
        "(batch_id,recommendation_id,event,decision,discord_user_id,discord_message_id,approval_message_id,details,created_at_utc) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (batch_id, recommendation_id, event, decision, user_id, message_id, approval_id,
         details[:1000], dt.datetime.now(UTC).isoformat()),
    )


def process_discord_approval(
    data_dir: Path, command: str, user_id: str, channel_id: str,
    message_id: str, reply_to_message_id: str,
) -> Dict[str, Any]:
    """Authorize and apply a deterministic reply to a recorded approval DM."""
    allowed_user = os.environ.get("DISCORD_ALLOWED_USERS", "").strip()
    if not allowed_user or str(user_id) != allowed_user:
        return {"success": False, "error": "Discord user is not authorized"}
    match = re.fullmatch(r"(APPROVE|DENY)(?: +(ALL))? +(new-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}|rec-[0-9a-f]{16})", command.strip(), re.I)
    if not match:
        return {"success": False, "error": "use APPROVE ALL <batch_id>, DENY ALL <batch_id>, APPROVE <recommendation_id>, or DENY <recommendation_id>"}
    decision, all_marker, target = match.group(1).lower(), match.group(2), match.group(3)
    connection = open_state(data_dir)
    _ensure_tables(connection)
    if target.startswith("rec-"):
        batch_row = connection.execute(
            "SELECT batch_id FROM management_recommendations WHERE recommendation_id = ?", (target,)
        ).fetchone()
        if not batch_row:
            connection.close(); return {"success": False, "error": "recommendation was not found"}
        batch_id = str(batch_row[0])
    else:
        batch_id = target
    request = connection.execute(
        "SELECT discord_channel_id,discord_message_id,expires_at_utc,status FROM management_approval_requests WHERE batch_id = ?",
        (batch_id,),
    ).fetchone()
    if not request:
        connection.close(); return {"success": False, "error": "reply must target the matching approval DM"}
    approval_message_ids = {item for item in str(request[1]).split(",") if item}
    if str(request[0]) != str(channel_id) or str(reply_to_message_id) not in approval_message_ids:
        connection.close(); return {"success": False, "error": "reply must target the matching approval DM"}
    if (str(request[2]) and _parse_cursor(str(request[2])) <= dt.datetime.now(UTC)) or str(request[3]) != "open":
        connection.close(); return {"success": False, "error": "approval request is expired or closed"}
    if all_marker and target.startswith("rec-"):
        connection.close(); return {"success": False, "error": "ALL requires a batch ID"}
    rows = connection.execute(
        "SELECT recommendation_id,source,message_id,action,category,reason,target,status FROM management_recommendations "
        "WHERE batch_id = ? AND status = 'pending'" + ("" if all_marker else " AND recommendation_id = ?"),
        (batch_id,) if all_marker else (batch_id, target),
    ).fetchall()
    if not rows:
        connection.close(); return {"success": False, "error": "no pending recommendation matched"}
    results = []
    for rec_id, source, provider_id, action, category, reason, target_url, status in rows:
        if decision == "deny":
            connection.execute("UPDATE management_recommendations SET status='denied' WHERE recommendation_id = ?", (rec_id,))
            _audit(connection, batch_id, rec_id, "decision", "denied", str(user_id), str(message_id), str(reply_to_message_id), "explicit denial")
            results.append({"recommendation_id": rec_id, "status": "denied"})
            continue
        if not _mutation_enabled():
            connection.execute("UPDATE management_recommendations SET status='approved_dry_run' WHERE recommendation_id = ?", (rec_id,))
            _audit(connection, batch_id, rec_id, "decision", "approved_dry_run", str(user_id), str(message_id), str(reply_to_message_id), "approval recorded while mutations are disabled")
            results.append({"recommendation_id": rec_id, "status": "approved_dry_run"})
            continue
        try:
            apply_action(str(source), str(provider_id), str(action), str(category), data_dir, str(target_url or ""))
        except (MailActionError, OSError) as exc:
            detail = str(exc)[:200]
            connection.execute("UPDATE management_recommendations SET status='failed' WHERE recommendation_id = ?", (rec_id,))
            _audit(connection, batch_id, rec_id, "mutation", "failed", str(user_id), str(message_id), str(reply_to_message_id), detail)
            results.append({"recommendation_id": rec_id, "status": "failed", "error": detail})
        else:
            connection.execute("UPDATE management_recommendations SET status='applied' WHERE recommendation_id = ?", (rec_id,))
            _audit(connection, batch_id, rec_id, "mutation", "applied", str(user_id), str(message_id), str(reply_to_message_id), reason)
            results.append({"recommendation_id": rec_id, "status": "applied"})
    remaining = connection.execute("SELECT count(*) FROM management_recommendations WHERE batch_id = ? AND status = 'pending'", (batch_id,)).fetchone()[0]
    if not remaining:
        connection.execute("UPDATE management_approval_requests SET status='closed' WHERE batch_id = ?", (batch_id,))
    connection.commit(); connection.close()
    return {"success": True, "batch_id": batch_id, "decision": decision, "results": results, "remaining_pending": remaining}


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
        return {"success": False, "error": "action is not enabled; delete, trash, send, and arbitrary read actions are unavailable"}
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
    if str(batch[0]) and _parse_cursor(str(batch[0])) <= dt.datetime.now(UTC):
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

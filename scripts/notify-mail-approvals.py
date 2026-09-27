#!/usr/bin/env python3
"""Send a separate, auditable Discord DM for new-mail mutation approvals."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("PERSONAL_ASSISTANT_DATA_DIR", "/run/personal-assistant-tmp"))
API = "https://discord.com/api/v10"
MAX_LENGTH = 1900


def _compact(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _action_label(item: Dict[str, Any]) -> str:
    action = _compact(item.get("action"), 40)
    category = _compact(item.get("category"), 60)
    if action == "label" and category:
        return f'Add “{category}” label'
    return {
        "archive": "Archive",
        "spam": "Mark as spam",
        "unsubscribe": "Unsubscribe",
    }.get(action, action.title() or "Review")


def _reason(value: Any) -> str:
    text = _compact(value, 130)
    match = re.search(r"as ([^.]+)\.$", text)
    if text.startswith("Classified from sender, subject, and a bounded body excerpt") and match:
        return f"This message appears to relate to {match.group(1)}."
    return text or "Review recommended."


def _post(channel_id: str, token: str, content: str) -> str:
    request = urllib.request.Request(
        f"{API}/channels/{channel_id}/messages",
        data=json.dumps({"content": content}, ensure_ascii=False).encode(),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PersonalAssistant/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
            value = json.loads(response.read(128 * 1024).decode())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise RuntimeError("Discord approval notification failed") from exc
    message_id = str(value.get("id") or "") if isinstance(value, dict) else ""
    if not message_id:
        raise RuntimeError("Discord approval notification returned no message ID")
    return message_id


def _load_plugin() -> Any:
    directory = ROOT / ".hermes/plugins/personal-assistant-mail"
    spec = importlib.util.spec_from_file_location(
        "personal_assistant_mail_approval_delivery",
        directory / "__init__.py",
        submodule_search_locations=[str(directory)],
    )
    if not spec or not spec.loader:
        raise RuntimeError("mail plugin is unavailable")
    import sys
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def notify(review: Dict[str, Any], data_dir: Path) -> Dict[str, Any]:
    batch_id = str(review.get("batch_id") or "")
    recommendations = review.get("recommendations") or []
    if not batch_id or not recommendations:
        return {"sent": False, "reason": "no approval recommendations"}
    runtime = json.loads((data_dir / "credentials/discord-runtime.json").read_text(encoding="utf-8"))
    channel_id = str(runtime.get("dm_channel_id") or "")
    token = (data_dir / "credentials/discord-bot-token").read_text(encoding="utf-8").strip()
    if not channel_id or not token:
        raise RuntimeError("Discord DM runtime is not configured")
    lines = [
        "🔐 **Mail actions need your approval**",
        f"{len(recommendations)} suggested action{'s' if len(recommendations) != 1 else ''}. Nothing will change unless you approve it.",
        "",
    ]
    for index, item in enumerate(recommendations, start=1):
        recommendation_id = _compact(item.get("recommendation_id"), 60)
        sender = _compact(item.get("sender") or "Unknown sender", 90)
        subject = _compact(item.get("subject") or "(no subject)", 120)
        reason = _reason(item.get("reason"))
        lines.extend([
            f"{index}. **{_action_label(item)}**",
            f"   {sender} — {subject}",
            f"   Why: {reason}",
            f"   Approve: `APPROVE {recommendation_id}` · Reject: `DENY {recommendation_id}`",
            "",
        ])
    lines.extend([
        f"Approve all: `APPROVE ALL {batch_id}`",
        f"Reject all remaining: `DENY ALL {batch_id}`",
        "Reply to this message with your decision.",
    ])
    text = "\n".join(lines)
    chunks = [text[index:index + MAX_LENGTH] for index in range(0, len(text), MAX_LENGTH)]
    message_ids = [_post(channel_id, token, chunks[0])]
    for chunk in chunks[1:]:
        message_ids.append(_post(channel_id, token, chunk))
    plugin = _load_plugin()
    # Bind every continuation to the same approval request so a user can
    # reply to the item they actually see, not only the first chunk.
    plugin.mail_management.record_approval_request(
        data_dir, batch_id, channel_id, ",".join(message_ids), ""
    )
    return {"sent": True, "batch_id": batch_id, "message_id": message_ids[0], "message_ids": message_ids, "chunks": len(chunks)}


def main() -> int:
    payload = json.loads(os.environ.get("PDA_APPROVAL_JSON", "{}"))
    print(json.dumps(notify(payload, DATA_DIR), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

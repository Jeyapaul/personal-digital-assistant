#!/usr/bin/env python3
"""Probe the local LM Studio OpenAI-compatible model endpoint.

This performs only a bounded GET request. It does not send email content or
model prompts and does not modify Hermes configuration.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


ENDPOINTS = {
    "lmstudio": os.getenv("LM_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/"),
}


def probe(name: str, base_url: str) -> dict:
    url = f"{base_url}/models"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read(256 * 1024).decode("utf-8"))
        models = payload.get("data", []) if isinstance(payload, dict) else []
        ids = [m.get("id") for m in models if isinstance(m, dict) and m.get("id")]
        return {"provider": name, "base_url": base_url, "reachable": True, "models": ids}
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"provider": name, "base_url": base_url, "reachable": False, "error": str(exc)}


if __name__ == "__main__":
    print(json.dumps([probe(name, url) for name, url in ENDPOINTS.items()], indent=2))

#!/usr/bin/env python3
"""Manage the explicit HTTPS unsubscribe host allowlist.

Hosts are operator-approved configuration, never derived automatically from
email content. Restart/recreate the egress proxy after changing this file.
"""
from __future__ import annotations

import argparse
import re
import stat
from pathlib import Path

HOST_RE = re.compile(r"(?=^.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z", re.I)


def path() -> Path:
    import os
    data = Path(os.environ.get("PERSONAL_ASSISTANT_DATA_DIR", str(Path.home() / ".hermes/personal-assistant-data")))
    return data / "config/unsubscribe-hosts.txt"


def read(target: Path) -> list[str]:
    if not target.exists():
        return []
    return sorted({line.strip().lower().lstrip(".") for line in target.read_text().splitlines() if line.strip()})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["list", "add", "remove"])
    parser.add_argument("host", nargs="?")
    args = parser.parse_args()
    target = path()
    hosts = read(target)
    if args.action != "list":
        if not args.host or not HOST_RE.fullmatch(args.host):
            raise SystemExit("host must be a DNS hostname, not a URL or wildcard")
        host = args.host.lower().lstrip(".")
        if args.action == "add":
            hosts = sorted(set(hosts) | {host})
        else:
            hosts = [item for item in hosts if item != host]
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_text("".join(item + "\n" for item in hosts), encoding="utf-8")
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print("\n".join(hosts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

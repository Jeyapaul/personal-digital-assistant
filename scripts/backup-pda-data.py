#!/usr/bin/env python3
"""Create an encrypted, authenticated backup of the private PDA data directory."""

from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import os
import secrets
import struct
import tarfile
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"PDA-BACKUP-1\0"
SALT_BYTES = 16
NONCE_BYTES = 12


def _password() -> bytes:
    value = os.environ.get("PDA_BACKUP_PASSWORD")
    if value is None:
        value = getpass.getpass("PDA backup password: ")
    if len(value) < 16:
        raise SystemExit("PDA_BACKUP_PASSWORD must contain at least 16 characters")
    return value.encode("utf-8")


def _key(password: bytes, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password)


def main() -> int:
    data_dir = Path(os.environ.get(
        "PERSONAL_ASSISTANT_DATA_DIR",
        str(Path.home() / ".hermes/personal-assistant-data"),
    )).expanduser().resolve()
    if not data_dir.is_dir():
        raise SystemExit(f"data directory does not exist: {data_dir}")
    destination = Path(os.environ.get(
        "PDA_BACKUP_DIR", str(data_dir.parent / "pda-backups")
    )).expanduser().resolve()
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.chmod(0o700)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = destination / f"personal-assistant-{timestamp}.tar.gz.pda"
    password = _password()
    salt = secrets.token_bytes(SALT_BYTES)
    nonce = secrets.token_bytes(NONCE_BYTES)

    with tempfile.NamedTemporaryFile(prefix="pda-backup-", suffix=".tar.gz", dir=destination, delete=False) as archive:
        archive_path = Path(archive.name)
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(data_dir, arcname="personal-assistant-data", recursive=True)
        compressed = archive_path.read_bytes()
        ciphertext = AESGCM(_key(password, salt)).encrypt(nonce, compressed, MAGIC)
        payload = MAGIC + struct.pack("!B", len(salt)) + salt + nonce + ciphertext
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.chmod(0o600)
        temporary.replace(output)
    finally:
        archive_path.unlink(missing_ok=True)

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"Created encrypted backup: {output}")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

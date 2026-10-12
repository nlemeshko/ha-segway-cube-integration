#!/usr/bin/env python3
"""Read only Segway's preferences from an unencrypted iPhone backup or plist.

Never uploads data. Does not decrypt encrypted backups. Prints candidate keys
locally, or saves the selected key to a private file with --output.
"""

import argparse
import json
import os
import plistlib
import sqlite3
from pathlib import Path


def load_preferences(source: Path) -> dict:
    if source.is_file():
        return plistlib.loads(source.read_bytes())
    manifest = source / "Manifest.plist"
    if manifest.exists() and plistlib.loads(manifest.read_bytes()).get("IsEncrypted"):
        raise ValueError("Use an unencrypted Finder backup; this tool does not decrypt backups")
    database = source / "Manifest.db"
    if not database.exists():
        raise ValueError("Select an iPhone backup directory containing Manifest.db, or the Segway plist")
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT fileID FROM Files WHERE domain = ? AND relativePath = ?",
            ("AppDomain-com.ninebot.segway", "Library/Preferences/com.ninebot.segway.plist"),
        ).fetchall()
    if len(rows) != 1:
        raise ValueError("Segway preferences are missing from this backup")
    file_id = rows[0][0]
    candidate = source / file_id[:2] / file_id
    if not candidate.is_file():
        candidate = source / file_id
    return plistlib.loads(candidate.read_bytes())


def keys(preferences: dict, serial: str | None):
    result = {}
    for name, value in preferences.items():
        if not name.endswith("_decrypt") or (serial and name != serial + "_decrypt"):
            continue
        if isinstance(value, bytes) and len(value) == 16:
            key = value.hex()
        elif isinstance(value, str):
            try:
                raw = bytes.fromhex(value)
            except ValueError:
                continue
            if len(raw) != 16:
                continue
            key = raw.hex()
        else:
            continue
        result[name.removesuffix("_decrypt")] = key
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Unencrypted backup directory or com.ninebot.segway.plist")
    parser.add_argument("--serial", help="Select the Cube's exact serial number")
    parser.add_argument("--output", type=Path, help="Save selected key privately, instead of printing it")
    args = parser.parse_args()
    try:
        found = keys(load_preferences(args.source), args.serial)
        if not found:
            raise ValueError("No 16-byte _decrypt key found for this station")
        if args.output:
            if len(found) != 1:
                raise ValueError("Use --serial when multiple devices have keys")
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as target:
                json.dump({"serial": next(iter(found)), "password": next(iter(found.values()))}, target)
            print("Selected key saved to a private file")
        else:
            for serial, key in found.items():
                print(f"{serial}: {key}")
            print("Candidate keys must be validated by the integration's AUTH handshake.")
    except (ValueError, OSError, sqlite3.Error, plistlib.InvalidFileException) as err:
        parser.exit(1, f"{err}\n")


if __name__ == "__main__":
    main()

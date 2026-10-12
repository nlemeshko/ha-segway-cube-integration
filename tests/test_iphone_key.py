import importlib.util
import plistlib
import sqlite3
from pathlib import Path

import pytest

tool = Path(__file__).resolve().parents[1] / "tools" / "extract_iphone_key.py"
spec = importlib.util.spec_from_file_location("extract_iphone_key", tool)
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)


def test_extracts_only_matching_segway_key():
    prefs = {"CUBE123_decrypt": "ab" * 16, "OTHER_decrypt": bytes(16), "account_password": "not-a-ble-key"}
    assert extractor.keys(prefs, "CUBE123") == {"CUBE123": "ab" * 16}
    assert extractor.keys(prefs, "missing") == {}


def test_backup_reads_only_segway_plist(tmp_path):
    file_id = "ab" + "0" * 38
    target = tmp_path / "ab" / file_id
    target.parent.mkdir()
    target.write_bytes(plistlib.dumps({"CUBE_decrypt": bytes(range(16))}))
    with sqlite3.connect(tmp_path / "Manifest.db") as conn:
        conn.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT)")
        conn.execute(
            "INSERT INTO Files VALUES (?, ?, ?)",
            (file_id, "AppDomain-com.ninebot.segway", "Library/Preferences/com.ninebot.segway.plist"),
        )
        conn.execute("INSERT INTO Files VALUES (?, ?, ?)", ("unrelated", "OtherDomain", "private.plist"))
    assert extractor.keys(extractor.load_preferences(tmp_path), "CUBE") == {"CUBE": bytes(range(16)).hex()}


def test_encrypted_backup_is_not_read(tmp_path):
    (tmp_path / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": True}))
    with pytest.raises(ValueError, match="unencrypted"):
        extractor.load_preferences(tmp_path)

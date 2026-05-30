import logging
from datetime import date
from unittest.mock import patch

import pytest

from app import config


@pytest.fixture(autouse=True)
def _cleanup_file_handlers():
    root = logging.getLogger()
    old_level = root.level
    yield
    root.setLevel(old_level)
    for h in list(root.handlers):
        if isinstance(h, logging.FileHandler):
            root.removeHandler(h)
            h.close()


def test_skips_when_log_output_dir_unset(monkeypatch):
    monkeypatch.delenv("LOG_OUTPUT_DIR", raising=False)
    assert config.add_file_handler("run-1") is False


def test_creates_jsonl_under_date_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_OUTPUT_DIR", str(tmp_path))
    assert config.add_file_handler("run-test") is True

    expected = tmp_path / date.today().isoformat() / "run-test.jsonl"
    assert expected.exists()

    # 追加ハンドラに書いたログが JSON で残ること
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger("config").info("[TEST] hello")
    content = expected.read_text(encoding="utf-8")
    assert "hello" in content


def test_skips_on_oserror_without_crashing(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_OUTPUT_DIR", str(tmp_path))
    with patch("app.config.Path.mkdir", side_effect=OSError("permission denied")):
        assert config.add_file_handler("run-2") is False


# --- Windows パス入力の unix 解決（サンドボックス動的マウント対応） ---

def test_sharepoint_root_resolves_windows_path(monkeypatch, tmp_path):
    monkeypatch.setattr("app.mounts.discover_maps", lambda raw, self_path=None: [(str(tmp_path), "C:\\sp")])
    monkeypatch.setenv("SHAREPOINT_ROOT", "C:\\sp\\案件")
    assert config.settings.sharepoint_root == str(tmp_path / "案件")


def test_sharepoint_root_passthrough_unix_path(monkeypatch, tmp_path):
    monkeypatch.setattr("app.mounts.discover_maps", lambda raw, self_path=None: [])
    monkeypatch.setenv("SHAREPOINT_ROOT", str(tmp_path))
    assert config.settings.sharepoint_root == str(tmp_path)


# --- GOOGLE_APPLICATION_CREDENTIALS の正規化 ---

def test_normalize_credentials_unset_returns_none(monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    assert config.normalize_google_credentials() is None


def test_normalize_credentials_windows_path_resolved(monkeypatch, tmp_path):
    key = tmp_path / "linetask-puller.json"
    key.write_text("{}")
    monkeypatch.setattr("app.mounts.discover_maps", lambda raw, self_path=None: [(str(tmp_path), "C:\\secrets")])
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "C:\\secrets\\linetask-puller.json")
    resolved = config.normalize_google_credentials()
    assert resolved == str(key)
    # google ライブラリが読む os.environ も書き換わっていること
    import os
    assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == str(key)


def test_normalize_credentials_unix_path_passthrough(monkeypatch, tmp_path):
    key = tmp_path / "k.json"
    key.write_text("{}")
    monkeypatch.setattr("app.mounts.discover_maps", lambda raw, self_path=None: [])
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(key))
    assert config.normalize_google_credentials() == str(key)

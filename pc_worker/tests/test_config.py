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

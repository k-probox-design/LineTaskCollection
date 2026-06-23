import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from app import config, tray_writer
from app.cli import app

runner = CliRunner()


# --- build_tray_record -------------------------------------------------------

def _meta(**over):
    # pull._doc_to_meta の実出力キーに合わせた既定メタ
    base = {
        "doc_id": "DOC1",
        "type": "file",
        "group_id": "Cgrp",
        "timestamp": "2026-05-30T03:30:00+00:00",  # UTC ISO（_doc_to_meta は receivedAt をこのキーで出す）
        "file_name": "見積書_山田様.pdf",
        "group_name": "姫路農場グループ",
        "sender_display_name": "山田",
    }
    base.update(over)
    return base


def test_build_record_basic_mapping():
    rec = tray_writer.build_tray_record(_meta(), case="佐藤邸")
    assert rec["source"] == "LINE"
    assert rec["source_id"] == "DOC1"
    assert rec["依頼主"] == "山田"
    assert rec["内容"] == "LINE資料受領: 見積書_山田様.pdf"
    assert rec["案件"] == "佐藤邸"
    assert rec["場所"] == "姫路農場グループ"
    assert rec["期限"] == ""
    assert rec["要対応"] == "△"
    assert rec["添付"] == []
    assert rec["link"] == "#"
    assert "会話ログ" not in rec


def test_build_record_received_converted_to_jst():
    # 03:30 UTC -> 12:30 JST
    rec = tray_writer.build_tray_record(_meta())
    assert rec["受信"] == "2026/05/30 12:30"


def test_build_record_received_unparsable_is_empty():
    rec = tray_writer.build_tray_record(_meta(timestamp="not-a-date"))
    assert rec["受信"] == ""


def test_build_record_needs_review_marks_double_circle():
    rec = tray_writer.build_tray_record(_meta(), needs_review=True)
    assert rec["要対応"] == "◎"


def test_build_record_content_never_empty_text_only():
    # ファイル無し・text のみ → text 先頭を内容に（改行は空白化）
    meta = _meta(type="text", text="図面の\n変更を\nお願いします" + "あ" * 50)
    del meta["file_name"]
    rec = tray_writer.build_tray_record(meta)
    assert rec["内容"]
    assert "\n" not in rec["内容"]
    assert len(rec["内容"]) <= 40


def test_build_record_content_fallback_when_no_file_no_text():
    meta = _meta(type="text")
    del meta["file_name"]
    rec = tray_writer.build_tray_record(meta)
    assert rec["内容"] == "LINE受信: DOC1"


def test_build_record_attachment_basename_and_link():
    win = r"C:\Users\knaka\OneDrive\案件\佐藤邸\09.LINEやりとり資料\2026-05-30 見積.pdf"
    rec = tray_writer.build_tray_record(_meta(), placed_file_windows=win)
    assert rec["添付"] == ["2026-05-30 見積.pdf"]
    assert rec["link"] == win


def test_build_record_conversation_log_present_when_given():
    rec = tray_writer.build_tray_record(_meta(), conversation_text="[12:00] 山田: こんにちは")
    assert rec["会話ログ"] == "[12:00] 山田: こんにちは"


def test_build_record_accepts_alternate_key_names():
    # list_messages / 生 Firestore 由来のキー名も吸収する
    meta = {
        "message_id": "DOC9",
        "received_at": "2026-05-30T03:30:00+00:00",
        "text": "テキスト本文のみ",
        "groupName": "別グループ",
        "senderDisplayName": "佐藤",
    }
    rec = tray_writer.build_tray_record(meta)
    assert rec["source_id"] == "DOC9"
    assert rec["依頼主"] == "佐藤"
    assert rec["場所"] == "別グループ"
    assert rec["受信"] == "2026/05/30 12:30"
    assert rec["内容"] == "テキスト本文のみ"


def test_build_record_missing_optional_fields_default_empty():
    rec = tray_writer.build_tray_record({"doc_id": "DOC2"})
    assert rec["依頼主"] == ""
    assert rec["場所"] == ""
    assert rec["受信"] == ""
    assert rec["内容"] == "LINE受信: DOC2"


# --- write_tray_file ---------------------------------------------------------

def test_write_tray_file_writes_utf8_roundtrip(tmp_path):
    rec = tray_writer.build_tray_record(_meta(), case="佐藤邸")
    dest = tray_writer.write_tray_file(rec, tmp_path)
    assert dest == tmp_path / "LINE_DOC1.json"
    assert dest.exists()
    # BOM 無し UTF-8
    raw = dest.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert loaded["依頼主"] == "山田"
    assert loaded["内容"] == "LINE資料受領: 見積書_山田様.pdf"
    assert loaded["案件"] == "佐藤邸"


def test_write_tray_file_creates_missing_dir(tmp_path):
    out = tmp_path / "nested" / "tray"
    rec = tray_writer.build_tray_record(_meta())
    dest = tray_writer.write_tray_file(rec, out)
    assert dest.parent == out
    assert dest.exists()


# --- send-to-tray (CLI) ------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_logging():
    def _clear():
        config._configured = False
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()

    _clear()
    yield
    _clear()


def _stdout_json(result):
    return json.loads(result.stdout)


def _stderr_json(result):
    lines = [ln for ln in result.stderr.strip().splitlines() if ln.strip()]
    return json.loads(lines[-1])


def test_send_to_tray_writes_json(tmp_path):
    meta = _meta()
    with patch("app.cli.pull.get_meta", return_value=meta) as m_get:
        result = runner.invoke(app, [
            "send-to-tray", "--doc-id", "DOC1", "--case", "佐藤邸", "--out-dir", str(tmp_path),
        ])
    assert result.exit_code == 0, result.stderr
    m_get.assert_called_once_with("DOC1")
    data = _stdout_json(result)
    assert data["source_id"] == "DOC1"
    out = tmp_path / "LINE_DOC1.json"
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["案件"] == "佐藤邸"
    assert loaded["要対応"] == "△"
    assert "会話ログ" not in loaded


def test_send_to_tray_with_conversation(tmp_path):
    meta = _meta()
    convo = [
        {"received_at": "2026-05-30T03:00:00+00:00", "sender_display_name": "山田", "text": "資料送ります"},
        {"received_at": "2026-05-30T03:30:00+00:00", "sender_display_name": "山田", "file_name": "見積.pdf"},
    ]
    with patch("app.cli.pull.get_meta", return_value=meta), \
         patch("app.cli.pull.list_messages", return_value=convo) as m_list:
        result = runner.invoke(app, [
            "send-to-tray", "--doc-id", "DOC1", "--with-conversation",
            "--window-hours", "24", "--out-dir", str(tmp_path),
        ])
    assert result.exit_code == 0, result.stderr
    assert m_list.call_args.kwargs["around_doc"] == "DOC1"
    assert m_list.call_args.kwargs["window_hours"] == 24
    loaded = json.loads((tmp_path / "LINE_DOC1.json").read_text(encoding="utf-8"))
    assert "会話ログ" in loaded
    assert "山田: 資料送ります" in loaded["会話ログ"]
    assert "山田: 見積.pdf" in loaded["会話ログ"]


def test_send_to_tray_needs_review_flag(tmp_path):
    with patch("app.cli.pull.get_meta", return_value=_meta()):
        result = runner.invoke(app, [
            "send-to-tray", "--doc-id", "DOC1", "--needs-review", "--out-dir", str(tmp_path),
        ])
    assert result.exit_code == 0, result.stderr
    loaded = json.loads((tmp_path / "LINE_DOC1.json").read_text(encoding="utf-8"))
    assert loaded["要対応"] == "◎"


def test_send_to_tray_uses_settings_tray_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAY_DIR", str(tmp_path))
    with patch("app.cli.pull.get_meta", return_value=_meta()):
        result = runner.invoke(app, ["send-to-tray", "--doc-id", "DOC1"])
    assert result.exit_code == 0, result.stderr
    assert (tmp_path / "LINE_DOC1.json").exists()


def test_send_to_tray_fails_without_tray_dir(monkeypatch):
    monkeypatch.delenv("TRAY_DIR", raising=False)
    with patch("app.cli.pull.get_meta", return_value=_meta()):
        result = runner.invoke(app, ["send-to-tray", "--doc-id", "DOC1"])
    assert result.exit_code != 0
    assert _stderr_json(result)["error"] == "tray dir not set"


def test_send_to_tray_get_meta_error(tmp_path):
    with patch("app.cli.pull.get_meta", side_effect=ValueError("document not found: X")):
        result = runner.invoke(app, ["send-to-tray", "--doc-id", "X", "--out-dir", str(tmp_path)])
    assert result.exit_code != 0
    assert _stderr_json(result)["error"] == "send-to-tray failed"

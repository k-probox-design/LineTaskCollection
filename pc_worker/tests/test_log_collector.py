import json
import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from app import config, log_collector, pull
from app.cli import app

runner = CliRunner()


# --- sanitize_filename -------------------------------------------------------

def test_sanitize_filename_replaces_forbidden_chars():
    assert log_collector.sanitize_filename('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"


def test_sanitize_filename_empty_and_blank_become_unknown():
    assert log_collector.sanitize_filename("") == "unknown"
    assert log_collector.sanitize_filename("   ") == "unknown"


def test_sanitize_filename_replaces_control_chars():
    assert log_collector.sanitize_filename("a\tb\nc") == "a_b_c"


def test_sanitize_filename_strips_surrounding_dots_and_space():
    assert log_collector.sanitize_filename("  .姫路農場.  ") == "姫路農場"


# --- format_log_line ---------------------------------------------------------

def test_format_log_line_text_jst_conversion():
    entry = {
        "received_at": "2026-06-22T08:15:00+00:00",
        "sender_display_name": "田中太郎",
        "message_type": "text",
        "text": "○○邸の配線写真を確認してほしい",
    }
    assert log_collector.format_log_line(entry) == "- 2026/06/22 17:15 田中太郎: ○○邸の配線写真を確認してほしい"


def test_format_log_line_missing_type_treated_as_text():
    entry = {"received_at": "2026-06-22T08:15:00+00:00", "sender_display_name": "田中", "text": "本文"}
    assert log_collector.format_log_line(entry) == "- 2026/06/22 17:15 田中: 本文"


def test_format_log_line_image_label_with_file():
    entry = {"received_at": "2026-06-22T08:15:00+00:00", "sender_display_name": "田中",
             "message_type": "image", "file_name": "photo.jpg"}
    assert log_collector.format_log_line(entry) == "- 2026/06/22 17:15 田中: [画像] photo.jpg"


def test_format_log_line_file_label():
    entry = {"received_at": "2026-06-22T08:15:00+00:00", "sender_display_name": "田中",
             "message_type": "file", "file_name": "見積.pdf"}
    assert log_collector.format_log_line(entry) == "- 2026/06/22 17:15 田中: [ファイル] 見積.pdf"


def test_format_log_line_video_audio_other_labels():
    base = {"received_at": "2026-06-22T08:15:00+00:00", "sender_display_name": "田中"}
    assert "[動画]" in log_collector.format_log_line({**base, "message_type": "video"})
    assert "[音声]" in log_collector.format_log_line({**base, "message_type": "audio"})
    assert "[その他]" in log_collector.format_log_line({**base, "message_type": "sticker"})


def test_format_log_line_label_without_file_name():
    entry = {"received_at": "2026-06-22T08:15:00+00:00", "sender_display_name": "田中", "message_type": "image"}
    assert log_collector.format_log_line(entry) == "- 2026/06/22 17:15 田中: [画像]"


def test_format_log_line_missing_sender_is_fuhmei():
    entry = {"received_at": "2026-06-22T08:15:00+00:00", "message_type": "text", "text": "x"}
    assert "不明:" in log_collector.format_log_line(entry)


def test_format_log_line_newlines_flattened():
    entry = {"received_at": "2026-06-22T08:15:00+00:00", "sender_display_name": "田中",
             "message_type": "text", "text": "一行目\n二行目\n三行目"}
    line = log_collector.format_log_line(entry)
    assert "\n" not in line
    assert "一行目 二行目 三行目" in line


def test_format_log_line_blank_time_does_not_raise():
    entry = {"received_at": None, "sender_display_name": "田中", "message_type": "text", "text": "本文"}
    line = log_collector.format_log_line(entry)
    assert "田中: 本文" in line
    assert line.startswith("- ")


# --- append_entries ----------------------------------------------------------

def _e(gid, received, **over):
    base = {"group_id": gid, "received_at": received, "sender_display_name": "田中",
            "message_type": "text", "text": "本文"}
    base.update(over)
    return base


def test_append_entries_new_file_has_header_first(tmp_path):
    entries = [_e("G1", "2026-06-22T08:00:00+00:00", text="最初")]
    log_collector.append_entries(tmp_path, entries, lambda gid: {"G1": "姫路農場"}.get(gid))
    md = (tmp_path / "姫路農場.md").read_text(encoding="utf-8")
    lines = md.splitlines()
    assert lines[0] == "# LINE会話ログ: 姫路農場 (groupId: G1)"
    assert "最初" in lines[1]


def test_append_entries_appends_without_truncating(tmp_path):
    resolve = lambda gid: {"G1": "姫路農場"}.get(gid)
    log_collector.append_entries(tmp_path, [_e("G1", "2026-06-22T08:00:00+00:00", text="一回目")], resolve)
    first = (tmp_path / "姫路農場.md").read_text(encoding="utf-8")
    log_collector.append_entries(tmp_path, [_e("G1", "2026-06-22T09:00:00+00:00", text="二回目")], resolve)
    second = (tmp_path / "姫路農場.md").read_text(encoding="utf-8")
    assert second.startswith("# LINE会話ログ: 姫路農場")
    assert "一回目" in second and "二回目" in second
    assert len(second.splitlines()) > len(first.splitlines())


def test_append_entries_two_groups_separate_files(tmp_path):
    resolve = lambda gid: {"G1": "姫路農場", "G2": "佐藤邸"}.get(gid)
    entries = [_e("G1", "2026-06-22T08:00:00+00:00"), _e("G2", "2026-06-22T08:00:00+00:00")]
    log_collector.append_entries(tmp_path, entries, resolve)
    assert (tmp_path / "姫路農場.md").exists()
    assert (tmp_path / "佐藤邸.md").exists()


def test_append_entries_utf8_roundtrip(tmp_path):
    entries = [_e("G1", "2026-06-22T08:00:00+00:00", text="日本語テスト○○邸")]
    log_collector.append_entries(tmp_path, entries, lambda gid: "姫路農場")
    raw = (tmp_path / "姫路農場.md").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "日本語テスト○○邸" in raw.decode("utf-8")


def test_append_entries_sorts_by_received_at(tmp_path):
    entries = [
        _e("G1", "2026-06-22T10:00:00+00:00", text="三番"),
        _e("G1", "2026-06-22T08:00:00+00:00", text="一番"),
        _e("G1", "2026-06-22T09:00:00+00:00", text="二番"),
    ]
    log_collector.append_entries(tmp_path, entries, lambda gid: "姫路農場")
    body = (tmp_path / "姫路農場.md").read_text(encoding="utf-8")
    assert body.index("一番") < body.index("二番") < body.index("三番")


def test_append_entries_uses_group_id_when_name_none(tmp_path):
    entries = [_e("Gunknown", "2026-06-22T08:00:00+00:00")]
    log_collector.append_entries(tmp_path, entries, lambda gid: None)
    path = tmp_path / "Gunknown.md"
    assert path.exists()
    assert "groupId: Gunknown" in path.read_text(encoding="utf-8")


def test_append_entries_return_value(tmp_path):
    resolve = lambda gid: {"G1": "姫路農場", "G2": "佐藤邸"}.get(gid)
    entries = [
        _e("G1", "2026-06-22T08:00:00+00:00"),
        _e("G1", "2026-06-22T09:00:00+00:00"),
        _e("G2", "2026-06-22T08:00:00+00:00"),
    ]
    result = log_collector.append_entries(tmp_path, entries, resolve)
    assert result["appended"] == 3
    assert result["groups"] == {"姫路農場": 2, "佐藤邸": 1}
    assert len(result["files"]) == 2
    assert all(str(tmp_path) in f for f in result["files"])


# --- read_state / write_state ------------------------------------------------

def test_state_roundtrip(tmp_path):
    log_collector.write_state(tmp_path, {"last_received": "2026-06-22T08:00:00+00:00"})
    assert log_collector.read_state(tmp_path) == {"last_received": "2026-06-22T08:00:00+00:00"}


def test_read_state_missing_returns_empty(tmp_path):
    assert log_collector.read_state(tmp_path) == {}


def test_read_state_broken_json_returns_empty(tmp_path):
    (tmp_path / ".collect_state.json").write_text("{not valid", encoding="utf-8")
    assert log_collector.read_state(tmp_path) == {}


def test_write_state_creates_dir(tmp_path):
    out = tmp_path / "nested" / "logs"
    log_collector.write_state(out, {"last_received": "x"})
    assert (out / ".collect_state.json").exists()


# --- list_since (Firestore mock) ---------------------------------------------

def _doc(doc_id, received, **fields):
    d = MagicMock()
    d.id = doc_id
    d.to_dict.return_value = {"groupId": "Cgrp", "receivedAt": received, **fields}
    return d


def _utc(y, mo, da, h=0, mi=0):
    return datetime(y, mo, da, h, mi, tzinfo=timezone.utc)


def test_list_since_none_uses_order_by_limit():
    docs = [_doc("a", _utc(2026, 6, 22, 8, 0), type="text", text="x")]
    client = MagicMock()
    client.collection.return_value.order_by.return_value.limit.return_value.stream.return_value = iter(docs)
    with patch("app.pull._firestore", return_value=client):
        out = pull.list_since(None, limit=500)
    client.collection.return_value.order_by.assert_called_once_with("receivedAt")
    client.collection.return_value.order_by.return_value.limit.assert_called_once_with(500)
    assert out[0]["doc_id"] == "a"


def test_list_since_with_cursor_uses_where_filter():
    docs = [_doc("b", _utc(2026, 6, 22, 9, 0), type="text", text="y")]
    client = MagicMock()
    where_chain = client.collection.return_value.where.return_value
    where_chain.order_by.return_value.limit.return_value.stream.return_value = iter(docs)
    with patch("app.pull._firestore", return_value=client):
        out = pull.list_since("2026-06-22T08:00:00+00:00", limit=1000)
    assert client.collection.return_value.where.called
    call = client.collection.return_value.where.call_args
    flt = call.kwargs["filter"]
    assert flt.field_path == "receivedAt"
    assert flt.op_string == ">"
    assert out[0]["doc_id"] == "b"


# --- collect-logs (CLI) ------------------------------------------------------

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


def test_collect_logs_cli_writes_md_and_cursor(tmp_path):
    entries = [
        {"group_id": "G1", "received_at": "2026-06-22T08:15:00+00:00",
         "sender_display_name": "田中太郎", "message_type": "text", "text": "配線写真を確認してほしい"},
    ]
    with patch("app.cli.pull.list_since", return_value=entries), \
         patch("app.cli.pull._group_name", return_value="姫路農場"):
        result = runner.invoke(app, ["collect-logs", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stderr
    data = _stdout_json(result)
    assert data["appended"] == 1
    assert data["since"] is None
    assert data["new_cursor"] == "2026-06-22T08:15:00+00:00"
    md = (tmp_path / "姫路農場.md").read_text(encoding="utf-8")
    assert md.startswith("# LINE会話ログ: 姫路農場")
    assert "配線写真を確認してほしい" in md


def test_collect_logs_cli_empty_is_ok(tmp_path):
    with patch("app.cli.pull.list_since", return_value=[]), \
         patch("app.cli.pull._group_name", return_value=None):
        result = runner.invoke(app, ["collect-logs", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stderr
    data = _stdout_json(result)
    assert data["appended"] == 0
    assert data["files"] == []
    assert data["since"] is None
    assert data["new_cursor"] is None

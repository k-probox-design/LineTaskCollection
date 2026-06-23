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


def _ce(doc_id, gid, received, **over):
    """collect-logs 経由のエントリ（_msg_to_entry 相当＝必ず doc_id を持つ）。"""
    base = {"doc_id": doc_id, "group_id": gid, "received_at": received,
            "sender_display_name": "田中太郎", "message_type": "text", "text": "本文"}
    base.update(over)
    return base


def test_collect_logs_cli_writes_md_and_cursor(tmp_path):
    entries = [
        _ce("d1", "G1", "2026-06-22T08:15:00+00:00",
            sender_display_name="田中太郎", text="配線写真を確認してほしい"),
    ]
    # 初回 batch → 取り切り（len<limit）で 1 回で抜ける。
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
    # 境界 doc_id が state に保存される。
    state = log_collector.read_state(tmp_path)
    assert state["last_received"] == "2026-06-22T08:15:00+00:00"
    assert state["boundary_ids"] == ["d1"]


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


# --- list_since inclusive ----------------------------------------------------

def test_list_since_inclusive_uses_gte_filter():
    docs = [_doc("b", _utc(2026, 6, 22, 9, 0), type="text", text="y")]
    client = MagicMock()
    where_chain = client.collection.return_value.where.return_value
    where_chain.order_by.return_value.limit.return_value.stream.return_value = iter(docs)
    with patch("app.pull._firestore", return_value=client):
        out = pull.list_since("2026-06-22T09:00:00+00:00", limit=1000, inclusive=True)
    call = client.collection.return_value.where.call_args
    flt = call.kwargs["filter"]
    assert flt.field_path == "receivedAt"
    assert flt.op_string == ">="
    assert out[0]["doc_id"] == "b"


# --- collect-logs: 取りこぼし防止・冪等・ドレイン ---------------------------

def test_collect_logs_no_loss_at_limit_boundary(tmp_path):
    """同一 received_at が境界に複数あり limit で分割されても、全件が md に入る。"""
    t = "2026-06-22T08:00:00+00:00"
    t2 = "2026-06-22T09:00:00+00:00"
    # batch1: limit=2 ちょうど。末尾と同時刻(t)の doc が分割で次バッチに残る状況。
    batch1 = [_ce("d1", "G1", t, text="一"), _ce("d2", "G1", t, text="二")]
    # batch2: inclusive(>=t) で d2(既出=boundary) と、同時刻 t の取りこぼし d3、続く t2 の d4。
    batch2 = [_ce("d2", "G1", t, text="二"), _ce("d3", "G1", t, text="三"),
              _ce("d4", "G1", t2, text="四")]
    batch3 = [_ce("d4", "G1", t2, text="四")]  # inclusive(>=t2) で d4 のみ＝取り切り

    with patch("app.cli.pull.list_since", side_effect=[batch1, batch2, batch3]), \
         patch("app.cli.pull._group_name", return_value="姫路農場"):
        result = runner.invoke(app, ["collect-logs", "--out-dir", str(tmp_path), "--limit", "2"])
    assert result.exit_code == 0, result.stderr
    md = (tmp_path / "姫路農場.md").read_text(encoding="utf-8")
    # 取りこぼし d3 を含め d1〜d4 が全部入り、かつ重複しない。
    for needle in ("一", "二", "三", "四"):
        assert md.count(needle) == 1, f"{needle} の出現が想定外: {md.count(needle)}"
    data = _stdout_json(result)
    assert data["appended"] == 4


def test_collect_logs_drains_over_limit_in_one_call(tmp_path):
    """合計が limit 超でも 1 回の呼び出しで全部追記される（ドレイン）。"""
    b1 = [_ce("a1", "G1", "2026-06-22T08:00:00+00:00", text="A"),
          _ce("a2", "G1", "2026-06-22T08:30:00+00:00", text="B")]
    b2 = [_ce("a2", "G1", "2026-06-22T08:30:00+00:00", text="B"),  # boundary 再取得
          _ce("a3", "G1", "2026-06-22T09:00:00+00:00", text="C")]
    b3 = [_ce("a3", "G1", "2026-06-22T09:00:00+00:00", text="C")]  # 取り切り
    with patch("app.cli.pull.list_since", side_effect=[b1, b2, b3]) as m, \
         patch("app.cli.pull._group_name", return_value="姫路農場"):
        result = runner.invoke(app, ["collect-logs", "--out-dir", str(tmp_path), "--limit", "2"])
    assert result.exit_code == 0, result.stderr
    md = (tmp_path / "姫路農場.md").read_text(encoding="utf-8")
    for needle in ("A", "B", "C"):
        assert md.count(needle) == 1
    data = _stdout_json(result)
    assert data["appended"] == 3
    # 1 回の collect-logs 内で 3 回 list_since を呼んでドレインしている。
    assert m.call_count == 3


def test_collect_logs_idempotent_second_run(tmp_path):
    """同じ入力で 2 回実行しても md が二重にならない（boundary_ids で除外）。"""
    entries = [_ce("d1", "G1", "2026-06-22T08:15:00+00:00", text="唯一の本文")]
    # 1 回目
    with patch("app.cli.pull.list_since", return_value=entries), \
         patch("app.cli.pull._group_name", return_value="姫路農場"):
        r1 = runner.invoke(app, ["collect-logs", "--out-dir", str(tmp_path)])
    assert r1.exit_code == 0, r1.stderr
    state = log_collector.read_state(tmp_path)
    assert state["boundary_ids"] == ["d1"]

    # 2 回目: state(cursor=その時刻, boundary={d1}) があるので inclusive(>=) で d1 を再取得するが、
    # boundary に居る d1 は除外され、追記 0。
    with patch("app.cli.pull.list_since", return_value=entries), \
         patch("app.cli.pull._group_name", return_value="姫路農場"):
        r2 = runner.invoke(app, ["collect-logs", "--out-dir", str(tmp_path)])
    assert r2.exit_code == 0, r2.stderr
    data2 = _stdout_json(r2)
    assert data2["appended"] == 0
    md = (tmp_path / "姫路農場.md").read_text(encoding="utf-8")
    assert md.count("唯一の本文") == 1


# --- write_state アトミック性 ------------------------------------------------

def test_write_state_atomic_roundtrip_and_no_tmp(tmp_path):
    state = {"last_received": "2026-06-22T08:00:00+00:00", "boundary_ids": ["d2", "d1"]}
    log_collector.write_state(tmp_path, state)
    # round-trip（boundary_ids も保持）
    assert log_collector.read_state(tmp_path) == state
    # 一時ファイルが残らない
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


# --- state 消失ガード --------------------------------------------------------

def test_collect_logs_guard_skips_when_state_missing_but_md_exists(tmp_path):
    """cursor None ＋ 既存 md → 追記 0・警告（exit 0）。全件二重を防ぐ。"""
    (tmp_path / "姫路農場.md").write_text("# LINE会話ログ: 姫路農場 (groupId: G1)\n- 既存\n", encoding="utf-8")
    all_docs = [_ce("d1", "G1", "2026-06-22T08:00:00+00:00", text="全件バックフィルされる本文")]
    with patch("app.cli.pull.list_since", return_value=all_docs) as m, \
         patch("app.cli.pull._group_name", return_value="姫路農場"):
        result = runner.invoke(app, ["collect-logs", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stderr
    data = _stdout_json(result)
    assert data["appended"] == 0
    assert data.get("skipped") == "state_missing_guard"
    # list_since は呼ばれない（収集自体をスキップ）
    assert m.call_count == 0
    # 警告メッセージが stderr に出る
    assert "二重取り込み防止" in result.stderr
    # md は触られていない（全件本文が入っていない）
    md = (tmp_path / "姫路農場.md").read_text(encoding="utf-8")
    assert "全件バックフィルされる本文" not in md


def test_collect_logs_force_backfill_overrides_guard(tmp_path):
    """--force-backfill なら、既存 md があっても全件取得して追記する。"""
    (tmp_path / "姫路農場.md").write_text("# LINE会話ログ: 姫路農場 (groupId: G1)\n- 既存\n", encoding="utf-8")
    all_docs = [_ce("d1", "G1", "2026-06-22T08:00:00+00:00", text="バックフィル本文")]
    with patch("app.cli.pull.list_since", return_value=all_docs) as m, \
         patch("app.cli.pull._group_name", return_value="姫路農場"):
        result = runner.invoke(app, ["collect-logs", "--out-dir", str(tmp_path), "--force-backfill"])
    assert result.exit_code == 0, result.stderr
    data = _stdout_json(result)
    assert data["appended"] == 1
    assert m.call_count >= 1
    md = (tmp_path / "姫路農場.md").read_text(encoding="utf-8")
    assert "バックフィル本文" in md


# --- collect-logs: 旧形式 state 移行（inclusive 判定）-------------------------

def test_collect_logs_legacy_state_first_call_is_exclusive(tmp_path):
    """旧形式 state(last_received のみ・boundary_ids 無し)では、移行初回の list_since が
    inclusive=False(厳密 >) で呼ばれる。境界 doc を取りに行かず last_received と同時刻の
    1 通を二重追記しないため。"""
    # state を旧形式で用意（boundary_ids を持たない）。md も置いて初回バックフィル扱いにしない。
    log_collector.write_state(tmp_path, {"last_received": "2026-06-22T08:00:00+00:00"})
    (tmp_path / "姫路農場.md").write_text(
        "# LINE会話ログ: 姫路農場 (groupId: G1)\n- 既存\n", encoding="utf-8"
    )
    # cursor 以降の新規 doc を 1 件返し、取り切り(len<limit)で 1 バッチで抜ける。
    batch = [_ce("d2", "G1", "2026-06-22T09:00:00+00:00", text="新規本文")]
    m = MagicMock(side_effect=[batch, []])
    with patch("app.cli.pull.list_since", m), \
         patch("app.cli.pull._group_name", return_value="姫路農場"):
        result = runner.invoke(app, ["collect-logs", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stderr
    # state ガードは state があるので発火しない（収集は走る）。
    data = _stdout_json(result)
    assert data.get("skipped") is None
    # 最初の呼び出しが inclusive=False（旧形式 state＝boundary 空のため）。
    first_call = m.call_args_list[0]
    assert first_call.kwargs.get("inclusive") is False, first_call
    # cursor は last_received を渡している。
    assert first_call.args[0] == "2026-06-22T08:00:00+00:00"


def test_collect_logs_with_boundary_first_call_is_inclusive_and_no_dup(tmp_path):
    """boundary_ids を持つ通常 state では、初回 list_since が inclusive=True(>=) で呼ばれ、
    返り値に boundary の doc(d1) が含まれても二重追記されない（appended に数えない）。"""
    log_collector.write_state(
        tmp_path,
        {"last_received": "2026-06-22T08:00:00+00:00", "boundary_ids": ["d1"]},
    )
    (tmp_path / "姫路農場.md").write_text(
        "# LINE会話ログ: 姫路農場 (groupId: G1)\n- 既存\n", encoding="utf-8"
    )
    # >= 再取得で境界 d1 を含むが、d1 は boundary で除外。新規 d2 のみ追記。
    batch = [
        _ce("d1", "G1", "2026-06-22T08:00:00+00:00", text="境界の既出本文"),
        _ce("d2", "G1", "2026-06-22T09:00:00+00:00", text="新規本文"),
    ]
    m = MagicMock(side_effect=[batch, []])
    with patch("app.cli.pull.list_since", m), \
         patch("app.cli.pull._group_name", return_value="姫路農場"):
        result = runner.invoke(app, ["collect-logs", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stderr
    # 最初の呼び出しが inclusive=True（boundary があるため）。
    first_call = m.call_args_list[0]
    assert first_call.kwargs.get("inclusive") is True, first_call
    # boundary の d1 は二重追記されず、新規 d2 の 1 件だけ。
    data = _stdout_json(result)
    assert data["appended"] == 1
    md = (tmp_path / "姫路農場.md").read_text(encoding="utf-8")
    assert md.count("境界の既出本文") == 0
    assert md.count("新規本文") == 1


def test_collect_logs_first_run_backfills_when_no_md(tmp_path):
    """md が無い初回は、state 無しでも従来どおり全件バックフィルする。"""
    all_docs = [_ce("d1", "G1", "2026-06-22T08:00:00+00:00", text="初回本文")]
    with patch("app.cli.pull.list_since", return_value=all_docs), \
         patch("app.cli.pull._group_name", return_value="姫路農場"):
        result = runner.invoke(app, ["collect-logs", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stderr
    data = _stdout_json(result)
    assert data["appended"] == 1
    md = (tmp_path / "姫路農場.md").read_text(encoding="utf-8")
    assert "初回本文" in md

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from app import config
from app.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_logging():
    # CliRunner は呼び出しごとに stderr を差し替えるため、ハンドラを毎回作り直して
    # 旧ストリームへの emit エラー（--- Logging error ---）が混ざらないようにする
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
    # stderr には JSON Lines ログが混ざるため、最後の JSON 行（_fail のエラー出力）を取る
    lines = [ln for ln in result.stderr.strip().splitlines() if ln.strip()]
    return json.loads(lines[-1])


def test_pull_pending_outputs_json_array():
    with patch("app.cli.pull.list_pending", return_value=[{"doc_id": "a", "type": "image"}]) as m:
        result = runner.invoke(app, ["pull-pending", "--limit", "10"])
    assert result.exit_code == 0
    assert _stdout_json(result) == [{"doc_id": "a", "type": "image"}]
    m.assert_called_once_with(10)


def test_download_returns_unix_and_windows_paths():
    with patch("app.cli.pull.download", return_value=Path("/mnt/c/tmp/abc123.jpg")):
        result = runner.invoke(app, ["download", "abc123", "--dest-dir", "/mnt/c/tmp"])
    assert result.exit_code == 0
    data = _stdout_json(result)
    assert data["doc_id"] == "abc123"
    assert data["local_path_unix"] == "/mnt/c/tmp/abc123.jpg"
    assert data["local_path_windows"] == "C:\\tmp\\abc123.jpg"


def test_list_cases_passes_days():
    with patch("app.cli.notion_writer.list_cases", return_value=[{"case_name": "A"}]) as m:
        result = runner.invoke(app, ["list-cases", "--days", "30"])
    assert result.exit_code == 0
    assert _stdout_json(result) == [{"case_name": "A"}]
    m.assert_called_once_with(30)


def test_write_task_passes_args():
    with patch("app.cli.notion_writer.write_task", return_value={"page_id": "p", "url": "u"}) as m:
        result = runner.invoke(app, ["write-task", "--case", "佐藤邸", "--title", "見積", "--note", "n"])
    assert result.exit_code == 0
    assert _stdout_json(result)["page_id"] == "p"
    # priority/assignee 未指定は None で渡し、既定解決は notion_writer 側（既定優先度 Claude追記 / 担当 env）
    m.assert_called_once_with("佐藤邸", "見積", None, "n", None, None, None, None)


def test_write_task_passes_file_and_confidence():
    with patch("app.cli.notion_writer.write_task", return_value={"page_id": "p", "url": "u"}) as m:
        result = runner.invoke(app, [
            "write-task", "--case", "A", "--title", "t",
            "--file-name", "f.pdf", "--confidence", "高",
        ])
    assert result.exit_code == 0
    # 引数順: case,title,priority,note,onedrive_link,assignee_user_id,file_name,confidence
    assert m.call_args.args == ("A", "t", None, None, None, None, "f.pdf", "高")


def test_export_results_html_writes_file(tmp_path):
    page = {
        "id": "p1",
        "properties": {
            "タスク名": {"title": [{"plain_text": "【LINE】2026-05-30 見積"}]},
            "備考": {"rich_text": [{"plain_text": "案件: 佐藤邸\ngroupId: Cabc"}]},
            "ステータス": {"status": {"name": "未着手"}},
            "優先度": {"select": {"name": "Claude追記"}},
            "OneDrive": {"url": None},
        },
    }
    out = tmp_path / "LINE仕分け実績.html"
    with patch("app.cli.notion_writer.list_line_tasks", return_value=[page]):
        result = runner.invoke(app, ["export-results-html", "--out", str(out)])
    assert result.exit_code == 0
    data = _stdout_json(result)
    assert data["count"] == 1
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert 'id="data"' in content
    assert "★" not in content  # マーカー置換済み


def test_export_results_html_notion_error_keeps_file(tmp_path):
    out = tmp_path / "x.html"
    out.write_text("EXISTING", encoding="utf-8")
    with patch("app.cli.notion_writer.list_line_tasks", side_effect=RuntimeError("notion down")):
        result = runner.invoke(app, ["export-results-html", "--out", str(out)])
    assert result.exit_code != 0
    assert _stderr_json(result)["error"] == "export-results-html failed"
    assert out.read_text(encoding="utf-8") == "EXISTING"  # 既存ファイルを壊さない


def test_write_task_passes_assignee():
    with patch("app.cli.notion_writer.write_task", return_value={"page_id": "p", "url": "u"}) as m:
        result = runner.invoke(app, [
            "write-task", "--case", "A", "--title", "t",
            "--priority", "高", "--assignee-user-id", "U-keisuke",
        ])
    assert result.exit_code == 0
    assert m.call_args.args == ("A", "t", "高", None, None, "U-keisuke", None, None)


def test_update_task_passes_priority():
    with patch("app.cli.notion_writer.update_task", return_value={"page_id": "p", "updated_fields": ["priority"]}) as m:
        result = runner.invoke(app, ["update-task", "--page-id", "p", "--priority", "高"])
    assert result.exit_code == 0
    m.assert_called_once_with("p", None, None, "高", None, None, None, None, None)


def test_update_task_passes_status():
    with patch("app.cli.notion_writer.update_task", return_value={"page_id": "p", "updated_fields": ["status"]}) as m:
        result = runner.invoke(app, ["update-task", "--page-id", "p", "--status", "完了"])
    assert result.exit_code == 0
    # 引数順: page_id, case, title, priority, note, onedrive_link, status, assignee_user_id, completed_date
    assert m.call_args.args == ("p", None, None, None, None, None, "完了", None, None)


def test_update_task_passes_completed_date():
    with patch("app.cli.notion_writer.update_task", return_value={"page_id": "p", "updated_fields": ["completed_date"]}) as m:
        result = runner.invoke(app, ["update-task", "--page-id", "p", "--completed-date", "2026-06-16"])
    assert result.exit_code == 0
    # completed_date は引数の最後（9 番目）
    assert m.call_args.args == ("p", None, None, None, None, None, None, None, "2026-06-16")


def test_find_task_passes_args_and_outputs():
    sample = [{"page_id": "p1", "title": "甲賀　レイアウト【済】　単線結線図【済】",
               "note_excerpt": "案件: ニッコン_甲賀営業所", "last_edited": "2026-06-15T00:00:00Z"}]
    with patch("app.cli.notion_writer.find_tasks", return_value=sample) as m:
        result = runner.invoke(app, ["find-task", "--query", "甲賀", "--days", "30", "--limit", "5"])
    assert result.exit_code == 0
    assert _stdout_json(result) == sample
    m.assert_called_once_with("甲賀", 30, 5)


def test_find_task_defaults():
    with patch("app.cli.notion_writer.find_tasks", return_value=[]) as m:
        result = runner.invoke(app, ["find-task", "--query", "岩沼"])
    assert result.exit_code == 0
    assert _stdout_json(result) == []
    m.assert_called_once_with("岩沼", 90, 20)  # 既定 days=90 / limit=20


def test_find_task_failure_emits_error():
    with patch("app.cli.notion_writer.find_tasks", side_effect=RuntimeError("notion down")):
        result = runner.invoke(app, ["find-task", "--query", "x"])
    assert result.exit_code != 0
    assert _stderr_json(result)["error"] == "find-task failed"


def test_list_case_folders_outputs_array():
    sample = [{"folder_name": "テラチャージ", "depth": 1, "parent_folder_name": None}]
    with patch("app.cli.folders.list_case_folders", return_value=sample) as m:
        result = runner.invoke(app, ["list-case-folders", "--max-depth", "3"])
    assert result.exit_code == 0
    assert _stdout_json(result) == sample
    m.assert_called_once_with(None, 3, query=None)


def test_list_case_folders_query_deepens_and_passes():
    with patch("app.cli.folders.list_case_folders", return_value=[]) as m:
        result = runner.invoke(app, ["list-case-folders", "--query", "姫路"])
    assert result.exit_code == 0
    # query 指定で深さは max(3,6)=6、query を渡す（bug2 対策）
    m.assert_called_once_with(None, 6, query="姫路")


def test_list_messages_passes_args_and_outputs():
    sample = [{"doc_id": "a", "message_type": "text", "text": "x"}]
    with patch("app.cli.pull.list_messages", return_value=sample) as m:
        result = runner.invoke(app, [
            "list-messages", "--group-id", "Cgrp", "--around-doc", "d1", "--window-hours", "24",
        ])
    assert result.exit_code == 0
    assert _stdout_json(result) == sample
    assert m.call_args.kwargs["around_doc"] == "d1"
    assert m.call_args.kwargs["window_hours"] == 24


def test_list_case_folders_resolves_windows_root(monkeypatch):
    # A-2 ①: --root の Windows パスも実マウントへ解決してから渡す
    monkeypatch.setattr("app.mounts.discover_maps",
                        lambda raw, self_path=None: [("/sessions/s/mnt/@@@", "C:\\X\\@@@")])
    with patch("app.cli.folders.list_case_folders", return_value=[]) as m:
        result = runner.invoke(app, ["list-case-folders", "--root", "C:\\X\\@@@\\branch"])
    assert result.exit_code == 0
    m.assert_called_once_with("/sessions/s/mnt/@@@/branch", 3, query=None)


def test_list_case_folders_root_not_found():
    with patch("app.cli.folders.list_case_folders", side_effect=FileNotFoundError("no root")):
        result = runner.invoke(app, ["list-case-folders", "--root", "/nope"])
    assert result.exit_code != 0
    assert _stderr_json(result)["error"] == "root_not_found"


def test_place_file_success(tmp_path):
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF")
    dest = Path("/mnt/c/案件/佐藤邸/09.LINEやりとり資料/2026-05-29 見積.pdf")
    with patch("app.cli.sharepoint_writer.place_in_case_folder", return_value=(dest, True)), \
         patch("app.cli.sharepoint_writer.to_onedrive_link", return_value=None):
        result = runner.invoke(app, [
            "place-file", "--src", str(src), "--case-folder", "/mnt/c/案件/佐藤邸", "--title", "見積",
        ])
    assert result.exit_code == 0
    data = _stdout_json(result)
    assert data["destination_unix"] == str(dest)
    assert data["destination_windows"].startswith("C:\\")
    assert data["onedrive_link"] is None
    assert data["created_subfolder"] is True


def test_place_file_resolves_windows_case_folder(tmp_path, monkeypatch):
    # bug1: Skill が渡す Windows パスの --case-folder を実マウントへ解決してから書く
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF")
    monkeypatch.setattr("app.mounts.discover_maps",
                        lambda raw, self_path=None: [("/sessions/s/mnt/@@@", "C:\\X\\@@@")])
    dest = Path("/sessions/s/mnt/@@@/案件/09.LINEやりとり資料/2026-05-30 見積.pdf")
    with patch("app.cli.sharepoint_writer.place_in_case_folder", return_value=(dest, False)) as m, \
         patch("app.cli.sharepoint_writer.to_onedrive_link", return_value=None):
        result = runner.invoke(app, [
            "place-file", "--src", str(src),
            "--case-folder", "C:\\X\\@@@\\案件", "--title", "見積",
        ])
    assert result.exit_code == 0
    # place_in_case_folder には解決後の unix パスが渡る
    assert m.call_args.args[0] == "/sessions/s/mnt/@@@/案件"


def test_place_file_default_uses_09_subfolder(tmp_path):
    # 既定（フラグ無し）は subfolder=09…、allow_create=False（後方互換）
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF")
    dest = Path("/mnt/c/案件/A/09.LINEやりとり資料/2026-06-07 見積.pdf")
    with patch("app.cli.sharepoint_writer.place_in_case_folder", return_value=(dest, True)) as m, \
         patch("app.cli.sharepoint_writer.to_onedrive_link", return_value=None):
        result = runner.invoke(app, [
            "place-file", "--src", str(src), "--case-folder", "/mnt/c/案件/A", "--title", "見積",
        ])
    assert result.exit_code == 0
    assert m.call_args.kwargs["subfolder"] == "09.LINEやりとり資料"
    assert m.call_args.kwargs["allow_create"] is False


def test_place_file_no_subfolder_and_allow_create(tmp_path):
    # 個人 OneDrive 運用: --no-subfolder で subfolder=None、--allow-create で allow_create=True
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF")
    dest = Path("/mnt/c/LINE資料/A/2026-06-07 見積.pdf")
    with patch("app.cli.sharepoint_writer.place_in_case_folder", return_value=(dest, True)) as m, \
         patch("app.cli.sharepoint_writer.to_onedrive_link", return_value=None):
        result = runner.invoke(app, [
            "place-file", "--src", str(src), "--case-folder", "/mnt/c/LINE資料/A",
            "--title", "見積", "--no-subfolder", "--allow-create",
        ])
    assert result.exit_code == 0
    assert m.call_args.kwargs["subfolder"] is None
    assert m.call_args.kwargs["allow_create"] is True


def test_place_file_case_folder_not_found(tmp_path):
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF")
    with patch("app.cli.sharepoint_writer.place_in_case_folder", side_effect=FileNotFoundError("nope")):
        result = runner.invoke(app, [
            "place-file", "--src", str(src), "--case-folder", "/mnt/c/案件/無い", "--title", "見積",
        ])
    assert result.exit_code != 0
    assert _stderr_json(result)["error"] == "case_folder_not_found"


def test_write_log_overwrites_fixed_name():
    dest = Path("/mnt/c/案件/A/09.LINEやりとり資料/2026-05-29 議事ログ.md")
    with patch("app.cli.sharepoint_writer.place_in_case_folder", return_value=(dest, False)) as m:
        result = runner.invoke(app, [
            "write-log", "--case-folder", "/mnt/c/案件/A", "--date", "2026-05-29", "--content", "# log",
        ])
    assert result.exit_code == 0
    data = _stdout_json(result)
    assert data["created_subfolder"] is False
    # overwrite=True で固定名書き込み
    assert m.call_args.kwargs.get("overwrite") is True
    assert "議事ログ.md" in m.call_args.args[1]


def test_write_log_custom_filename_for_html():
    dest = Path("/mnt/c/案件/A/09.LINEやりとり資料/2026-05-30 議事ログ.html")
    with patch("app.cli.sharepoint_writer.place_in_case_folder", return_value=(dest, False)) as m:
        result = runner.invoke(app, [
            "write-log", "--case-folder", "/mnt/c/案件/A", "--date", "2026-05-30",
            "--content", "<html>x</html>", "--filename", "2026-05-30 議事ログ.html",
        ])
    assert result.exit_code == 0
    assert m.call_args.args[1] == "2026-05-30 議事ログ.html"
    assert m.call_args.kwargs.get("overwrite") is True


def test_write_log_no_subfolder_and_allow_create():
    dest = Path("/mnt/c/LINE資料/A/議事ログ.html")
    with patch("app.cli.sharepoint_writer.place_in_case_folder", return_value=(dest, True)) as m:
        result = runner.invoke(app, [
            "write-log", "--case-folder", "/mnt/c/LINE資料/A", "--date", "2026-06-07",
            "--content", "<html>x</html>", "--filename", "議事ログ.html",
            "--no-subfolder", "--allow-create",
        ])
    assert result.exit_code == 0
    assert m.call_args.kwargs["subfolder"] is None
    assert m.call_args.kwargs["allow_create"] is True
    assert m.call_args.kwargs.get("overwrite") is True
    assert m.call_args.args[1] == "議事ログ.html"


def test_write_log_default_uses_09_subfolder():
    dest = Path("/mnt/c/案件/A/09.LINEやりとり資料/2026-06-07 議事ログ.md")
    with patch("app.cli.sharepoint_writer.place_in_case_folder", return_value=(dest, False)) as m:
        result = runner.invoke(app, [
            "write-log", "--case-folder", "/mnt/c/案件/A", "--date", "2026-06-07", "--content", "# log",
        ])
    assert result.exit_code == 0
    assert m.call_args.kwargs["subfolder"] == "09.LINEやりとり資料"
    assert m.call_args.kwargs["allow_create"] is False


def test_write_log_resolves_windows_case_folder(monkeypatch):
    monkeypatch.setattr("app.mounts.discover_maps",
                        lambda raw, self_path=None: [("/sessions/s/mnt/@@@", "C:\\X\\@@@")])
    dest = Path("/sessions/s/mnt/@@@/A/09.LINEやりとり資料/2026-05-30 議事ログ.md")
    with patch("app.cli.sharepoint_writer.place_in_case_folder", return_value=(dest, False)) as m:
        result = runner.invoke(app, [
            "write-log", "--case-folder", "C:\\X\\@@@\\A", "--date", "2026-05-30", "--content", "# log",
        ])
    assert result.exit_code == 0
    assert m.call_args.args[0] == "/sessions/s/mnt/@@@/A"


def test_write_log_reads_content_from_stdin():
    dest = Path("/mnt/c/案件/A/09.LINEやりとり資料/2026-05-29 議事ログ.md")
    with patch("app.cli.sharepoint_writer.place_in_case_folder", return_value=(dest, False)) as m:
        result = runner.invoke(
            app,
            ["write-log", "--case-folder", "/mnt/c/案件/A", "--date", "2026-05-29", "--content", "-"],
            input="# stdin から渡したログ\n本文",
        )
    assert result.exit_code == 0
    # place_in_case_folder の content 引数(args[2]) が stdin の内容
    assert "stdin から渡したログ" in m.call_args.args[2]


def test_mark_done():
    with patch("app.cli.pull.mark_done", return_value={"doc_id": "a", "status": "done", "gcs_deleted": True}) as m:
        result = runner.invoke(app, ["mark-done", "a"])
    assert result.exit_code == 0
    assert _stdout_json(result)["status"] == "done"
    m.assert_called_once_with("a")


def test_mark_review_with_reason():
    with patch("app.cli.pull.mark_review", return_value={"doc_id": "a", "status": "needs_review", "reason": "不明"}) as m:
        result = runner.invoke(app, ["mark-review", "a", "--reason", "不明"])
    assert result.exit_code == 0
    m.assert_called_once_with("a", "不明")


def test_error_emits_json_to_stderr_and_nonzero_exit():
    with patch("app.cli.pull.list_pending", side_effect=RuntimeError("firestore down")):
        result = runner.invoke(app, ["pull-pending"])
    assert result.exit_code == 1
    err = _stderr_json(result)
    assert err["error"] == "pull-pending failed"
    assert "firestore down" in err["detail"]


def test_log_run_id_is_accepted():
    with patch("app.cli.pull.list_pending", return_value=[]), \
         patch("app.cli.config.add_file_handler") as m_handler:
        result = runner.invoke(app, ["pull-pending", "--log-run-id", "session-xyz"])
    assert result.exit_code == 0
    m_handler.assert_called_once_with("session-xyz")


def test_help_works():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "pull-pending" in result.stdout

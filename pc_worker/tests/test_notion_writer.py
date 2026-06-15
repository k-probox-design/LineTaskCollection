from unittest.mock import MagicMock, patch

import pytest

from app import notion_writer
from app.notion_writer import (
    PROP_ONEDRIVE,
    PROP_PRIORITY,
    PROP_TITLE,
    list_cases,
    update_task,
    write_task,
)

_DSID = "ds_design_task"


@pytest.fixture(autouse=True)
def _reset_data_source_cache():
    # data_source_id / スキーマ / タイトル列名はモジュールグローバルにキャッシュされるので毎回クリア
    notion_writer._data_source_id = None
    notion_writer._schema_props = None
    notion_writer._title_prop_name = None
    yield
    notion_writer._data_source_id = None
    notion_writer._schema_props = None
    notion_writer._title_prop_name = None


def _schema(title_name: str = "タスク名") -> dict:
    """data_sources.retrieve が返すスキーマ（title 列名を差し替え可能）。"""
    return {
        "properties": {
            title_name: {"id": "title", "name": title_name, "type": "title"},
            "優先度": {"id": "p1", "name": "優先度", "type": "select"},
            "ステータス": {"id": "s1", "name": "ステータス", "type": "status"},
            "担当": {"id": "a1", "name": "担当", "type": "people"},
            "備考": {"id": "n1", "name": "備考", "type": "rich_text"},
            "OneDrive": {"id": "o1", "name": "OneDrive", "type": "url"},
            "タスク登録日": {"id": "d1", "name": "タスク登録日", "type": "date"},
            "日付": {"id": "d2", "name": "日付", "type": "date"},
        }
    }


def _client_with_data_source(title_name: str = "タスク名"):
    """databases.retrieve が単一データソースを、data_sources.retrieve がスキーマを返すモック。"""
    client = MagicMock()
    client.databases.retrieve.return_value = {
        "data_sources": [{"id": _DSID, "name": "設計タスク管理"}],
    }
    client.data_sources.retrieve.return_value = _schema(title_name)
    return client


def test_resolve_data_source_id_from_retrieve(monkeypatch):
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    client = _client_with_data_source()
    with patch("app.notion_writer._get_client", return_value=client):
        assert notion_writer._get_data_source_id() == _DSID
    client.databases.retrieve.assert_called_once()


def test_resolve_data_source_id_prefers_env(monkeypatch):
    monkeypatch.setenv("NOTION_DATA_SOURCE_ID", "env_dsid")
    client = _client_with_data_source()
    with patch("app.notion_writer._get_client", return_value=client):
        assert notion_writer._get_data_source_id() == "env_dsid"
    client.databases.retrieve.assert_not_called()


def test_write_task_payload(monkeypatch):
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    client = _client_with_data_source()
    client.pages.create.return_value = {"id": "page_1", "url": "https://notion.so/page_1"}

    with patch("app.notion_writer._get_client", return_value=client):
        result = write_task(case="コスモス", title="【LINE】2026-05-29 見積書", note="確信度 0.9")

    assert result == {"page_id": "page_1", "url": "https://notion.so/page_1"}
    # parent は 2025-09-03 形式の data_source_id 指定
    assert client.pages.create.call_args.kwargs["parent"] == {
        "type": "data_source_id",
        "data_source_id": _DSID,
    }
    props = client.pages.create.call_args.kwargs["properties"]
    assert props[PROP_TITLE]["title"][0]["text"]["content"] == "【LINE】2026-05-29 見積書"
    # priority 未指定 → 既定 "Claude追記"（ボット起因の目印）
    assert props[PROP_PRIORITY]["select"]["name"] == "Claude追記"
    # 既定 assignee 未設定なので担当は付かない
    assert "担当" not in props
    note = props["備考"]["rich_text"][0]["text"]["content"]
    assert "案件: コスモス" in note
    assert "確信度 0.9" in note


def test_write_task_with_onedrive_link(monkeypatch):
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    client = _client_with_data_source()
    client.pages.create.return_value = {"id": "p", "url": "u"}
    with patch("app.notion_writer._get_client", return_value=client):
        write_task(case="A", title="t", priority="通常", onedrive_link="file:///c/x.pdf")
    props = client.pages.create.call_args.kwargs["properties"]
    assert props[PROP_PRIORITY]["select"]["name"] == "通常"
    assert props[PROP_ONEDRIVE]["url"] == "file:///c/x.pdf"


def test_update_task_only_specified_fields():
    # update は page_id 指定なので data_source_id 解決は不要（databases.retrieve を呼ばない）
    client = MagicMock()
    with patch("app.notion_writer._get_client", return_value=client):
        result = update_task("page_1", priority="通常", onedrive_link="file:///c/y.pdf")

    assert result["page_id"] == "page_1"
    assert set(result["updated_fields"]) == {"priority", "onedrive_link"}
    props = client.pages.update.call_args.kwargs["properties"]
    assert props[PROP_PRIORITY]["select"]["name"] == "通常"
    assert props[PROP_ONEDRIVE]["url"] == "file:///c/y.pdf"
    assert PROP_TITLE not in props  # title 未指定なら更新しない
    client.databases.retrieve.assert_not_called()


def test_write_task_sets_assignee_from_env(monkeypatch):
    monkeypatch.setenv("NOTION_DEFAULT_ASSIGNEE_USER_ID", "U-keisuke")
    client = _client_with_data_source()
    client.pages.create.return_value = {"id": "p", "url": "u"}
    with patch("app.notion_writer._get_client", return_value=client):
        write_task(case="A", title="t")
    props = client.pages.create.call_args.kwargs["properties"]
    assert props["担当"] == {"people": [{"object": "user", "id": "U-keisuke"}]}


def test_write_task_priority_override_and_explicit_assignee(monkeypatch):
    monkeypatch.setenv("NOTION_DEFAULT_PRIORITY", "Claude追記")
    client = _client_with_data_source()
    client.pages.create.return_value = {"id": "p", "url": "u"}
    with patch("app.notion_writer._get_client", return_value=client):
        write_task(case="A", title="t", priority="高", assignee_user_id="U-x")
    props = client.pages.create.call_args.kwargs["properties"]
    assert props[PROP_PRIORITY]["select"]["name"] == "高"  # 明示指定が既定に優先
    assert props["担当"]["people"][0]["id"] == "U-x"


def test_update_task_sets_assignee():
    client = MagicMock()
    with patch("app.notion_writer._get_client", return_value=client):
        result = update_task("p", assignee_user_id="U-keisuke")
    assert "assignee" in result["updated_fields"]
    props = client.pages.update.call_args.kwargs["properties"]
    assert props["担当"] == {"people": [{"object": "user", "id": "U-keisuke"}]}


def test_write_task_note_includes_file_and_confidence(monkeypatch):
    monkeypatch.delenv("NOTION_DEFAULT_ASSIGNEE_USER_ID", raising=False)
    client = _client_with_data_source()
    client.pages.create.return_value = {"id": "p", "url": "u"}
    with patch("app.notion_writer._get_client", return_value=client):
        write_task(case="三和鶏園", title="t", note="groupId: Cabc",
                   file_name="2026-05-30 図面.pdf", confidence="高")
    note = client.pages.create.call_args.kwargs["properties"]["備考"]["rich_text"][0]["text"]["content"]
    assert "案件: 三和鶏園" in note
    assert "ファイル: 2026-05-30 図面.pdf" in note
    assert "確信度: 高" in note
    assert "groupId: Cabc" in note


def test_list_line_tasks_filters_by_prefix_and_paginates():
    client = _client_with_data_source()
    client.data_sources.query.side_effect = [
        {"results": [{"id": "a"}], "has_more": True, "next_cursor": "cur"},
        {"results": [{"id": "b"}], "has_more": False},
    ]
    with patch("app.notion_writer._get_client", return_value=client):
        pages = notion_writer.list_line_tasks()
    assert [p["id"] for p in pages] == ["a", "b"]  # 2 ページ分を連結
    first_filter = client.data_sources.query.call_args_list[0].kwargs["filter"]
    assert first_filter == {"property": "タスク名", "title": {"starts_with": "【LINE】"}}


def test_update_task_sets_status_property():
    # 完了化は status 型「ステータス」で（優先度に "通常" は無い）
    client = MagicMock()
    with patch("app.notion_writer._get_client", return_value=client):
        result = update_task("page_1", status="完了")
    assert "status" in result["updated_fields"]
    props = client.pages.update.call_args.kwargs["properties"]
    assert props["ステータス"] == {"status": {"name": "完了"}}
    client.databases.retrieve.assert_not_called()


def test_list_cases_aggregates_by_name(monkeypatch):
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    client = _client_with_data_source()
    client.data_sources.query.return_value = {
        "results": [
            {
                "last_edited_time": "2026-05-28T14:23:00+09:00",
                "properties": {PROP_TITLE: {"title": [{"plain_text": "佐藤邸新築"}]}},
            },
            {
                "last_edited_time": "2026-05-29T09:00:00+09:00",
                "properties": {PROP_TITLE: {"title": [{"plain_text": "佐藤邸新築"}]}},
            },
            {
                "last_edited_time": "2026-05-25T10:11:00+09:00",
                "properties": {PROP_TITLE: {"title": [{"plain_text": "山田事務所改修"}]}},
            },
        ],
        "has_more": False,
    }
    with patch("app.notion_writer._get_client", return_value=client):
        cases = list_cases(days=90)

    # data_sources.query を data_source_id で呼ぶ
    assert client.data_sources.query.call_args.kwargs["data_source_id"] == _DSID
    # 件数集約 + 最終更新降順
    assert cases[0]["case_name"] == "佐藤邸新築"
    assert cases[0]["task_count"] == 2
    assert cases[0]["last_updated"] == "2026-05-29T09:00:00+09:00"
    assert cases[1]["case_name"] == "山田事務所改修"
    assert cases[1]["task_count"] == 1


# --- タイトル列名の動的解決（列名ドリフト耐性） -------------------------------------------

def test_title_prop_name_resolved_from_schema(monkeypatch):
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    client = _client_with_data_source(title_name="タスク名")
    with patch("app.notion_writer._get_client", return_value=client):
        assert notion_writer._get_title_prop_name() == "タスク名"


def test_title_prop_name_handles_empty_string_drift(monkeypatch):
    # 表示名が空文字 "" にドリフトしても type=="title" で追従する（本件の恒久対応）
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    client = _client_with_data_source(title_name="")
    with patch("app.notion_writer._get_client", return_value=client):
        assert notion_writer._get_title_prop_name() == ""


def test_title_prop_name_raises_without_title(monkeypatch):
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    client = _client_with_data_source()
    client.data_sources.retrieve.return_value = {
        "properties": {"優先度": {"id": "p", "name": "優先度", "type": "select"}}
    }
    with patch("app.notion_writer._get_client", return_value=client):
        with pytest.raises(RuntimeError, match="title 型プロパティ未検出"):
            notion_writer._get_title_prop_name()


def test_write_task_uses_dynamic_title_key_when_name_empty(monkeypatch):
    # 列名が "" でも write-task が空文字キーで title を入れる（400 で落ちない）
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    client = _client_with_data_source(title_name="")
    client.pages.create.return_value = {"id": "p", "url": "u"}
    with patch("app.notion_writer._get_client", return_value=client):
        write_task(case="甲賀", title="【LINE】甲賀")
    props = client.pages.create.call_args.kwargs["properties"]
    assert props[""]["title"][0]["text"]["content"] == "【LINE】甲賀"


def test_list_line_tasks_filter_follows_dynamic_title_name(monkeypatch):
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    client = _client_with_data_source(title_name="")  # 空文字にドリフト
    client.data_sources.query.return_value = {"results": [], "has_more": False}
    with patch("app.notion_writer._get_client", return_value=client):
        notion_writer.list_line_tasks()
    first_filter = client.data_sources.query.call_args.kwargs["filter"]
    assert first_filter == {"property": "", "title": {"starts_with": "【LINE】"}}


# --- update_task: 全角/【】タイトル & status ホワイトリスト --------------------------------

def test_update_task_title_preserves_fullwidth_and_brackets(monkeypatch):
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    client = _client_with_data_source()
    new_title = "甲賀　レイアウト【済】　単線結線図【済】"  # 全角スペース＋全角ブラケット
    with patch("app.notion_writer._get_client", return_value=client):
        update_task("page_1", title=new_title)
    props = client.pages.update.call_args.kwargs["properties"]
    assert props["タスク名"]["title"][0]["text"]["content"] == new_title


def test_update_task_accepts_known_status():
    client = MagicMock()
    with patch("app.notion_writer._get_client", return_value=client):
        result = update_task("p", status="レイアウト完了")
    assert "status" in result["updated_fields"]
    props = client.pages.update.call_args.kwargs["properties"]
    assert props["ステータス"] == {"status": {"name": "レイアウト完了"}}


def test_update_task_rejects_unknown_status():
    client = MagicMock()
    with patch("app.notion_writer._get_client", return_value=client):
        with pytest.raises(ValueError, match="未知のステータス"):
            update_task("p", status="やっぱり完了")
    client.pages.update.assert_not_called()  # API を叩く前に弾く


def test_update_task_sets_completed_date():
    client = MagicMock()
    with patch("app.notion_writer._get_client", return_value=client):
        result = update_task("p", status="完了", completed_date="2026-06-16")
    assert "completed_date" in result["updated_fields"]
    props = client.pages.update.call_args.kwargs["properties"]
    assert props["タスク完了日"] == {"date": {"start": "2026-06-16"}}
    assert props["ステータス"] == {"status": {"name": "完了"}}  # status と併用できる


# --- find_tasks: 【LINE】が消えたリネーム済みも備考一致で引く --------------------------------

def _page(pid: str, title: str, note: str, last_edited: str = "2026-06-15T00:00:00.000Z") -> dict:
    return {
        "id": pid,
        "last_edited_time": last_edited,
        "properties": {
            "タスク名": {"title": [{"plain_text": title}]},
            "備考": {"rich_text": [{"plain_text": note}]},
        },
    }


def _find_client(pages):
    client = _client_with_data_source()
    client.data_sources.query.return_value = {"results": pages, "has_more": False}
    return client


def test_find_tasks_matches_renamed_title_by_note(monkeypatch):
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    pages = [
        _page("g_koka", "甲賀　レイアウト【済】　単線結線図【済】", "投稿者: X\n案件: ニッコン_甲賀営業所"),
        _page("g_kobe", "神戸　レイアウト【済】　単線結線図【未】", "案件: ニッコン_神戸営業所"),
    ]
    client = _find_client(pages)
    with patch("app.notion_writer._get_client", return_value=client):
        matches = notion_writer.find_tasks("甲賀")
    # 【LINE】プレフィックス filter は使わない（last_edited_time 窓のみ）
    assert "starts_with" not in str(client.data_sources.query.call_args.kwargs["filter"])
    assert [m["page_id"] for m in matches] == ["g_koka"]
    assert matches[0]["title"] == "甲賀　レイアウト【済】　単線結線図【済】"


def test_find_tasks_normalizes_space_and_width(monkeypatch):
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    pages = [_page("g1", "甲賀　レイアウト【済】　単線結線図【未】", "案件: ＮＩＫＫＯＮ")]
    client = _find_client(pages)
    with patch("app.notion_writer._get_client", return_value=client):
        # 全角スペースを跨いだ連結 & 半角→全角の表記ゆれ
        assert len(notion_writer.find_tasks("甲賀レイアウト")) == 1
        assert len(notion_writer.find_tasks("NIKKON")) == 1


def test_find_tasks_respects_limit(monkeypatch):
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    pages = [_page(f"g{i}", f"岩沼{i} レイアウト", "案件: 岩沼") for i in range(5)]
    client = _find_client(pages)
    with patch("app.notion_writer._get_client", return_value=client):
        matches = notion_writer.find_tasks("岩沼", limit=2)
    assert len(matches) == 2

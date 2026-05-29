from unittest.mock import MagicMock, patch

from app.notion_writer import (
    PROP_ONEDRIVE,
    PROP_PRIORITY,
    PROP_TITLE,
    list_cases,
    update_task,
    write_task,
)


def test_write_task_payload():
    client = MagicMock()
    client.pages.create.return_value = {"id": "page_1", "url": "https://notion.so/page_1"}

    with patch("app.notion_writer._get_client", return_value=client):
        result = write_task(case="コスモス", title="【LINE】2026-05-29 見積書", note="確信度 0.9")

    assert result == {"page_id": "page_1", "url": "https://notion.so/page_1"}
    props = client.pages.create.call_args.kwargs["properties"]
    assert props[PROP_TITLE]["title"][0]["text"]["content"] == "【LINE】2026-05-29 見積書"
    assert props[PROP_PRIORITY]["select"]["name"] == "仕分け待ち"
    note = props["備考"]["rich_text"][0]["text"]["content"]
    assert "案件: コスモス" in note
    assert "確信度 0.9" in note


def test_write_task_with_onedrive_link():
    client = MagicMock()
    client.pages.create.return_value = {"id": "p", "url": "u"}
    with patch("app.notion_writer._get_client", return_value=client):
        write_task(case="A", title="t", priority="通常", onedrive_link="file:///c/x.pdf")
    props = client.pages.create.call_args.kwargs["properties"]
    assert props[PROP_PRIORITY]["select"]["name"] == "通常"
    assert props[PROP_ONEDRIVE]["url"] == "file:///c/x.pdf"


def test_update_task_only_specified_fields():
    client = MagicMock()
    with patch("app.notion_writer._get_client", return_value=client):
        result = update_task("page_1", priority="通常", onedrive_link="file:///c/y.pdf")

    assert result["page_id"] == "page_1"
    assert set(result["updated_fields"]) == {"priority", "onedrive_link"}
    props = client.pages.update.call_args.kwargs["properties"]
    assert props[PROP_PRIORITY]["select"]["name"] == "通常"
    assert props[PROP_ONEDRIVE]["url"] == "file:///c/y.pdf"
    assert PROP_TITLE not in props  # title 未指定なら更新しない


def test_list_cases_aggregates_by_name():
    client = MagicMock()
    client.databases.query.return_value = {
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

    # 件数集約 + 最終更新降順
    assert cases[0]["case_name"] == "佐藤邸新築"
    assert cases[0]["task_count"] == 2
    assert cases[0]["last_updated"] == "2026-05-29T09:00:00+09:00"
    assert cases[1]["case_name"] == "山田事務所改修"
    assert cases[1]["task_count"] == 1

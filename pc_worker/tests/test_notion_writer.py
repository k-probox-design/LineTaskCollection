from unittest.mock import MagicMock, patch

from app.classify import ClassifyResult
from app.notion_writer import (
    PROP_ONEDRIVE,
    PROP_PRIORITY,
    PROP_TITLE,
    create_pending_task,
    fetch_case_candidates,
    update_task_with_sharepoint_link,
)
from app.pull import PendingItem


def test_create_pending_task_payload():
    client = MagicMock()
    client.pages.create.return_value = {"id": "page_1"}
    item = PendingItem(message_id="m1", group_id="C1", type="image", gcs_path="gs://b/pending/x.jpg")
    result = ClassifyResult(case_name="コスモス", title="見積書", confidence=0.9, reasoning="r", related_message_ids=["m1"])

    with patch("app.notion_writer._get_client", return_value=client):
        page_id = create_pending_task(item, result)

    assert page_id == "page_1"
    props = client.pages.create.call_args.kwargs["properties"]
    title = props[PROP_TITLE]["title"][0]["text"]["content"]
    assert title.startswith("【LINE】")
    assert "見積書" in title
    assert props[PROP_PRIORITY]["select"]["name"] == "仕分け待ち"
    note = props["備考"]["rich_text"][0]["text"]["content"]
    assert "確信度: 0.90" in note
    assert "m1" in note


def test_update_task_with_sharepoint_link():
    client = MagicMock()
    with patch("app.notion_writer._get_client", return_value=client):
        update_task_with_sharepoint_link("page_1", "file:///c/案件/x.jpg")
    props = client.pages.update.call_args.kwargs["properties"]
    assert props[PROP_ONEDRIVE]["url"] == "file:///c/案件/x.jpg"


def test_fetch_case_candidates_paginates_and_extracts_titles():
    client = MagicMock()
    client.databases.query.side_effect = [
        {
            "results": [
                {"properties": {PROP_TITLE: {"title": [{"plain_text": "コスモス ソラプロ"}]}}},
                {"properties": {PROP_TITLE: {"title": [{"plain_text": "山田邸 "}]}}},
            ],
            "has_more": True,
            "next_cursor": "cursor2",
        },
        {
            "results": [
                {"properties": {PROP_TITLE: {"title": [{"plain_text": "佐藤ビル"}]}}},
            ],
            "has_more": False,
        },
    ]
    with patch("app.notion_writer._get_client", return_value=client):
        candidates = fetch_case_candidates()

    assert candidates == ["コスモス ソラプロ", "山田邸", "佐藤ビル"]
    # 2 ページ目は start_cursor 付きで呼ばれる
    assert client.databases.query.call_count == 2
    assert client.databases.query.call_args_list[1].kwargs["start_cursor"] == "cursor2"

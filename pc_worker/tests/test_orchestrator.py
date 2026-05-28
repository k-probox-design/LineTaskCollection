from pathlib import Path
from unittest.mock import patch

from app.classify import ClassifyResult
from app.orchestrator import run_once
from app.pull import PendingItem


def _item():
    return PendingItem(
        message_id="m1", group_id="C1", type="image",
        gcs_path="gs://b/pending/x.jpg", content_bytes=b"\xff\xd8\xff",
    )


def test_confident_item_stores_and_marks_done():
    item = _item()
    result = ClassifyResult(case_name="コスモス", title="見積書", confidence=0.95, reasoning="r", related_message_ids=[])

    with patch("app.orchestrator.pull.pull_pending", return_value=[item]), \
         patch("app.orchestrator.notion_writer.fetch_case_candidates", return_value=["コスモス"]), \
         patch("app.orchestrator.classify.classify", return_value=result), \
         patch("app.orchestrator.notion_writer.create_pending_task", return_value="page_1") as m_create, \
         patch("app.orchestrator.sharepoint_writer.write_to_case_folder", return_value=Path("/tmp/コスモス/x.jpg")) as m_sp, \
         patch("app.orchestrator.notion_writer.update_task_with_sharepoint_link") as m_update, \
         patch("app.orchestrator.log_writer.build_session_log", return_value="# log"), \
         patch("app.orchestrator.pull.mark_done_and_cleanup") as m_done, \
         patch("app.orchestrator.pull.mark_review_only") as m_review:
        run_once()

    m_create.assert_called_once()
    assert m_sp.call_count == 2  # 個別ファイル + 議事ログ
    m_update.assert_called_once()
    m_done.assert_called_once()
    m_review.assert_not_called()


def test_low_confidence_item_left_for_review():
    item = _item()
    result = ClassifyResult(case_name="コスモス", title="写真", confidence=0.5, reasoning="r", related_message_ids=[])

    with patch("app.orchestrator.pull.pull_pending", return_value=[item]), \
         patch("app.orchestrator.notion_writer.fetch_case_candidates", return_value=["コスモス"]), \
         patch("app.orchestrator.classify.classify", return_value=result), \
         patch("app.orchestrator.notion_writer.create_pending_task", return_value="page_1") as m_create, \
         patch("app.orchestrator.sharepoint_writer.write_to_case_folder") as m_sp, \
         patch("app.orchestrator.pull.mark_done_and_cleanup") as m_done, \
         patch("app.orchestrator.pull.mark_review_only") as m_review:
        run_once()

    m_create.assert_called_once()
    m_sp.assert_not_called()
    m_done.assert_not_called()
    m_review.assert_called_once()


def test_exception_in_one_item_does_not_abort_run():
    items = [_item(), _item()]
    result = ClassifyResult(case_name="コスモス", title="t", confidence=0.95, reasoning="r", related_message_ids=[])

    with patch("app.orchestrator.pull.pull_pending", return_value=items), \
         patch("app.orchestrator.notion_writer.fetch_case_candidates", return_value=["コスモス"]), \
         patch("app.orchestrator.classify.classify", return_value=result), \
         patch("app.orchestrator.notion_writer.create_pending_task", side_effect=[Exception("boom"), "page_2"]), \
         patch("app.orchestrator.sharepoint_writer.write_to_case_folder", return_value=Path("/tmp/x.jpg")), \
         patch("app.orchestrator.notion_writer.update_task_with_sharepoint_link"), \
         patch("app.orchestrator.log_writer.build_session_log", return_value="# log"), \
         patch("app.orchestrator.pull.mark_done_and_cleanup") as m_done, \
         patch("app.orchestrator.pull.mark_review_only"):
        run_once()

    # 1 件目で例外が出ても 2 件目は処理される
    m_done.assert_called_once()

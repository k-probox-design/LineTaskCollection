import logging
from pathlib import Path

from app import classify, log_writer, notion_writer, pull, sharepoint_writer
from app.config import settings
from app.pull import PendingItem

logger = logging.getLogger("orchestrator")

SUBFOLDER_DOCS = "09.受領資料"
SUBFOLDER_LOG = "09.LINEやりとり資料"


def _path_to_url(path: Path) -> str:
    try:
        return path.as_uri()
    except ValueError:
        return str(path)


def _process_item(item: PendingItem, candidates: list[str], threshold: float) -> None:
    result = classify.classify(item, candidates)
    page_id = notion_writer.create_pending_task(item, result)

    confident = bool(result.case_name) and result.confidence >= threshold
    if not confident or item.content_bytes is None:
        # 確信なし or 本体が取れない → Notion「仕分け待ち」row は残し、Firestore は needs_review に。
        # GCS も保持する(けいすけが手動確認 → 必要なら status を pending に戻して再 run できる)。
        pull.mark_review_only(item)
        return

    date_str = item.received_at.date().isoformat()
    sp_path = sharepoint_writer.write_to_case_folder(
        case_name=result.case_name,
        subfolder=SUBFOLDER_DOCS,
        filename=f"{date_str} {result.title}.{item.ext}",
        content=item.content_bytes,
    )
    notion_writer.update_task_with_sharepoint_link(page_id, _path_to_url(sp_path))

    log_md = log_writer.build_session_log(item.group_id, item.received_at)
    sharepoint_writer.write_to_case_folder(
        case_name=result.case_name,
        subfolder=SUBFOLDER_LOG,
        filename=f"{date_str} 議事ログ.md",
        content=log_md,
    )

    pull.mark_done_and_cleanup(item, final_path=str(sp_path))


def run_once() -> None:
    items = pull.pull_pending()
    candidates = notion_writer.fetch_case_candidates()
    threshold = settings.classify_confidence_threshold

    processed = 0
    for item in items:
        try:
            _process_item(item, candidates, threshold)
            processed += 1
        except Exception:
            logger.exception("[ORCH] failed to process message_id=%s", item.message_id)

    logger.info("[ORCH] run_once finished: %d/%d items processed", processed, len(items))

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from notion_client import Client

from app.classify import ClassifyResult
from app.config import settings
from app.pull import PendingItem

logger = logging.getLogger("notion_writer")

# Notion API のレート制限(平均 3 req/sec)対策。連続呼び出しの間隔を最低 0.34 秒空ける。
_MIN_INTERVAL = 0.34
_last_call = 0.0
_throttle_lock = threading.Lock()


def _throttle() -> None:
    global _last_call
    with _throttle_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()

# 設計タスク管理 DB の既存プロパティ名。けいすけの実地確認で実際の名称と照合し、
# 相違があればここだけ直せば済むように定数化している。
PROP_TITLE = "タスク名"
PROP_PRIORITY = "優先度"
PROP_NOTE = "備考"
PROP_ONEDRIVE = "OneDrive"
PRIORITY_PENDING = "仕分け待ち"

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(auth=settings.notion_api_key)
    return _client


def _build_note(item: PendingItem, result: ClassifyResult) -> str:
    related = ", ".join(result.related_message_ids) if result.related_message_ids else "（なし）"
    return (
        "[Claude 推測]\n"
        f"案件候補: {result.case_name or '（候補なし）'}\n"
        f"確信度: {result.confidence:.2f}\n"
        f"判断理由: {result.reasoning}\n"
        f"関連メッセージ: {related}\n"
        f"LINE messageId: {item.message_id}\n"
        f"LINE groupId: {item.group_id}\n"
        f"GCS path: {item.gcs_path or '（なし）'}\n"
    )


def create_pending_task(item: PendingItem, result: ClassifyResult) -> str:
    date_str = item.received_at.date().isoformat()
    task_name = f"【LINE】{date_str} {result.title}"
    properties = {
        PROP_TITLE: {"title": [{"text": {"content": task_name}}]},
        PROP_PRIORITY: {"select": {"name": PRIORITY_PENDING}},
        PROP_NOTE: {"rich_text": [{"text": {"content": _build_note(item, result)}}]},
    }
    _throttle()
    page = _get_client().pages.create(
        parent={"database_id": settings.notion_database_id_design_task},
        properties=properties,
    )
    logger.info("[NOTION] created task %s (page=%s)", task_name, page["id"])
    return page["id"]


def update_task_with_sharepoint_link(page_id: str, sharepoint_url: str) -> None:
    _throttle()
    _get_client().pages.update(
        page_id=page_id,
        properties={PROP_ONEDRIVE: {"url": sharepoint_url}},
    )
    logger.info("[NOTION] updated page %s with SharePoint link", page_id)


def fetch_case_candidates() -> list[str]:
    """設計タスク管理 DB から「仕分け待ち」以外・直近 N 日以内のタスク名を仕分け候補として取得。"""
    since = (datetime.now(timezone.utc) - timedelta(days=settings.candidate_lookback_days)).isoformat()
    query_filter = {
        "and": [
            {"property": PROP_PRIORITY, "select": {"does_not_equal": PRIORITY_PENDING}},
            {"timestamp": "created_time", "created_time": {"on_or_after": since}},
        ]
    }

    candidates: list[str] = []
    cursor: str | None = None
    while True:
        kwargs = {
            "database_id": settings.notion_database_id_design_task,
            "filter": query_filter,
            "page_size": 100,
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        _throttle()
        resp = _get_client().databases.query(**kwargs)

        for page in resp.get("results", []):
            title_prop = page.get("properties", {}).get(PROP_TITLE, {}).get("title", [])
            name = "".join(part.get("plain_text", "") for part in title_prop).strip()
            if name:
                candidates.append(name)

        if resp.get("has_more"):
            cursor = resp.get("next_cursor")
        else:
            break

    logger.info("[NOTION] fetched %d case candidates", len(candidates))
    return candidates

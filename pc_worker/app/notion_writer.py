import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from notion_client import Client

from app.config import settings

logger = logging.getLogger("notion_writer")

# 設計タスク管理 DB の既存プロパティ名。けいすけの実地確認で実際の名称と照合し、
# 相違があればここだけ直せば済むように定数化している。
PROP_TITLE = "タスク名"
PROP_PRIORITY = "優先度"
PROP_NOTE = "備考"
PROP_ONEDRIVE = "OneDrive"
PRIORITY_PENDING = "仕分け待ち"

# Notion API のレート制限(平均 3 req/sec)対策。連続呼び出しの間隔を最低 0.34 秒空ける。
_MIN_INTERVAL = 0.34
_last_call = 0.0
_throttle_lock = threading.Lock()

_client: Client | None = None


def _throttle() -> None:
    global _last_call
    with _throttle_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(auth=settings.notion_api_key)
    return _client


def _title_text(page: dict) -> str:
    title_prop = page.get("properties", {}).get(PROP_TITLE, {}).get("title", [])
    return "".join(part.get("plain_text", "") for part in title_prop).strip()


def _compose_note(case: str | None, note: str | None) -> str:
    text = note or ""
    if case:
        text = f"案件: {case}\n{text}".strip()
    return text


def write_task(
    case: str,
    title: str,
    priority: str = PRIORITY_PENDING,
    note: str | None = None,
    onedrive_link: str | None = None,
) -> dict:
    """設計タスク管理 DB に row を新規作成。案件名は備考に記録する（案件プロパティは実 DB 未確認のため）。"""
    properties: dict = {
        PROP_TITLE: {"title": [{"text": {"content": title}}]},
        PROP_PRIORITY: {"select": {"name": priority}},
    }
    note_text = _compose_note(case, note)
    if note_text:
        properties[PROP_NOTE] = {"rich_text": [{"text": {"content": note_text}}]}
    if onedrive_link:
        properties[PROP_ONEDRIVE] = {"url": onedrive_link}

    _throttle()
    page = _get_client().pages.create(
        parent={"database_id": settings.notion_database_id_design_task},
        properties=properties,
    )
    logger.info("[NOTION] created task '%s' (page=%s)", title, page["id"])
    return {"page_id": page["id"], "url": page.get("url", "")}


def update_task(
    page_id: str,
    case: str | None = None,
    title: str | None = None,
    priority: str | None = None,
    note: str | None = None,
    onedrive_link: str | None = None,
) -> dict:
    """既存 row を部分更新。指定したフィールドのみ更新する。"""
    properties: dict = {}
    updated: list[str] = []

    if title is not None:
        properties[PROP_TITLE] = {"title": [{"text": {"content": title}}]}
        updated.append("title")
    if priority is not None:
        properties[PROP_PRIORITY] = {"select": {"name": priority}}
        updated.append("priority")
    if case is not None or note is not None:
        properties[PROP_NOTE] = {"rich_text": [{"text": {"content": _compose_note(case, note)}}]}
        if case is not None:
            updated.append("case")
        if note is not None:
            updated.append("note")
    if onedrive_link is not None:
        properties[PROP_ONEDRIVE] = {"url": onedrive_link}
        updated.append("onedrive_link")

    _throttle()
    _get_client().pages.update(page_id=page_id, properties=properties)
    logger.info("[NOTION] updated page %s fields=%s", page_id, updated)
    return {"page_id": page_id, "updated_fields": updated}


def list_cases(days: int = 90) -> list[dict]:
    """直近 N 日に更新があったタスクから案件名候補を集約して返す。

    案件名は現状タスク名（PROP_TITLE）を流用（実 DB の案件プロパティ名が未確認のため）。
    同名タスクを 1 案件として件数・最終更新でまとめる。
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query_filter = {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": since}}

    agg: dict[str, dict] = {}
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
            case_name = _title_text(page)
            if not case_name:
                continue
            last_edited = page.get("last_edited_time", "")
            entry = agg.setdefault(case_name, {"case_name": case_name, "last_updated": last_edited, "task_count": 0})
            entry["task_count"] += 1
            if last_edited > entry["last_updated"]:
                entry["last_updated"] = last_edited

        if resp.get("has_more"):
            cursor = resp.get("next_cursor")
        else:
            break

    cases = sorted(agg.values(), key=lambda c: c["last_updated"], reverse=True)
    logger.info("[NOTION] list_cases returned %d cases (days=%d)", len(cases), days)
    return cases

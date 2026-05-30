import hashlib
import hmac
import base64
import logging
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.config import settings

logger = logging.getLogger("line_webhook")
router = APIRouter()

TMP_DIR = Path(__file__).resolve().parent.parent / "tmp"

EXT_MAP = {
    "image": ".jpg",
    "video": ".mp4",
    "audio": ".m4a",
}


def verify_signature(body: bytes, signature: str) -> bool:
    digest = hmac.new(
        settings.line_channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode("utf-8"), signature)


def _download_content_bytes(message_id: str) -> bytes:
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {settings.line_channel_access_token}"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content


def _ext_for_file_message(event: dict) -> str:
    file_name = event.get("message", {}).get("fileName", "")
    if "." in file_name:
        return "." + file_name.rsplit(".", 1)[1].lower()
    return ".bin"


def _save_local(data: bytes, message_id: str, ext: str) -> Path:
    TMP_DIR.mkdir(exist_ok=True)
    timestamp = int(time.time())
    dest = TMP_DIR / f"{timestamp}_{message_id}{ext}"
    dest.write_bytes(data)
    logger.info("[LOCAL] saved %s (%d bytes)", dest.name, len(data))
    return dest


# インスタンス内で「このグループのグループ名は intake_groups に保存済み」を覚える集合。
# summary API と Firestore 書込を group あたり 1 回に抑える。
_group_synced: set[str] = set()


def _record_group_name(group_id: str) -> None:
    """グループ名を best-effort 解決して intake_groups に保存（インスタンス内で 1 group 1 回）。"""
    if settings.local_fallback or not group_id or group_id == "N/A" or group_id in _group_synced:
        return
    try:
        from app.profile import resolve_group_name
        from app.firestore import set_group_name
        name = resolve_group_name(group_id)
        if name:
            set_group_name(group_id, name)
            _group_synced.add(group_id)
    except Exception:
        logger.warning("[GROUP] group name 解決/保存に失敗 group=%s", group_id)


def _enrich_after_save(message_id: str, group_id: str, user_id: str | None) -> None:
    """メッセージ保存『後』に走る best-effort のエンリッチ（送信者表示名・グループ名）。

    ★ 重要: LINE プロフィール/グループ summary の HTTP 呼び出しはここ（=record_message より後）でだけ行う。
    Cloud Run のレスポンス後 CPU スロットルで本タスクが途中で止まっても、メッセージ保存自体は
    既に完了しているので取りこぼさない（2026-05-31 の取り込み欠落バグの恒久対策）。
    失敗・タイムアウトは握りつぶす。
    """
    if settings.local_fallback:
        return
    try:
        from app.profile import resolve_display_name
        from app.firestore import update_message
        name = resolve_display_name(group_id, user_id)
        if name:
            update_message(message_id, {"senderDisplayName": name})
    except Exception:
        logger.warning("[ENRICH] senderDisplayName 解決/保存に失敗 msg=%s", message_id)
    _record_group_name(group_id)


def _store_media(
    data: bytes,
    message_id: str,
    ext: str,
    group_id: str,
    msg_type: str,
    file_name: str | None,
    user_id: str | None = None,
) -> None:
    try:
        if settings.local_fallback:
            _save_local(data, message_id, ext)
        else:
            from app.gcs import upload_to_pending
            from app.firestore import record_message
            gcs_path = upload_to_pending(data, message_id, ext)
            meta = {
                "groupId": group_id,
                "type": msg_type,
                "status": "pending",
                "gcsPath": gcs_path,
            }
            if file_name:
                meta["fileName"] = file_name
            if user_id:
                meta["senderUserId"] = user_id  # userId はイベント内＝HTTP 不要。表示名は保存後に付与
            record_message(message_id, meta)
            _enrich_after_save(message_id, group_id, user_id)
    except Exception:
        logger.exception("[STORE] failed to store media message_id=%s", message_id)


def _store_metadata(event: dict) -> None:
    try:
        event_type = event.get("type", "")
        source = event.get("source", {})
        group_id = source.get("groupId", "N/A")

        if event_type == "join":
            logger.info("[JOIN] groupId=%s", group_id)
            if not settings.local_fallback:
                from app.firestore import upsert_group, record_message
                upsert_group(group_id)
                record_message(
                    f"join_{group_id}_{int(time.time())}",
                    {
                        "groupId": group_id,
                        "type": "join",
                        "status": "done",
                    },
                )
                _record_group_name(group_id)
            return

        if event_type != "message":
            return

        msg = event.get("message", {})
        msg_type = msg.get("type", "")
        msg_id = msg.get("id", "")

        if msg_type == "text":
            text = msg.get("text", "")
            logger.info("[TEXT] groupId=%s text=%s", group_id, text)
            if not settings.local_fallback:
                from app.firestore import record_message
                user_id = source.get("userId")
                meta = {
                    "groupId": group_id,
                    "type": "text",
                    "text": text,
                    "status": "done",
                }
                if user_id:
                    meta["senderUserId"] = user_id  # userId はイベント内＝HTTP 不要
                # 保存を最優先（HTTP より前）。表示名・グループ名は保存後に best-effort。
                record_message(msg_id, meta)
                _enrich_after_save(msg_id, group_id, user_id)
    except Exception:
        logger.exception("[STORE] failed to store metadata for event type=%s", event.get("type"))


@router.post("/line/webhook")
async def line_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not verify_signature(body, signature):
        logger.warning("[SIGNATURE] verification failed")
        return Response(status_code=400, content="Bad signature")

    payload = await request.json()
    events = payload.get("events", [])

    downloads: list[tuple[bytes, str, str, str, str, str | None, str | None]] = []

    for event in events:
        event_type = event.get("type", "")
        if event_type == "message":
            msg = event.get("message", {})
            msg_type = msg.get("type", "")
            msg_id = msg.get("id", "")
            if msg_type in ("image", "video", "audio", "file"):
                ext = EXT_MAP.get(msg_type) or _ext_for_file_message(event)
                source = event.get("source", {})
                group_id = source.get("groupId", "N/A")
                user_id = source.get("userId")
                file_name = msg.get("fileName") if msg_type == "file" else None
                data = _download_content_bytes(msg_id)
                downloads.append((data, msg_id, ext, group_id, msg_type, file_name, user_id))
                continue

        background_tasks.add_task(_store_metadata, event)

    for data, msg_id, ext, group_id, msg_type, file_name, user_id in downloads:
        background_tasks.add_task(_store_media, data, msg_id, ext, group_id, msg_type, file_name, user_id)

    return Response(status_code=200, content="OK")

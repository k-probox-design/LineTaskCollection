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
            from app.profile import sender_fields
            gcs_path = upload_to_pending(data, message_id, ext)
            meta = {
                "groupId": group_id,
                "type": msg_type,
                "status": "pending",
                "gcsPath": gcs_path,
            }
            if file_name:
                meta["fileName"] = file_name
            meta.update(sender_fields(group_id, user_id))
            record_message(message_id, meta)
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
                from app.profile import sender_fields
                meta = {
                    "groupId": group_id,
                    "type": "text",
                    "text": text,
                    "status": "done",
                }
                meta.update(sender_fields(group_id, source.get("userId")))
                record_message(msg_id, meta)
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

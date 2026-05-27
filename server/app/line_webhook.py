import hashlib
import hmac
import base64
import logging
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Request, Response

from app.config import settings

logger = logging.getLogger("line_webhook")
router = APIRouter()

TMP_DIR = Path(__file__).resolve().parent.parent / "tmp"
TMP_DIR.mkdir(exist_ok=True)

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


async def download_content(message_id: str, ext: str) -> Path:
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {settings.line_channel_access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.content

    timestamp = int(time.time())
    dest = TMP_DIR / f"{timestamp}_{message_id}{ext}"
    dest.write_bytes(data)
    logger.info("[DOWNLOAD] saved %s (%d bytes)", dest.name, len(data))
    return dest


def _ext_for_file_message(event: dict) -> str:
    file_name = event.get("message", {}).get("fileName", "")
    if "." in file_name:
        return "." + file_name.rsplit(".", 1)[1].lower()
    return ".bin"


@router.post("/line/webhook")
async def line_webhook(request: Request) -> Response:
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not verify_signature(body, signature):
        logger.warning("[SIGNATURE] verification failed")
        return Response(status_code=400, content="Bad signature")

    payload = await request.json()
    events = payload.get("events", [])

    for event in events:
        event_type = event.get("type", "")
        source = event.get("source", {})
        group_id = source.get("groupId", "N/A")

        if event_type == "join":
            logger.info("[JOIN] groupId=%s", group_id)
            continue

        if event_type == "message":
            msg = event.get("message", {})
            msg_type = msg.get("type", "")
            msg_id = msg.get("id", "")

            if msg_type == "text":
                text = msg.get("text", "")
                logger.info("[TEXT] groupId=%s text=%s", group_id, text)
                continue

            if msg_type in ("image", "video", "audio"):
                ext = EXT_MAP.get(msg_type, ".bin")
                await download_content(msg_id, ext)
                continue

            if msg_type == "file":
                ext = _ext_for_file_message(event)
                await download_content(msg_id, ext)
                continue

    return Response(status_code=200, content="OK")

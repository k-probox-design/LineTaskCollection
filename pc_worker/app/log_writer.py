import logging
from datetime import datetime, timedelta, timezone

from google.cloud import firestore

from app.config import settings

logger = logging.getLogger("log_writer")

_fs_client: firestore.Client | None = None


def _firestore() -> firestore.Client:
    global _fs_client
    if _fs_client is None:
        _fs_client = firestore.Client(project=settings.firestore_project)
    return _fs_client


def _query_group_messages(group_id: str):
    return (
        _firestore()
        .collection("intake_messages")
        .where(filter=firestore.FieldFilter("groupId", "==", group_id))
        .stream()
    )


def build_session_log(group_id: str, around: datetime, window_hours: int = 24) -> str:
    """同 groupId 内で around 前後 window_hours 時間の text/file イベントを時系列でまとめた Markdown を返す。

    Phase C' では Cowork が議事ログ Markdown を組み立て pc_cli write-log に渡すため、
    本関数は CLI からは直接呼ばれない。Firestore からの集約が必要になったとき流用するために残置。
    """
    start = around - timedelta(hours=window_hours)
    end = around + timedelta(hours=window_hours)

    rows = []
    for doc in _query_group_messages(group_id):
        data = doc.to_dict() or {}
        received = data.get("receivedAt")
        if received is None:
            continue
        if isinstance(received, datetime) and received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        if not (start <= received <= end):
            continue
        rows.append((received, data))

    rows.sort(key=lambda r: r[0])

    lines = [
        f"# {around.date().isoformat()} 議事ログ",
        "",
        f"対象 LINE グループ: {group_id}",
        f"対象時刻範囲: {start.isoformat()} 〜 {end.isoformat()}",
        "",
        "---",
        "",
    ]
    for received, data in rows:
        ts = received.strftime("%Y-%m-%d %H:%M")
        msg_type = data.get("type", "")
        if msg_type == "text":
            lines.append(f"## {ts} [テキスト]")
            lines.append("")
            lines.append(data.get("text", ""))
            lines.append("")
        elif msg_type in ("image", "file", "video", "audio"):
            file_name = data.get("fileName") or f"{msg_type}"
            lines.append(f"## {ts} [ファイル: {file_name}]")
            lines.append("")
            lines.append(f"→ ../09.受領資料/{file_name}")
            lines.append("")

    return "\n".join(lines)

import logging
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import firestore, storage

from app.config import settings

logger = logging.getLogger("pull")

_fs_client: firestore.Client | None = None
_gcs_client: storage.Client | None = None

# Firestore のフィールド名 → 出力キーの対応（任意項目。未収集なら欠落）
# senderUserId / senderDisplayName は Phase B 拡張（2026-05-30）で Cloud Run 受信側が保存。
# 本対応より前に受信したメッセージは持たない（遡及不可）。
_OPTIONAL_FIELDS = {
    "senderUserId": "sender_user_id",
    "senderDisplayName": "sender_display_name",
    "mimeType": "mime_type",
    "sizeBytes": "size_bytes",
}


def _firestore() -> firestore.Client:
    global _fs_client
    if _fs_client is None:
        _fs_client = firestore.Client(project=settings.firestore_project)
    return _fs_client


def _gcs() -> storage.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client(project=settings.firestore_project)
    return _gcs_client


def _ext_from(gcs_path: str | None, file_name: str | None) -> str:
    source = gcs_path or file_name or ""
    if "." in source:
        return source.rsplit(".", 1)[1].lower()
    return "bin"


def _parse_gcs_path(gcs_path: str) -> tuple[str, str]:
    without_scheme = gcs_path.removeprefix("gs://")
    bucket, _, blob = without_scheme.partition("/")
    return bucket, blob


def _doc_to_meta(doc) -> dict:
    data = doc.to_dict() or {}
    received = data.get("receivedAt")
    timestamp = received.isoformat() if isinstance(received, datetime) else None
    meta = {
        "doc_id": doc.id,
        "type": data.get("type"),
        "group_id": data.get("groupId"),
        "timestamp": timestamp,
        "gcs_path": data.get("gcsPath"),
        "file_name": data.get("fileName"),
        "text_content": data.get("text"),
    }
    for src_key, out_key in _OPTIONAL_FIELDS.items():
        if src_key in data:
            meta[out_key] = data[src_key]
    return {k: v for k, v in meta.items() if v is not None}


def list_pending(limit: int = 50) -> list[dict]:
    """Firestore intake_messages の status=pending を最大 N 件、メタのみ取得（GCS は触らない）。"""
    docs = (
        _firestore()
        .collection("intake_messages")
        .where(filter=firestore.FieldFilter("status", "==", "pending"))
        .limit(limit)
        .stream()
    )
    items = [_doc_to_meta(d) for d in docs]
    logger.info("[PULL] list_pending returned %d items (limit=%d)", len(items), limit)
    return items


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _msg_to_entry(doc) -> dict:
    data = doc.to_dict() or {}
    received = data.get("receivedAt")
    entry = {
        "doc_id": doc.id,
        "group_id": data.get("groupId"),
        "received_at": _as_utc(received).isoformat() if isinstance(received, datetime) else None,
        # 受信側は `type` で保存するが、念のため messageType も見る
        "message_type": data.get("type") or data.get("messageType"),
        "text": data.get("text"),
        "status": data.get("status"),
        "file_name": data.get("fileName"),
        "has_gcs": bool(data.get("gcsPath")),
    }
    for src_key, out_key in _OPTIONAL_FIELDS.items():
        if src_key in data:
            entry[src_key] = data[src_key]
    # senderUserId 等は _OPTIONAL_FIELDS のキーで入るので出力キーに正規化
    return {_OPTIONAL_FIELDS.get(k, k): v for k, v in entry.items() if v is not None}


def list_since(since_iso: str | None, limit: int = 1000) -> list[dict]:
    """intake_messages を receivedAt 昇順で、since_iso より新しいものを返す（全グループ横断）。

    since_iso が None なら全件（初回バックフィル）。各要素は _msg_to_entry 形式。
    """
    col = _firestore().collection("intake_messages")
    if since_iso is None:
        docs = col.order_by("receivedAt").limit(limit).stream()
    else:
        since = _as_utc(datetime.fromisoformat(since_iso))
        docs = (
            col.where(filter=firestore.FieldFilter("receivedAt", ">", since))
            .order_by("receivedAt")
            .limit(limit)
            .stream()
        )
    items = [_msg_to_entry(d) for d in docs]
    logger.info("[PULL] list_since since=%s returned %d (limit=%d)", since_iso, len(items), limit)
    return items


def list_messages(
    group_id: str,
    around_doc: str | None = None,
    since: str | None = None,
    until: str | None = None,
    window_hours: int = 48,
    limit: int = 200,
) -> list[dict]:
    """同一グループの前後メッセージを時系列（昇順）で返す。関連/非関連の判断は持たない。

    時間範囲: around_doc 指定時はその receivedAt を中心に ±window_hours。
    それ以外は since/until（ISO8601）があれば使い、無ければ範囲無制限（最新 limit 件）。
    """
    from datetime import timedelta

    start: datetime | None = None
    end: datetime | None = None
    if around_doc:
        snap = _firestore().collection("intake_messages").document(around_doc).get()
        if not snap.exists:
            raise ValueError(f"around-doc not found: {around_doc}")
        center = (snap.to_dict() or {}).get("receivedAt")
        if not isinstance(center, datetime):
            raise ValueError(f"around-doc has no receivedAt: {around_doc}")
        center = _as_utc(center)
        start, end = center - timedelta(hours=window_hours), center + timedelta(hours=window_hours)
    else:
        if since:
            start = _as_utc(datetime.fromisoformat(since))
        if until:
            end = _as_utc(datetime.fromisoformat(until))

    docs = (
        _firestore()
        .collection("intake_messages")
        .where(filter=firestore.FieldFilter("groupId", "==", group_id))
        .stream()
    )

    rows: list[tuple[datetime, object]] = []
    for d in docs:
        received = (d.to_dict() or {}).get("receivedAt")
        if not isinstance(received, datetime):
            continue
        received = _as_utc(received)
        if start and received < start:
            continue
        if end and received > end:
            continue
        rows.append((received, d))

    rows.sort(key=lambda r: r[0])
    rows = rows[:limit]
    items = [_msg_to_entry(d) for _, d in rows]

    # グループ名（intake_groups.groupName、受信側が解決保存）を各要素に付与。無ければ付けない。
    group_name = _group_name(group_id)
    if group_name:
        for it in items:
            it["group_name"] = group_name

    logger.info(
        "[PULL] list_messages group=%s (%s) returned %d (around=%s, window=%dh, limit=%d)",
        group_id, group_name, len(items), around_doc, window_hours, limit,
    )
    return items


def _group_name(group_id: str) -> str | None:
    """intake_groups/{groupId}.groupName を引く。未取得なら None。"""
    try:
        snap = _firestore().collection("intake_groups").document(group_id).get()
        if snap.exists:
            return (snap.to_dict() or {}).get("groupName")
    except Exception:
        logger.warning("[PULL] intake_groups の groupName 取得に失敗 group=%s", group_id)
    return None


def get_meta(doc_id: str) -> dict:
    """単一 doc のメタを取得（GCS は触らない）。list_pending と同じ整形（_doc_to_meta）で返す。

    存在しなければ ValueError。send-to-tray が doc 1 件分のメタを取るために使う。
    """
    snap = _firestore().collection("intake_messages").document(doc_id).get()
    if not snap.exists:
        raise ValueError(f"document not found: {doc_id}")
    return _doc_to_meta(snap)


def download(doc_id: str, dest_dir: str) -> Path:
    """doc_id の GCS バイナリを <dest_dir>/<doc_id>.<ext> にダウンロードしてパスを返す。"""
    snap = _firestore().collection("intake_messages").document(doc_id).get()
    if not snap.exists:
        raise ValueError(f"document not found: {doc_id}")
    data = snap.to_dict() or {}
    gcs_path = data.get("gcsPath")
    if not gcs_path:
        raise ValueError(f"document has no gcsPath: {doc_id}")

    ext = _ext_from(gcs_path, data.get("fileName"))
    dest_path = Path(dest_dir)
    dest_path.mkdir(parents=True, exist_ok=True)
    dest = dest_path / f"{doc_id}.{ext}"

    bucket, blob = _parse_gcs_path(gcs_path)
    _gcs().bucket(bucket).blob(blob).download_to_filename(str(dest))
    logger.info("[PULL] downloaded %s -> %s", gcs_path, dest)
    return dest


def mark_done(doc_id: str) -> dict:
    """SharePoint 格納完了後: GCS の一時ファイルを削除し Firestore を done に更新。"""
    doc_ref = _firestore().collection("intake_messages").document(doc_id)
    snap = doc_ref.get()
    gcs_deleted = False
    if snap.exists:
        gcs_path = (snap.to_dict() or {}).get("gcsPath")
        if gcs_path:
            bucket, blob = _parse_gcs_path(gcs_path)
            try:
                _gcs().bucket(bucket).blob(blob).delete()
                gcs_deleted = True
            except Exception:
                logger.warning("[PULL] GCS delete failed for %s", gcs_path)
    doc_ref.update({"status": "done"})
    logger.info("[PULL] mark_done %s (gcs_deleted=%s)", doc_id, gcs_deleted)
    return {"doc_id": doc_id, "status": "done", "gcs_deleted": gcs_deleted}


def mark_review(doc_id: str, reason: str | None = None) -> dict:
    """確信度が低い: Firestore を needs_review に更新（GCS は保持）。"""
    update: dict = {"status": "needs_review"}
    if reason:
        update["reviewReason"] = reason
    _firestore().collection("intake_messages").document(doc_id).update(update)
    logger.info("[PULL] mark_review %s (reason=%s)", doc_id, reason)
    return {"doc_id": doc_id, "status": "needs_review", "reason": reason}

import logging
from datetime import datetime
from pathlib import Path

from google.cloud import firestore, storage

from app.config import settings

logger = logging.getLogger("pull")

_fs_client: firestore.Client | None = None
_gcs_client: storage.Client | None = None

# Firestore のフィールド名 → pull-pending 出力キーの対応（任意項目。Phase B 未収集なら欠落）
_OPTIONAL_FIELDS = {
    "userId": "user_id",
    "userDisplayName": "user_display_name",
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

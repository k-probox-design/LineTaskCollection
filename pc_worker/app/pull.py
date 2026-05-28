import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from google.cloud import firestore, storage

from app.config import settings

logger = logging.getLogger("pull")

_fs_client: firestore.Client | None = None
_gcs_client: storage.Client | None = None


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


@dataclass
class PendingItem:
    message_id: str
    group_id: str
    type: str
    gcs_path: str | None = None
    text: str | None = None
    file_name: str | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    content_bytes: bytes | None = None

    @property
    def is_media(self) -> bool:
        return self.type in ("image", "video", "audio", "file")

    @property
    def ext(self) -> str:
        """拡張子(先頭ドットなし)を gcs_path → file_name の順で導出する。"""
        source = self.gcs_path or self.file_name or ""
        if "." in source:
            return source.rsplit(".", 1)[1].lower()
        return "bin"


def _parse_gcs_path(gcs_path: str) -> tuple[str, str]:
    """gs://bucket/blob/path → (bucket, blob)。"""
    without_scheme = gcs_path.removeprefix("gs://")
    bucket, _, blob = without_scheme.partition("/")
    return bucket, blob


def _download_bytes(gcs_path: str) -> bytes:
    bucket_name, blob_name = _parse_gcs_path(gcs_path)
    blob = _gcs().bucket(bucket_name).blob(blob_name)
    return blob.download_as_bytes()


def pull_pending() -> list[PendingItem]:
    """Firestore intake_messages の status=pending を全件取得。メディアは GCS 本体も pull。"""
    docs = (
        _firestore()
        .collection("intake_messages")
        .where(filter=firestore.FieldFilter("status", "==", "pending"))
        .stream()
    )

    items: list[PendingItem] = []
    for doc in docs:
        data = doc.to_dict() or {}
        item = PendingItem(
            message_id=doc.id,
            group_id=data.get("groupId", ""),
            type=data.get("type", ""),
            gcs_path=data.get("gcsPath"),
            text=data.get("text"),
            file_name=data.get("fileName"),
            received_at=data.get("receivedAt") or datetime.now(timezone.utc),
        )
        if item.is_media and item.gcs_path:
            item.content_bytes = _download_bytes(item.gcs_path)
        items.append(item)

    logger.info("[PULL] fetched %d pending items", len(items))
    return items


def mark_done_and_cleanup(item: PendingItem, final_path: str | None = None) -> None:
    """SharePoint 格納完了後: GCS の一時ファイルを削除し Firestore を done に更新。"""
    if item.gcs_path:
        bucket_name, blob_name = _parse_gcs_path(item.gcs_path)
        _gcs().bucket(bucket_name).blob(blob_name).delete()
        logger.info("[CLEANUP] deleted %s", item.gcs_path)

    update: dict = {"status": "done"}
    if final_path:
        update["finalPath"] = final_path
    _firestore().collection("intake_messages").document(item.message_id).update(update)
    logger.info("[DONE] intake_messages/%s status=done", item.message_id)


def mark_review_only(item: PendingItem) -> None:
    """確信度が低い: Firestore を needs_review に更新(GCS は保持して再処理に備える)。"""
    _firestore().collection("intake_messages").document(item.message_id).update(
        {"status": "needs_review"}
    )
    logger.info("[REVIEW] intake_messages/%s status=needs_review", item.message_id)

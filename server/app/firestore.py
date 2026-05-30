import logging
from datetime import datetime, timezone

from google.cloud import firestore

from app.config import settings

logger = logging.getLogger("firestore")

_client: firestore.Client | None = None


def _get_client() -> firestore.Client:
    global _client
    if _client is None:
        _client = firestore.Client(project=settings.firestore_project)
    return _client


def upsert_group(group_id: str) -> None:
    doc_ref = _get_client().collection("intake_groups").document(group_id)
    doc_ref.set(
        {
            "registeredAt": datetime.now(timezone.utc),
            "caseName": None,
            "sharepointFolder": None,
        },
        merge=True,
    )
    logger.info("[FIRESTORE] upsert intake_groups/%s", group_id)


def set_group_name(group_id: str, group_name: str) -> None:
    """intake_groups/{groupId} に LINE グループ名を保存（merge）。caseName 等は壊さない。"""
    _get_client().collection("intake_groups").document(group_id).set(
        {"groupName": group_name}, merge=True
    )
    logger.info("[FIRESTORE] set intake_groups/%s groupName", group_id)


def record_message(message_id: str, meta: dict) -> None:
    doc_ref = _get_client().collection("intake_messages").document(message_id)
    meta.setdefault("receivedAt", datetime.now(timezone.utc))
    doc_ref.set(meta)
    logger.info("[FIRESTORE] recorded intake_messages/%s", message_id)


def update_message(message_id: str, fields: dict) -> None:
    """既存メッセージ doc に後追いでフィールドを足す（merge）。送信者表示名の事後付与に使う。"""
    _get_client().collection("intake_messages").document(message_id).set(fields, merge=True)
    logger.info("[FIRESTORE] updated intake_messages/%s %s", message_id, list(fields))

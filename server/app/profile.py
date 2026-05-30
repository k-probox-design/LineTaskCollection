import logging

import httpx

from app.config import settings

logger = logging.getLogger("profile")

# (groupId, userId) -> displayName の短期キャッシュ。インスタンス常駐中だけ使い回す
# （min-instances=1 なので実用上ほぼ効く）。失敗はキャッシュしない。
_cache: dict[tuple[str, str], str] = {}

# groupId -> groupName の短期キャッシュ（同上）
_group_cache: dict[str, str] = {}


def resolve_display_name(group_id: str | None, user_id: str | None) -> str | None:
    """送信者の表示名を LINE プロフィール API で best-effort 解決する。

    グループ送信者は group member profile、1:1 は profile を叩く。失敗時は None
    （呼び出し側は userId のみ保存にフォールバック）。受信本処理を止めないため例外は飲む。
    """
    if not user_id:
        return None
    key = (group_id or "", user_id)
    if key in _cache:
        return _cache[key]

    if group_id and group_id != "N/A":
        url = f"https://api.line.me/v2/bot/group/{group_id}/member/{user_id}"
    else:
        url = f"https://api.line.me/v2/bot/profile/{user_id}"
    headers = {"Authorization": f"Bearer {settings.line_channel_access_token}"}

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            name = resp.json().get("displayName")
    except Exception:
        logger.warning("[PROFILE] displayName 解決に失敗 group=%s user=%s", group_id, user_id)
        return None

    if name:
        _cache[key] = name
    return name


def resolve_group_name(group_id: str | None) -> str | None:
    """グループのトークルーム名を LINE group summary API で best-effort 解決する。

    `GET /v2/bot/group/{groupId}/summary` の `groupName` を採る。room/1:1（groupId 無し＝"N/A"）は
    summary が無いので None。失敗（403/404/タイムアウト等）も None（受信本処理は止めない）。
    """
    if not group_id or group_id == "N/A":
        return None
    if group_id in _group_cache:
        return _group_cache[group_id]

    url = f"https://api.line.me/v2/bot/group/{group_id}/summary"
    headers = {"Authorization": f"Bearer {settings.line_channel_access_token}"}
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            name = resp.json().get("groupName")
    except Exception:
        logger.warning("[PROFILE] groupName 解決に失敗 group=%s", group_id)
        return None

    if name:
        _group_cache[group_id] = name
    return name


def sender_fields(group_id: str | None, user_id: str | None) -> dict:
    """Firestore に保存する送信者フィールド（senderUserId / senderDisplayName）を組み立てる。

    userId が無ければ空。表示名解決に失敗したら userId のみ（遡及不可・best-effort 設計）。
    """
    if not user_id:
        return {}
    fields = {"senderUserId": user_id}
    name = resolve_display_name(group_id, user_id)
    if name:
        fields["senderDisplayName"] = name
    return fields

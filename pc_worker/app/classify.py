import base64
import logging

import anthropic
from pydantic import BaseModel

from app.config import settings
from app.pull import PendingItem

logger = logging.getLogger("classify")

_client: anthropic.Anthropic | None = None

_IMAGE_MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}

_SYSTEM_PROMPT = """あなたは設計事務所のアシスタントです。LINE グループで受信したファイル（見積書・図面・写真など）や\
テキストを、既存の案件に振り分け、内容を表すタイトルを推測します。

# 判断の手がかり
- ファイルの中身（画像・PDF はそのまま読める）
- ファイル名
- 直近のテキストメッセージ
- 同じ LINE グループ（groupId）に紐づく案件名（あれば最優先）
- 受信時刻

# 出力ルール
- case_name: 既存案件候補のいずれか。該当する案件が候補になければ null
- title: 資料の内容を表す簡潔な日本語タイトル（例: 見積書_山田様 / 屋根写真 / 1階平面図）
- confidence: 0.0〜1.0 の確信度。見積書・図面など文字のある資料は高め、文字のない写真は低めになりやすい
- reasoning: なぜその案件・タイトルと判断したかの簡潔な理由
- related_message_ids: 判断の根拠にした関連メッセージ ID（なければ空配列）
"""


class ClassifyResult(BaseModel):
    case_name: str | None
    title: str
    confidence: float
    reasoning: str
    related_message_ids: list[str]


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _build_system(candidates: list[str]) -> list[dict]:
    candidate_lines = "\n".join(f"- {c}" for c in candidates) if candidates else "（候補なし）"
    text = f"{_SYSTEM_PROMPT}\n# 既存案件候補\n{candidate_lines}\n"
    # システムプロンプト+候補リストは 1 回の run 内で不変なので prompt cache でヒットさせる
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _build_user_content(
    item: PendingItem,
    recent_texts: list[str] | None,
    group_case_name: str | None,
) -> list[dict]:
    content: list[dict] = []

    if item.content_bytes:
        data = base64.standard_b64encode(item.content_bytes).decode("utf-8")
        if item.type == "image" or item.ext in _IMAGE_MEDIA_TYPES:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _IMAGE_MEDIA_TYPES.get(item.ext, "image/jpeg"),
                    "data": data,
                },
            })
        elif item.ext == "pdf":
            content.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": data},
            })
        # それ以外のバイナリ（office 等）は本体を送らず、ファイル名と文脈だけで判断する

    context_lines = [
        f"groupId: {item.group_id}",
        f"受信時刻: {item.received_at}",
        f"メッセージ種別: {item.type}",
    ]
    if group_case_name:
        context_lines.append(f"このグループに紐づく案件名: {group_case_name}")
    if item.file_name:
        context_lines.append(f"ファイル名: {item.file_name}")
    if item.text:
        context_lines.append(f"テキスト本文: {item.text}")
    if recent_texts:
        joined = "\n".join(f"- {t}" for t in recent_texts)
        context_lines.append(f"直近のテキストメッセージ:\n{joined}")

    content.append({
        "type": "text",
        "text": "次の受信内容を仕分けしてください。\n" + "\n".join(context_lines),
    })
    return content


def classify(
    item: PendingItem,
    candidates: list[str],
    recent_texts: list[str] | None = None,
    group_case_name: str | None = None,
) -> ClassifyResult:
    response = _get_client().messages.parse(
        model=settings.classify_model,
        max_tokens=1024,
        thinking={"type": "disabled"},
        system=_build_system(candidates),
        messages=[{"role": "user", "content": _build_user_content(item, recent_texts, group_case_name)}],
        output_format=ClassifyResult,
    )

    result = response.parsed_output
    if result is None:
        logger.warning(
            "[CLASSIFY] parse failed for message_id=%s (stop_reason=%s)",
            item.message_id,
            response.stop_reason,
        )
        return ClassifyResult(
            case_name=None,
            title=item.file_name or "（仕分け不能）",
            confidence=0.0,
            reasoning="Claude の構造化出力に失敗したため要確認",
            related_message_ids=[],
        )

    logger.info(
        "[CLASSIFY] message_id=%s case=%s confidence=%.2f",
        item.message_id,
        result.case_name,
        result.confidence,
    )
    return result

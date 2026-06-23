"""タスク管理アプリの「受け渡しトレイ」へ書き出すアダプタ。

LINE 受信メッセージのメタ（Firestore intake_messages）から、タスク管理アプリが
取り込めるトレイ JSON（1 ファイル = タスク 1 件）を組み立てて書き出す。純粋関数中心で、
I/O は write_tray_file の 1 箇所に閉じる（テスト容易性のため）。

トレイ JSON スキーマ（タスク管理アプリ側の契約・厳守）:
  source / source_id / 依頼主 / 内容(必須・非空) / 案件 / 受信(YYYY/MM/DD HH:mm) /
  場所 / 添付(ファイル名の配列) / link / 期限(YYYY-MM-DD) / 要対応(◎/△/－)
注: アプリ側は未知フィールドを無視し、取り込み時に thread を強制的に空配列にする。
    会話ログは thread では送り込めないため「会話ログ」フィールドで持たせる（将来のアプリ
    拡張用の前方互換。現状アプリは無視するので無害）。
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import mounts
from app.config import settings

# 受信(JST)整形用。cli.py の export-results-html と同じ +9h 方式に揃える。
_JST = timezone(timedelta(hours=9))

# 内容に使う text 本文の最大長（先頭からこの字数まで採る）。
_TEXT_SUMMARY_LEN = 40


def _first(meta: dict, *keys: str) -> str | None:
    """meta から最初に見つかった非 None のキーの値を返す。

    pull._doc_to_meta（doc_id/timestamp/text_content/group_id/file_name/
    sender_display_name 等）と list_messages._msg_to_entry（received_at/text/
    group_name 等）の双方のキー名、および計画書記載の生 Firestore キー名（receivedAt/
    fileName/groupName/senderDisplayName/message_id）を吸収する。
    """
    for k in keys:
        v = meta.get(k)
        if v is not None:
            return v
    return None


def _to_jst_string(iso_utc: str | None) -> str:
    """UTC ISO8601 文字列 → JST の 'YYYY/MM/DD HH:mm'。パース不能なら ''。"""
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
    except (ValueError, TypeError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_JST).strftime("%Y/%m/%d %H:%M")


def _content(source_id: str, file_name: str | None, text: str | None) -> str:
    """内容（必須・絶対に空にしない）を組み立てる。

    優先: ファイル名 → text 先頭 N 字（改行は空白化）→ source_id フォールバック。
    """
    if file_name:
        return f"LINE資料受領: {file_name}"
    if text:
        flat = " ".join(text.split())
        if flat:
            return flat[:_TEXT_SUMMARY_LEN]
    return f"LINE受信: {source_id}"


def build_tray_record(
    meta: dict,
    *,
    case: str | None = None,
    placed_file_windows: str | None = None,
    conversation_text: str | None = None,
    needs_review: bool = False,
) -> dict:
    """Firestore intake_messages のメタからトレイ 1 件分の dict を組み立てる。

    meta のキー名は pull.py（_doc_to_meta / _msg_to_entry）の実際の出力に合わせ、
    生 Firestore キーも別名として吸収する（_first 参照）。内容は必ず非空にする。
    """
    source_id = _first(meta, "doc_id", "message_id") or ""
    file_name = _first(meta, "file_name", "fileName")
    text = _first(meta, "text", "text_content")
    received_iso = _first(meta, "received_at", "receivedAt", "timestamp")

    record: dict = {
        "source": "LINE",
        "source_id": source_id,
        "依頼主": _first(meta, "sender_display_name", "senderDisplayName") or "",
        "内容": _content(source_id, file_name, text),
        "案件": case or "",
        "受信": _to_jst_string(received_iso),
        "場所": _first(meta, "group_name", "groupName") or "",
        "添付": [Path(placed_file_windows.replace("\\", "/")).name] if placed_file_windows else [],
        "link": placed_file_windows or "#",
        "期限": "",
        "要対応": "◎" if needs_review else "△",
    }
    if conversation_text:
        # アプリは現状この「会話ログ」を無視する（thread は取り込み時に空配列化される）。
        # 将来アプリが会話ログ表示に対応したときのための前方互換フィールド。
        record["会話ログ"] = conversation_text
    return record


def write_tray_file(record: dict, out_dir: str | Path) -> Path:
    """トレイ JSON を <out_dir>/LINE_<source_id>.json に UTF-8(BOM無し) で書く。

    out_dir は Windows パスで渡されうるので mounts.resolve_to_unix で実マウントへ解決して
    から書く（place-file 等と同じ作法）。out_dir が無ければ作成する。戻り値は書いたパス。
    """
    resolved = mounts.resolve_to_unix(str(out_dir), settings.path_maps)
    out_path = Path(resolved)
    out_path.mkdir(parents=True, exist_ok=True)
    source_id = record.get("source_id") or "unknown"
    dest = out_path / f"LINE_{source_id}.json"
    dest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest

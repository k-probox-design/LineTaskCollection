import logging
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone

from notion_client import Client

from app.config import settings

logger = logging.getLogger("notion_writer")

# 設計タスク管理 DB の既存プロパティ名。けいすけの実地確認で実際の名称と照合し、
# 相違があればここだけ直せば済むように定数化している。
# 注意: タイトル列だけは表示名が空文字 "" 等にドリフトした実績があるため、もはやこの定数では
# 引かない。実行時に type=="title" のプロパティを動的解決する（_get_title_prop_name）。
# 下の PROP_TITLE は「期待される従来名」で、起動時のスキーマ突き合わせ WARN にのみ使う。
PROP_TITLE = "タスク名"
PROP_PRIORITY = "優先度"
PROP_STATUS = "ステータス"
PROP_ASSIGNEE = "担当"
PROP_NOTE = "備考"
PROP_ONEDRIVE = "OneDrive"
PROP_DATE_REGISTERED = "タスク登録日"
PROP_DATE_COMPLETED = "タスク完了日"
PROP_DATE = "日付"
PRIORITY_PENDING = "仕分け待ち"
LINE_TASK_PREFIX = "【LINE】"
# 実 DB 確認(2026-05-30): 優先度 options = 仕分け待ち/すぐ/高/中/低/趣味（"通常" は無い）。
# 完了化は優先度ではなく status 型プロパティ「ステータス」(完了/不要/レイアウト完了/…) で行う。

# ステータス(status 型)の有効値。実 DB 確認(2026-06-15)。status 型は option を API 経由で
# 追加できないため、ここに無い値を送ると Notion が 400 で弾く。update_task は事前に検証して
# 分かりやすく失敗させる（API のエラーを待たない）。
STATUS_OPTIONS = {
    "未着手", "情報待ち",                                  # to_do
    "進行中", "依頼中", "中断中", "中村確認待", "修正依頼済", "社内確認待",  # in_progress
    "レイアウト完了", "不要", "完了",                       # complete
}

# 起動時にスキーマと突き合わせる「期待プロパティ名 → 期待型」。欠落/型相違は WARN だけ出して
# 処理は止めない（列リネーム事故の早期検知用）。タイトルは動的解決するのでここには含めない。
_EXPECTED_PROPS = {
    PROP_PRIORITY: "select",
    PROP_STATUS: "status",
    PROP_ASSIGNEE: "people",
    PROP_NOTE: "rich_text",
    PROP_ONEDRIVE: "url",
    PROP_DATE_REGISTERED: "date",
    PROP_DATE_COMPLETED: "date",
    PROP_DATE: "date",
}

# Notion API のレート制限(平均 3 req/sec)対策。連続呼び出しの間隔を最低 0.34 秒空ける。
_MIN_INTERVAL = 0.34
_last_call = 0.0
_throttle_lock = threading.Lock()

_client: Client | None = None
_data_source_id: str | None = None
_schema_props: dict | None = None
_title_prop_name: str | None = None


def _throttle() -> None:
    global _last_call
    with _throttle_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(auth=settings.notion_api_key)
    return _client


def _get_data_source_id() -> str:
    """設計タスク管理 DB の data_source_id を解決してキャッシュする。

    notion-client 3.x が既定で使う Notion-Version 2025-09-03 では、DB クエリと page 作成が
    DB ではなく「データソース」単位になった（`databases.query` 廃止 → `data_sources.query`、
    page parent は `database_id` → `data_source_id`）。

    `NOTION_DATA_SOURCE_ID` が .env にあればそれを使う。無ければ `databases.retrieve` の
    `data_sources[0]` を採る（当 DB は単一データソース前提。複数データソースを持つようになったら
    この index 0 固定を見直すこと）。
    """
    global _data_source_id
    if _data_source_id:
        return _data_source_id

    env_id = settings.notion_data_source_id
    if env_id:
        _data_source_id = env_id
        return _data_source_id

    _throttle()
    db = _get_client().databases.retrieve(database_id=settings.notion_database_id_design_task)
    sources = db.get("data_sources", [])
    if not sources:
        raise RuntimeError(
            "設計タスク管理 DB に data_sources がありません（Notion-Version 2025-09-03 を期待）"
        )
    _data_source_id = sources[0]["id"]
    logger.info("[NOTION] resolved data_source_id=%s (name=%s)", _data_source_id, sources[0].get("name"))
    return _data_source_id


def _get_schema_props() -> dict:
    """データソースのプロパティスキーマ（{name: {id,name,type,...}}）を取得してキャッシュする。

    初回取得時に期待プロパティとの突き合わせ WARN（_warn_on_schema_drift）も走らせる。
    """
    global _schema_props
    if _schema_props is not None:
        return _schema_props
    _throttle()
    ds = _get_client().data_sources.retrieve(data_source_id=_get_data_source_id())
    _schema_props = ds.get("properties", {}) or {}
    _warn_on_schema_drift(_schema_props)
    return _schema_props


def _warn_on_schema_drift(props: dict) -> None:
    """期待プロパティ名/型がスキーマと食い違っていれば WARN を出す（処理は止めない）。"""
    names = set(props)
    for name, expected_type in _EXPECTED_PROPS.items():
        if name not in names:
            logger.warning(
                "[NOTION] 期待プロパティ '%s'(%s 型) が見つかりません。列名リネームの可能性", name, expected_type
            )
        else:
            actual_type = props[name].get("type")
            if actual_type != expected_type:
                logger.warning(
                    "[NOTION] プロパティ '%s' の型が想定(%s)と異なります: %s", name, expected_type, actual_type
                )


def _get_title_prop_name() -> str:
    """タイトル型(type=="title")プロパティの表示名を動的解決してキャッシュする。

    表示名が空文字 "" 等にドリフトしても追従するための恒久対応（2026-06-15 タイトル列名空文字化）。
    空文字も正規の名前なので None 初期値と区別してキャッシュする。
    """
    global _title_prop_name
    if _title_prop_name is not None:
        return _title_prop_name
    for name, spec in _get_schema_props().items():
        if spec.get("type") == "title":
            _title_prop_name = name
            logger.info("[NOTION] resolved title property name=%r", name)
            return _title_prop_name
    raise RuntimeError("title 型プロパティ未検出（設計タスク管理 DB のスキーマに title 列がありません）")


def _title_text(page: dict) -> str:
    title_prop = page.get("properties", {}).get(_get_title_prop_name(), {}).get("title", [])
    return "".join(part.get("plain_text", "") for part in title_prop).strip()


def _note_text(page: dict) -> str:
    rt = page.get("properties", {}).get(PROP_NOTE, {}).get("rich_text", [])
    return "".join(part.get("plain_text", "") for part in rt).strip()


# 備考の「案件: <値>」行（半角/全角コロン両対応）。find_tasks の突き合わせはこの値だけに限定する。
# 備考“全文”に対して一致させると、[Claude推測] 行の相互参照（対象6拠点: 神戸/…/甲賀/…）に
# 短い拠点名が部分一致して全件ヒットしてしまうため（2026-06-16 ライブ受け入れ指摘）。
_CASE_LINE_RE = re.compile(r"^\s*案件\s*[:：]\s*(.+?)\s*$", re.MULTILINE)


def _case_value(note: str) -> str:
    """備考から『案件: <値>』行の値だけを取り出す。無ければ空文字。"""
    m = _CASE_LINE_RE.search(note or "")
    return m.group(1) if m else ""


def _normalize_for_match(s: str) -> str:
    """fuzzy 一致用の正規化: NFKC（全半角統一）→ 空白除去 → casefold。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", "", s)
    return s.casefold()


def _compose_note(
    case: str | None,
    note: str | None,
    file_name: str | None = None,
    confidence: str | None = None,
) -> str:
    """備考テキストを機械可読な行で組み立てる（export-results-html のパーサと整合）。

    並び: 案件 / ファイル / 確信度 / <自由記述 note（groupId 等を含む）>。
    """
    lines: list[str] = []
    if case:
        lines.append(f"案件: {case}")
    if file_name:
        lines.append(f"ファイル: {file_name}")
    if confidence:
        lines.append(f"確信度: {confidence}")
    if note:
        lines.append(note)
    return "\n".join(lines).strip()


def write_task(
    case: str,
    title: str,
    priority: str | None = None,
    note: str | None = None,
    onedrive_link: str | None = None,
    assignee_user_id: str | None = None,
    file_name: str | None = None,
    confidence: str | None = None,
) -> dict:
    """設計タスク管理 DB に row を新規作成。案件名は備考に記録する（案件プロパティは実 DB 未確認のため）。

    priority 未指定なら既定（NOTION_DEFAULT_PRIORITY、既定値 "Claude追記"＝ボット起因の目印）。
    担当(person)は assignee_user_id か NOTION_DEFAULT_ASSIGNEE_USER_ID をセット（人別ビューに乗せるため）。
    どちらも無ければ担当を触らない（Notion 既定で作成者＝LineTaskBot になる）。
    """
    eff_priority = priority or settings.notion_default_priority
    eff_assignee = assignee_user_id or settings.notion_default_assignee_user_id

    properties: dict = {
        _get_title_prop_name(): {"title": [{"text": {"content": title}}]},
        PROP_PRIORITY: {"select": {"name": eff_priority}},
    }
    if eff_assignee:
        properties[PROP_ASSIGNEE] = {"people": [{"object": "user", "id": eff_assignee}]}
    note_text = _compose_note(case, note, file_name, confidence)
    if note_text:
        properties[PROP_NOTE] = {"rich_text": [{"text": {"content": note_text}}]}
    if onedrive_link:
        properties[PROP_ONEDRIVE] = {"url": onedrive_link}

    _throttle()
    page = _get_client().pages.create(
        parent={"type": "data_source_id", "data_source_id": _get_data_source_id()},
        properties=properties,
    )
    logger.info("[NOTION] created task '%s' (page=%s)", title, page["id"])
    return {"page_id": page["id"], "url": page.get("url", "")}


def update_task(
    page_id: str,
    case: str | None = None,
    title: str | None = None,
    priority: str | None = None,
    note: str | None = None,
    onedrive_link: str | None = None,
    status: str | None = None,
    assignee_user_id: str | None = None,
    completed_date: str | None = None,
) -> dict:
    """既存 row を部分更新。指定したフィールドのみ更新する。完了化は status（ステータス）で。

    completed_date は「タスク完了日」(date 型) を YYYY-MM-DD で設定する（status=完了 と併用しうる）。
    """
    if status is not None and status not in STATUS_OPTIONS:
        # status 型は option を API で増やせない。送る前に弾いて分かりやすく失敗させる。
        valid = " / ".join(sorted(STATUS_OPTIONS))
        logger.warning("[NOTION] 未知のステータス '%s'。有効値: %s", status, valid)
        raise ValueError(f"未知のステータス '{status}'。有効値は次のいずれか: {valid}")

    properties: dict = {}
    updated: list[str] = []

    if title is not None:
        properties[_get_title_prop_name()] = {"title": [{"text": {"content": title}}]}
        updated.append("title")
    if priority is not None:
        properties[PROP_PRIORITY] = {"select": {"name": priority}}
        updated.append("priority")
    if status is not None:
        properties[PROP_STATUS] = {"status": {"name": status}}
        updated.append("status")
    if assignee_user_id is not None:
        properties[PROP_ASSIGNEE] = {"people": [{"object": "user", "id": assignee_user_id}]}
        updated.append("assignee")
    if case is not None or note is not None:
        properties[PROP_NOTE] = {"rich_text": [{"text": {"content": _compose_note(case, note)}}]}
        if case is not None:
            updated.append("case")
        if note is not None:
            updated.append("note")
    if onedrive_link is not None:
        properties[PROP_ONEDRIVE] = {"url": onedrive_link}
        updated.append("onedrive_link")
    if completed_date is not None:
        properties[PROP_DATE_COMPLETED] = {"date": {"start": completed_date}}
        updated.append("completed_date")

    _throttle()
    _get_client().pages.update(page_id=page_id, properties=properties)
    logger.info("[NOTION] updated page %s fields=%s", page_id, updated)
    return {"page_id": page_id, "updated_fields": updated}


def list_cases(days: int = 90) -> list[dict]:
    """直近 N 日に更新があったタスクから案件名候補を集約して返す。

    案件名は現状タスク名（PROP_TITLE）を流用（実 DB の案件プロパティ名が未確認のため）。
    同名タスクを 1 案件として件数・最終更新でまとめる。
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query_filter = {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": since}}
    data_source_id = _get_data_source_id()

    agg: dict[str, dict] = {}
    cursor: str | None = None
    while True:
        kwargs = {
            "data_source_id": data_source_id,
            "filter": query_filter,
            "page_size": 100,
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        _throttle()
        resp = _get_client().data_sources.query(**kwargs)

        for page in resp.get("results", []):
            case_name = _title_text(page)
            if not case_name:
                continue
            last_edited = page.get("last_edited_time", "")
            entry = agg.setdefault(case_name, {"case_name": case_name, "last_updated": last_edited, "task_count": 0})
            entry["task_count"] += 1
            if last_edited > entry["last_updated"]:
                entry["last_updated"] = last_edited

        if resp.get("has_more"):
            cursor = resp.get("next_cursor")
        else:
            break

    cases = sorted(agg.values(), key=lambda c: c["last_updated"], reverse=True)
    logger.info("[NOTION] list_cases returned %d cases (days=%d)", len(cases), days)
    return cases


def list_line_tasks() -> list[dict]:
    """タスク名が【LINE】で始まるページを全件（ページング込み）取得し、生ページを返す。

    needs_review の「仕分け待ち」row も含める（けいすけが未処理も一覧したいため）。
    行データへの変換は results_export.build_rows が担う。
    """
    data_source_id = _get_data_source_id()
    query_filter = {"property": _get_title_prop_name(), "title": {"starts_with": LINE_TASK_PREFIX}}

    pages: list[dict] = []
    cursor: str | None = None
    while True:
        kwargs: dict = {"data_source_id": data_source_id, "filter": query_filter, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        _throttle()
        resp = _get_client().data_sources.query(**kwargs)
        pages.extend(resp.get("results", []))
        if resp.get("has_more"):
            cursor = resp.get("next_cursor")
        else:
            break

    logger.info("[NOTION] list_line_tasks returned %d pages", len(pages))
    return pages


def find_tasks(query: str, days: int = 90, limit: int = 20) -> list[dict]:
    """自然文/拠点名/案件名片からタスク行を特定するための候補を返す。

    完了報告で「甲賀」のように拠点名だけ来る運用に対応するための name → page_id 解決手段。
    けいすけはタスク名を「甲賀　レイアウト【済】…」にリネームし【LINE】が消えるため、
    list_line_tasks（title starts_with "【LINE】"）では二度と引けない。よってここでは
    prefix filter を使わず、タイトル(動的解決)と備考の『案件: <値>』行に対して
    正規化 fuzzy 一致（全半角・空白無視・部分一致）で突き合わせる。

    突き合わせは備考“全文”ではなく『案件:』行の値だけに限定する。全文一致だと [Claude推測] 行の
    相互参照（対象6拠点: 神戸/…/甲賀/…）に短い拠点名が当たり、全件ヒットしてしまうため
    （2026-06-16 ライブ受け入れ指摘）。タイトル一致は従来どおり有効。

    0 件・多数ヒットいずれもそのまま配列で返し、最終確定は呼び出し側エージェントに委ねる
    （pc_cli は判定しない）。全件走査が重い場合に備え last_edited_time の窓(days)で絞る。
    """
    nq = _normalize_for_match(query)
    data_source_id = _get_data_source_id()
    _get_title_prop_name()  # 先に解決＆スキーマ WARN を出しておく
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query_filter = {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": since}}
    sorts = [{"timestamp": "last_edited_time", "direction": "descending"}]

    matches: list[dict] = []
    cursor: str | None = None
    while True:
        kwargs: dict = {
            "data_source_id": data_source_id,
            "filter": query_filter,
            "sorts": sorts,
            "page_size": 100,
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        _throttle()
        resp = _get_client().data_sources.query(**kwargs)

        for page in resp.get("results", []):
            title = _title_text(page)
            note = _note_text(page)
            case_val = _case_value(note)
            if nq and (nq in _normalize_for_match(title) or nq in _normalize_for_match(case_val)):
                matches.append({
                    "page_id": page["id"],
                    "title": title,
                    "note_excerpt": note[:200],
                    "last_edited": page.get("last_edited_time", ""),
                })
                if len(matches) >= limit:
                    break

        if len(matches) >= limit or not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    logger.info("[NOTION] find_tasks query=%r days=%d -> %d matches", query, days, len(matches))
    return matches

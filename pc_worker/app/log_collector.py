"""LINE 会話ログをグループ別 md に追記する純粋関数群。

I/O は append_entries / read_state / write_state の 3 箇所に閉じる（テスト容易性のため）。
パス解決（Windows→unix）は呼び出し側 cli.py が mounts.resolve_to_unix で済ませてから
out_dir を渡す前提で、本モジュールは解決済みパスを Path で素通しに扱う。
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_JST = timezone(timedelta(hours=9))

_STATE_FILE = ".collect_state.json"

_TYPE_LABELS = {
    "image": "[画像]",
    "file": "[ファイル]",
    "video": "[動画]",
    "audio": "[音声]",
}

_FORBIDDEN = set('\\/:*?"<>|')


def sanitize_filename(name: str) -> str:
    if name is None:
        return "unknown"
    chars = []
    for ch in str(name):
        if ch in _FORBIDDEN or ord(ch) < 32:
            chars.append("_")
        else:
            chars.append(ch)
    result = "".join(chars).strip().strip(".").strip()
    return result or "unknown"


def _to_jst(iso_utc: str | None) -> str:
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
    except (ValueError, TypeError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_JST).strftime("%Y/%m/%d %H:%M")


def format_log_line(entry: dict) -> str:
    when = _to_jst(entry.get("received_at"))
    who = entry.get("sender_display_name") or "不明"
    msg_type = entry.get("message_type") or "text"
    if msg_type == "text":
        body = " ".join(str(entry.get("text") or "").split())
        line = f"- {when} {who}: {body}"
    else:
        label = _TYPE_LABELS.get(msg_type, "[その他]")
        file_name = entry.get("file_name")
        if file_name:
            file_name = " ".join(str(file_name).split())
            line = f"- {when} {who}: {label} {file_name}"
        else:
            line = f"- {when} {who}: {label}"
    if not when:
        line = "- " + line[2:].lstrip()
    return line


def group_header(group_name: str, group_id: str) -> str:
    name = group_name or group_id
    return f"# LINE会話ログ: {name} (groupId: {group_id})\n"


def append_entries(out_dir, entries: list[dict], resolve_group_name) -> dict:
    base = Path(out_dir)
    base.mkdir(parents=True, exist_ok=True)

    by_group: dict[str, list[dict]] = {}
    for e in entries:
        gid = e.get("group_id") or ""
        by_group.setdefault(gid, []).append(e)

    appended = 0
    groups: dict[str, int] = {}
    files: list[str] = []

    for gid, items in by_group.items():
        items = sorted(items, key=lambda e: e.get("received_at") or "")
        group_name = resolve_group_name(gid) if resolve_group_name else None
        display = group_name or gid
        path = base / (sanitize_filename(display) + ".md")
        new_file = not path.exists()
        with path.open("a", encoding="utf-8") as f:
            if new_file:
                f.write(group_header(group_name or gid, gid))
            for e in items:
                f.write(format_log_line(e) + "\n")
        appended += len(items)
        groups[display] = groups.get(display, 0) + len(items)
        files.append(str(path))

    return {"appended": appended, "groups": groups, "files": files}


def read_state(out_dir) -> dict:
    path = Path(out_dir) / _STATE_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_state(out_dir, state: dict) -> None:
    base = Path(out_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / _STATE_FILE
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

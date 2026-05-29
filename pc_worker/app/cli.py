import json
import sys
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path

import typer

from app import config, notion_writer, pull, sharepoint_writer, winpath
from app.config import settings

app = typer.Typer(add_completion=False, help="LineTask pc_cli — GCS/Notion/SharePoint の薄い API ラッパー")

_KIND_TO_SUBFOLDER = {
    "受領資料": "09.受領資料",
    "LINEやりとり資料": "09.LINEやりとり資料",
}


def _init_logging(log_run_id: str | None) -> str:
    config.setup_logging()
    run_id = log_run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    config.add_file_handler(run_id)
    return run_id


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _fail(message: str, detail: str = "") -> None:
    sys.stderr.write(json.dumps({"error": message, "detail": detail}, ensure_ascii=False) + "\n")
    raise typer.Exit(code=1)


@app.command("pull-pending")
def pull_pending_cmd(
    limit: int = typer.Option(50, "--limit"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """Firestore status=pending を最大 N 件、メタのみ JSON 配列で出力。"""
    _init_logging(log_run_id)
    try:
        items = pull.list_pending(limit)
    except Exception as e:
        _fail("pull-pending failed", str(e))
    _emit(items)


@app.command("download")
def download_cmd(
    doc_id: str = typer.Argument(...),
    dest_dir: str = typer.Option(None, "--dest-dir"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """doc の GCS バイナリをローカルにダウンロードし、unix/windows 両形式のパスを出力。"""
    _init_logging(log_run_id)
    target = dest_dir or settings.tmp_download_dir or tempfile.gettempdir()
    try:
        local = pull.download(doc_id, target)
    except Exception as e:
        _fail("download failed", str(e))
    unix = str(local)
    _emit({
        "doc_id": doc_id,
        "local_path_unix": unix,
        "local_path_windows": winpath.unix_to_windows(unix),
    })


@app.command("list-cases")
def list_cases_cmd(
    days: int = typer.Option(90, "--days"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """Notion 設計タスク管理 DB から直近 N 日に更新があった案件名候補を出力。"""
    _init_logging(log_run_id)
    try:
        cases = notion_writer.list_cases(days)
    except Exception as e:
        _fail("list-cases failed", str(e))
    _emit(cases)


@app.command("write-task")
def write_task_cmd(
    case: str = typer.Option(..., "--case"),
    title: str = typer.Option(..., "--title"),
    priority: str = typer.Option(notion_writer.PRIORITY_PENDING, "--priority"),
    note: str = typer.Option(None, "--note"),
    onedrive_link: str = typer.Option(None, "--onedrive-link"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """Notion に新規タスク row を追加。"""
    _init_logging(log_run_id)
    try:
        result = notion_writer.write_task(case, title, priority, note, onedrive_link)
    except Exception as e:
        _fail("write-task failed", str(e))
    _emit(result)


@app.command("update-task")
def update_task_cmd(
    page_id: str = typer.Option(..., "--page-id"),
    case: str = typer.Option(None, "--case"),
    title: str = typer.Option(None, "--title"),
    priority: str = typer.Option(None, "--priority"),
    note: str = typer.Option(None, "--note"),
    onedrive_link: str = typer.Option(None, "--onedrive-link"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """既存タスク row を部分更新。優先度を「仕分け待ち」以外にすると仕分け完了扱い。"""
    _init_logging(log_run_id)
    try:
        result = notion_writer.update_task(page_id, case, title, priority, note, onedrive_link)
    except Exception as e:
        _fail("update-task failed", str(e))
    _emit(result)


@app.command("place-file")
def place_file_cmd(
    src: str = typer.Option(..., "--src"),
    case: str = typer.Option(..., "--case"),
    kind: str = typer.Option(..., "--kind"),
    title: str = typer.Option(..., "--title"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """SharePoint 案件フォルダにファイル配置。kind は 受領資料 / LINEやりとり資料。"""
    _init_logging(log_run_id)
    subfolder = _KIND_TO_SUBFOLDER.get(kind)
    if subfolder is None:
        _fail("invalid kind", f"kind は {list(_KIND_TO_SUBFOLDER)} のいずれか: {kind}")
    src_path = Path(src)
    if not src_path.exists():
        _fail("src not found", src)
    filename = f"{date.today().isoformat()} {title}{src_path.suffix}"
    try:
        dest = sharepoint_writer.write_to_case_folder(case, subfolder, filename, src_path.read_bytes())
    except Exception as e:
        _fail("place-file failed", str(e))
    unix = str(dest)
    _emit({
        "destination_unix": unix,
        "destination_windows": winpath.unix_to_windows(unix),
        "onedrive_link": sharepoint_writer.to_onedrive_link(dest),
    })


@app.command("write-log")
def write_log_cmd(
    case: str = typer.Option(..., "--case"),
    log_date: str = typer.Option(..., "--date"),
    content: str = typer.Option(..., "--content"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """議事ログ Markdown を <案件名>/09.LINEやりとり資料/<date> 議事ログ.md に書き込み（上書き）。"""
    _init_logging(log_run_id)
    filename = f"{log_date} 議事ログ.md"
    try:
        dest = sharepoint_writer.write_to_case_folder(
            case, "09.LINEやりとり資料", filename, content, overwrite=True
        )
    except Exception as e:
        _fail("write-log failed", str(e))
    unix = str(dest)
    _emit({"destination_unix": unix, "destination_windows": winpath.unix_to_windows(unix)})


@app.command("mark-done")
def mark_done_cmd(
    doc_id: str = typer.Argument(...),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """Firestore status=done + GCS ファイル削除。"""
    _init_logging(log_run_id)
    try:
        result = pull.mark_done(doc_id)
    except Exception as e:
        _fail("mark-done failed", str(e))
    _emit(result)


@app.command("mark-review")
def mark_review_cmd(
    doc_id: str = typer.Argument(...),
    reason: str = typer.Option(None, "--reason"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """Firestore status=needs_review、GCS 保持。"""
    _init_logging(log_run_id)
    try:
        result = pull.mark_review(doc_id, reason)
    except Exception as e:
        _fail("mark-review failed", str(e))
    _emit(result)


if __name__ == "__main__":
    app()

import json
import sys
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path

import typer

from app import config, folders, mounts, notion_writer, pull, sharepoint_writer
from app.config import settings

app = typer.Typer(add_completion=False, help="LineTask pc_cli — GCS/Notion/SharePoint の薄い API ラッパー")


def _init_logging(log_run_id: str | None) -> str:
    config.setup_logging()
    run_id = log_run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    config.add_file_handler(run_id)
    config.normalize_google_credentials()
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
        "local_path_windows": config.to_windows(unix),
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
    status: str = typer.Option(None, "--status", help="ステータス(status 型)を設定。完了化は '完了' 等（'通常' 優先度は実 DB に存在しない）"),
    note: str = typer.Option(None, "--note"),
    onedrive_link: str = typer.Option(None, "--onedrive-link"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """既存タスク row を部分更新。完了化は --status（status 型プロパティ「ステータス」）で行う。"""
    _init_logging(log_run_id)
    try:
        result = notion_writer.update_task(page_id, case, title, priority, note, onedrive_link, status)
    except Exception as e:
        _fail("update-task failed", str(e))
    _emit(result)


@app.command("list-case-folders")
def list_case_folders_cmd(
    root: str = typer.Option(None, "--root"),
    max_depth: int = typer.Option(3, "--max-depth"),
    query: str = typer.Option(None, "--query", help="案件名の一部。指定すると深く（既定 max-depth=6）再帰し、名前にマッチする案件フォルダだけ返す"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """SHAREPOINT_ROOT 配下を再帰スキャンし、案件フォルダ候補一覧を JSON 配列で出力。

    --query を渡すと、不揃いな深さ（ブランチごとに depth2〜4）を跨いで名前で絞り込む（bug2 対策）。
    全件列挙（query 無し）は depth3 で約 6700 件と多いので、Skill は Notion 案件名で --query するのが安定。
    """
    _init_logging(log_run_id)
    effective_depth = max_depth if query is None else max(max_depth, 6)
    try:
        result = folders.list_case_folders(root, effective_depth, query=query)
    except FileNotFoundError as e:
        _fail("root_not_found", str(e))
    except Exception as e:
        _fail("list-case-folders failed", str(e))
    _emit(result)


@app.command("place-file")
def place_file_cmd(
    src: str = typer.Option(..., "--src"),
    case_folder: str = typer.Option(..., "--case-folder"),
    title: str = typer.Option(..., "--title"),
    log_date: str = typer.Option(None, "--date"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """案件フォルダ(絶対パス)配下の 09.LINEやりとり資料/ にファイル配置。"""
    _init_logging(log_run_id)
    # case_folder / src は Skill から Windows パスで来る。実マウントへ解決してから使う（bug1）。
    maps = settings.path_maps
    src = mounts.resolve_to_unix(src, maps)
    case_folder = mounts.resolve_to_unix(case_folder, maps)
    src_path = Path(src)
    if not src_path.exists():
        _fail("src not found", src)
    day = log_date or date.today().isoformat()
    filename = f"{day} {title}{src_path.suffix}"
    try:
        dest, created = sharepoint_writer.place_in_case_folder(case_folder, filename, src_path.read_bytes())
    except FileNotFoundError as e:
        _fail("case_folder_not_found", str(e))
    except Exception as e:
        _fail("place-file failed", str(e))
    unix = str(dest)
    _emit({
        "destination_unix": unix,
        "destination_windows": config.to_windows(unix),
        "onedrive_link": sharepoint_writer.to_onedrive_link(dest),
        "created_subfolder": created,
    })


@app.command("write-log")
def write_log_cmd(
    case_folder: str = typer.Option(..., "--case-folder"),
    log_date: str = typer.Option(..., "--date"),
    content: str = typer.Option(..., "--content", help="議事ログ本文。'-' で stdin から読む"),
    filename: str = typer.Option(None, "--filename", help="保存ファイル名（既定: '<date> 議事ログ.md'）。HTML 化はここで '<date> 議事ログ.html' を渡す"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """議事ログを <案件フォルダ>/09.LINEやりとり資料/<filename> に書き込み（固定名・上書き）。

    既定のファイル名は '<date> 議事ログ.md'。--filename で任意名（例 '<date> 議事ログ.html'）を指定できる。
    """
    _init_logging(log_run_id)
    # case_folder は Windows パスで来うる。実マウントへ解決（bug1、write-log も対象）。
    case_folder = mounts.resolve_to_unix(case_folder, settings.path_maps)
    text = sys.stdin.read() if content == "-" else content
    out_name = filename or f"{log_date} 議事ログ.md"
    try:
        dest, created = sharepoint_writer.place_in_case_folder(case_folder, out_name, text, overwrite=True)
    except FileNotFoundError as e:
        _fail("case_folder_not_found", str(e))
    except Exception as e:
        _fail("write-log failed", str(e))
    unix = str(dest)
    _emit({
        "destination_unix": unix,
        "destination_windows": config.to_windows(unix),
        "created_subfolder": created,
    })


@app.command("list-messages")
def list_messages_cmd(
    group_id: str = typer.Option(..., "--group-id"),
    around_doc: str = typer.Option(None, "--around-doc", help="この doc の receivedAt を中心に ±window-hours を取る糖衣"),
    since: str = typer.Option(None, "--since", help="ISO8601 下限（around-doc 未指定時）"),
    until: str = typer.Option(None, "--until", help="ISO8601 上限（around-doc 未指定時）"),
    window_hours: int = typer.Option(48, "--window-hours"),
    limit: int = typer.Option(200, "--limit"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """同一グループの前後メッセージ（text/file）を時系列で返す。関連/非関連の判断は Cowork 側。"""
    _init_logging(log_run_id)
    try:
        items = pull.list_messages(
            group_id,
            around_doc=around_doc,
            since=since,
            until=until,
            window_hours=window_hours,
            limit=limit,
        )
    except Exception as e:
        _fail("list-messages failed", str(e))
    _emit(items)


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

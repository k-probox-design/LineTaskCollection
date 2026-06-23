import json
import os
import sys
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import typer

from app import config, folders, log_collector, mounts, notion_writer, pull, results_export, sharepoint_writer, tray_writer
from app.config import settings

# 実績 HTML の既定出力先（Windows パス。winpath 解決を通してから書く）
DEFAULT_RESULTS_HTML = r"C:\Users\knaka\OneDrive - 株式会社ビギン\@@設計\51.LINE投稿ボット\LINE仕分け実績.html"

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


def _format_conversation(entries: list[dict]) -> str:
    """list_messages の戻り（時系列昇順）を人が読める会話ログ文字列に整形する。

    1 行 = '[受信(JST)] 送信者: 本文 or ファイル名'。受信は UTC ISO を +9h で JST 化する。
    """
    jst = timezone(timedelta(hours=9))
    lines: list[str] = []
    for e in entries:
        iso = e.get("received_at")
        when = ""
        if iso:
            try:
                dt = datetime.fromisoformat(iso)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                when = dt.astimezone(jst).strftime("%Y/%m/%d %H:%M")
            except (ValueError, TypeError):
                when = ""
        who = e.get("sender_display_name") or "(不明)"
        body = e.get("text") or e.get("file_name") or ""
        body = " ".join(str(body).split())
        lines.append(f"[{when}] {who}: {body}".rstrip())
    return "\n".join(lines)


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
    priority: str = typer.Option(None, "--priority", help="既定は NOTION_DEFAULT_PRIORITY（既定値 'Claude追記'）"),
    note: str = typer.Option(None, "--note"),
    onedrive_link: str = typer.Option(None, "--onedrive-link"),
    assignee_user_id: str = typer.Option(None, "--assignee-user-id", help="担当(person)。既定は NOTION_DEFAULT_ASSIGNEE_USER_ID"),
    file_name: str = typer.Option(None, "--file-name", help="実ファイル名。備考に『ファイル: …』で機械可読に残す（実績HTMLが消費）"),
    confidence: str = typer.Option(None, "--confidence", help="確信度。備考に『確信度: …』で残す"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """Notion に新規タスク row を追加。担当・既定優先度で人別ビューに乗せる。"""
    _init_logging(log_run_id)
    try:
        result = notion_writer.write_task(
            case, title, priority, note, onedrive_link, assignee_user_id, file_name, confidence
        )
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
    assignee_user_id: str = typer.Option(None, "--assignee-user-id", help="担当(person)を user_id で設定"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """既存タスク row を部分更新。完了化は --status（status 型プロパティ「ステータス」）で行う。"""
    _init_logging(log_run_id)
    try:
        result = notion_writer.update_task(page_id, case, title, priority, note, onedrive_link, status, assignee_user_id)
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
    # --root も Windows パスで来うる。実マウントへ解決（bug1 の取りこぼし＝A-2 要対応①）。
    if root:
        root = mounts.resolve_to_unix(root, settings.path_maps)
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
    no_subfolder: bool = typer.Option(False, "--no-subfolder", help="09.LINEやりとり資料 を作らず案件フォルダ直下に置く（個人 OneDrive 運用）"),
    allow_create: bool = typer.Option(False, "--allow-create", help="案件フォルダが無ければ自動作成する（個人 OneDrive サイロ向け）"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """案件フォルダ(絶対パス)配下にファイル配置（既定は 09.LINEやりとり資料/、--no-subfolder で直下）。"""
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
        dest, created = sharepoint_writer.place_in_case_folder(
            case_folder, filename, src_path.read_bytes(),
            subfolder=None if no_subfolder else sharepoint_writer.LINE_SUBFOLDER,
            allow_create=allow_create,
        )
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
    no_subfolder: bool = typer.Option(False, "--no-subfolder", help="09.LINEやりとり資料 を作らず案件フォルダ直下に置く（個人 OneDrive 運用）"),
    allow_create: bool = typer.Option(False, "--allow-create", help="案件フォルダが無ければ自動作成する（個人 OneDrive サイロ向け）"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """議事ログを <案件フォルダ>/[09.LINEやりとり資料/]<filename> に書き込み（固定名・上書き）。

    既定のファイル名は '<date> 議事ログ.md'。--filename で任意名（例 '<date> 議事ログ.html'）を指定できる。
    既定は 09.LINEやりとり資料/ 配下、--no-subfolder で案件フォルダ直下に書く。
    """
    _init_logging(log_run_id)
    # case_folder は Windows パスで来うる。実マウントへ解決（bug1、write-log も対象）。
    case_folder = mounts.resolve_to_unix(case_folder, settings.path_maps)
    text = sys.stdin.read() if content == "-" else content
    out_name = filename or f"{log_date} 議事ログ.md"
    try:
        dest, created = sharepoint_writer.place_in_case_folder(
            case_folder, out_name, text, overwrite=True,
            subfolder=None if no_subfolder else sharepoint_writer.LINE_SUBFOLDER,
            allow_create=allow_create,
        )
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


@app.command("export-results-html")
def export_results_html_cmd(
    out: str = typer.Option(DEFAULT_RESULTS_HTML, "--out", help="出力先（Windows パス可）。既定=51.LINE投稿ボット直下の LINE仕分け実績.html"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """Notion の【LINE】タスクを唯一の真実として実績 HTML をまるごと再生成（決定的・上書き）。

    Notion だけを読み、OneDrive へは書くだけ（未ハイドレートの罠を避ける）。Notion 失敗時は
    既存ファイルを壊さない（一時ファイルに書いて atomically rename）。
    """
    _init_logging(log_run_id)
    out_unix = mounts.resolve_to_unix(out, settings.path_maps)
    try:
        pages = notion_writer.list_line_tasks()
    except Exception as e:
        _fail("export-results-html failed", str(e))
    rows = results_export.build_rows(pages)
    jst_now = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M") + " JST"
    html = results_export.render_html(rows, jst_now)

    out_path = Path(out_unix)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_name(out_path.name + ".tmp")
        tmp.write_text(html, encoding="utf-8")
        os.replace(tmp, out_path)  # atomically 置換（途中失敗で既存を壊さない）
    except OSError as e:
        _fail("export-results-html write failed", str(e))

    _emit({
        "out_unix": str(out_path),
        "out_windows": config.to_windows(str(out_path)),
        "count": len(rows),
        "generated_at": jst_now,
    })


@app.command("send-to-tray")
def send_to_tray_cmd(
    doc_id: str = typer.Option(..., "--doc-id"),
    case: str = typer.Option(None, "--case"),
    placed_file: str = typer.Option(None, "--placed-file", help="place-file の destination_windows を渡す想定。トレイの link/添付になる"),
    with_conversation: bool = typer.Option(False, "--with-conversation", help="同一グループの前後メッセージを会話ログとして同梱する"),
    window_hours: int = typer.Option(48, "--window-hours", help="--with-conversation の前後窓（時間）"),
    needs_review: bool = typer.Option(False, "--needs-review", help="要対応を ◎ にする（既定は △）"),
    out_dir: str = typer.Option(None, "--out-dir", help="トレイの出力先（Windows パス可）。既定は settings.tray_dir"),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """doc 1 件をタスク管理アプリの受け渡しトレイへ LINE_<source_id>.json として書き出す。"""
    _init_logging(log_run_id)
    target = out_dir or settings.tray_dir
    if not target:
        _fail("tray dir not set", "--out-dir も TRAY_DIR も未設定です")
    try:
        meta = pull.get_meta(doc_id)
    except Exception as e:
        _fail("send-to-tray failed", str(e))

    conversation_text = None
    if with_conversation:
        group_id = meta.get("group_id")
        if not group_id:
            _fail("send-to-tray failed", f"doc に group_id がありません: {doc_id}")
        try:
            entries = pull.list_messages(group_id, around_doc=doc_id, window_hours=window_hours)
        except Exception as e:
            _fail("send-to-tray failed", str(e))
        conversation_text = _format_conversation(entries)

    record = tray_writer.build_tray_record(
        meta,
        case=case,
        placed_file_windows=placed_file,
        conversation_text=conversation_text,
        needs_review=needs_review,
    )
    try:
        dest = tray_writer.write_tray_file(record, target)
    except Exception as e:
        _fail("send-to-tray failed", str(e))
    unix = str(dest)
    _emit({
        "out_unix": unix,
        "out_windows": config.to_windows(unix),
        "source_id": record["source_id"],
    })


@app.command("collect-logs")
def collect_logs_cmd(
    out_dir: str = typer.Option(None, "--out-dir", help="会話ログmdの出力先（Windowsパス可）。既定は settings.line_log_dir"),
    limit: int = typer.Option(1000, "--limit"),
    force_backfill: bool = typer.Option(
        False, "--force-backfill",
        help="state(.collect_state.json) が無く既に md がある場合でも、全件バックフィルを強行する（意図的な取り直し用）",
    ),
    log_run_id: str = typer.Option(None, "--log-run-id"),
) -> None:
    """intake_messages を前回カーソル以降だけ取得し、グループ別 md に追記する（収集のみ・判断しない）。

    doc_id で冪等（取りこぼさない・二重にしない）に収集する。境界（last_received と同時刻の doc）を
    boundary_ids として state に持ち、次回 inclusive(>=) で取り直して doc_id で除外する。
    1 回の呼び出しで limit を跨いで取り切る（ドレイン）。
    """
    _init_logging(log_run_id)
    target = out_dir or settings.line_log_dir
    if not target:
        _fail("line log dir not set", "--out-dir も LINE_LOG_DIR も未設定です")
    target = mounts.resolve_to_unix(target, settings.path_maps)
    state = log_collector.read_state(target)
    since = state.get("last_received")

    # state 消失ガード: cursor が無いのに既存 md がある＝state が消えた/壊れた疑い。
    # 黙って全件追記すると md に履歴がまるごと二重で入るため、--force-backfill が無ければ
    # 収集をスキップして exit 0（自動実行を黙って止めず、かつ二重もしない＝安全側）。
    if since is None and not force_backfill:
        existing_md = list(Path(target).glob("*.md")) if Path(target).exists() else []
        if existing_md:
            sys.stderr.write(
                "state(.collect_state.json) が見つからず、既に会話ログmdがあります。"
                "二重取り込み防止のため収集をスキップしました。"
                "意図的に取り直す場合は --force-backfill を付けてください。\n"
            )
            _emit({
                "appended": 0,
                "groups": {},
                "files": [],
                "since": None,
                "new_cursor": None,
                "skipped": "state_missing_guard",
            })
            return

    cursor = since
    boundary: set[str] = set(state.get("boundary_ids") or [])
    total_appended = 0
    groups: dict[str, int] = {}
    files: list[str] = []

    while True:
        try:
            # cursor があり、かつ除外用 boundary を持つときだけ >=（inclusive）。
            # 旧形式 state(boundary 無し) の初回は厳密 >(False) で境界 doc を取りに行かず二重追記を防ぐ。
            # boundary はバッチごとに更新されるため、毎反復でこの式を評価する。
            batch = pull.list_since(cursor, limit, inclusive=(cursor is not None and bool(boundary)))
        except Exception as e:
            _fail("collect-logs failed", str(e))
        if not batch:
            break

        # 既に書いた境界 doc を除外＝二重書きしない（冪等）。
        fresh = [e for e in batch if e.get("doc_id") not in boundary]
        if fresh:
            try:
                result = log_collector.append_entries(target, fresh, pull._group_name)
            except Exception as e:
                _fail("collect-logs failed", str(e))
            total_appended += result["appended"]
            for g, n in result["groups"].items():
                groups[g] = groups.get(g, 0) + n
            for f in result["files"]:
                if f not in files:
                    files.append(f)

        # batch の doc は order_by receivedAt のため received_at を必ず持つ。
        batch_max = max(e["received_at"] for e in batch)
        new_boundary = {e["doc_id"] for e in batch if e["received_at"] == batch_max}
        if batch_max == cursor:
            # 境界が同一時刻のまま続く（limit 内に同時刻が収まらない）→ 蓄積する。
            new_boundary |= boundary

        # 無限ループ防止: batch 全件が batch_max と同時刻 かつ fresh が空 かつ満杯
        #（＝同一時刻に limit 超の異常）なら、これ以上前進できないので打ち切る。
        all_same_time = all(e["received_at"] == batch_max for e in batch)
        if all_same_time and not fresh and len(batch) >= limit:
            cursor, boundary = batch_max, new_boundary
            log_collector.write_state(
                target, {"last_received": cursor, "boundary_ids": sorted(boundary)}
            )
            break

        cursor, boundary = batch_max, new_boundary
        # 各バッチ後に state を保存（部分失敗しても次回 inclusive＋boundary で冪等）。
        log_collector.write_state(
            target, {"last_received": cursor, "boundary_ids": sorted(boundary)}
        )

        if len(batch) < limit:
            break  # 取り切った

    _emit({
        "appended": total_appended,
        "groups": groups,
        "files": files,
        "since": since,
        "new_cursor": cursor,
    })


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

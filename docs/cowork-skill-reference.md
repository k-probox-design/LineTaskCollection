# Cowork Skill 移植用リファレンス（Phase C 旧実装のロジック保存）

Phase C'（2026-05-29）で仕分け判断を Cowork（Opus）に移すにあたり、Phase C の `classify.py` / `orchestrator.py` を削除した。
ここに判定ロジックを保存しておくので、Cowork 用 Skill「LineTask 仕分け」を組むときの土台にすること。

pc_cli は判定ロジックを持たない API ラッパーに徹する。下記の「判断」「分岐」は Cowork 側が担う。

---

## 1. 旧 classify のシステムプロンプト（全文）

```
あなたは設計事務所のアシスタントです。LINE グループで受信したファイル（見積書・図面・写真など）やテキストを、既存の案件に振り分け、内容を表すタイトルを推測します。

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

# 既存案件候補
- <案件候補1>
- <案件候補2>
...
```

- 案件候補リストは `pc_cli list-cases` の出力（`case_name` の一覧）を使う
- システムプロンプト + 候補リストは「1 仕分けセッション内で不変」なので、API 実装時は prompt cache 対象だった（Cowork 運用では不要）

## 2. 旧 classify の入力（マルチモーダル組立）

- **image**: base64 で `image` ブロック（media_type は拡張子から: jpg/jpeg→image/jpeg, png→image/png, gif→image/gif, webp→image/webp）
- **pdf**: base64 で `document` ブロック（media_type=application/pdf）
- **その他バイナリ（office 等）**: 本体は送らず、ファイル名と文脈テキストのみで判断
- **コンテキストテキスト**（必ず付与）:
  - `groupId`
  - 受信時刻
  - メッセージ種別
  - このグループに紐づく案件名（あれば）
  - ファイル名（あれば）
  - テキスト本文（あれば）
  - 直近のテキストメッセージ一覧（あれば）

## 3. 旧 classify の出力スキーマ（ClassifyResult）

```
case_name: str | None        # 案件名。候補になければ null
title: str                   # 簡潔な日本語タイトル
confidence: float            # 0.0〜1.0
reasoning: str               # 判断理由
related_message_ids: list[str]
```

---

## 4. 旧 orchestrator の振り分けフロー（擬似コード）

```
run_once():
    items      = pull-pending          # Firestore status=pending
    candidates = list-cases            # 既存案件候補
    threshold  = 0.8                   # 確信度しきい値

    for item in items:
        result = classify(item, candidates)   # ← Cowork が担当
        page_id = write-task(                  # Notion に「仕分け待ち」row 追加
            case=result.case_name, title=result.title,
            priority="仕分け待ち",
            note="[Claude 推測] 案件候補/確信度/判断理由/関連メッセージ/LINE messageId/groupId/GCS path",
        )

        confident = result.case_name is not None and result.confidence >= threshold

        if confident and ファイル本体あり:
            # 確信あり → SharePoint 格納 + Notion 更新 + GCS 削除
            dest = place-file(case=result.case_name, kind=受領資料,
                              title=f"{受信日} {result.title}")
            update-task(page_id, onedrive_link=dest, priority=通常)  # 「仕分け完了」へ
            write-log(case=result.case_name, date=受信日, content=<議事ログ Markdown>)
            mark-done(doc_id)            # Firestore done + GCS 削除
        else:
            # 確信なし or 本体取得不可 → 「仕分け待ち」のまま残す
            mark-review(doc_id, reason="案件名不明 or 確信度不足")
            # GCS は保持（けいすけが手動確認 → 必要なら status を pending に戻して再 run）
```

### 確信度しきい値の扱い

- 旧実装では threshold=0.8 を `.env` の `CLASSIFY_CONFIDENCE_THRESHOLD` で持っていた
- Phase C' では Cowork（Opus）が判断時に確信度を内部で持ち、低いものはけいすけにその場で対話確認する（needs_review に溜めない）

## 5. Cowork Skill 側のフロー（pc_cli 呼び出し、2026-05-29 SharePoint 探索対応版）

SharePoint は階層・命名が不規則なので、案件フォルダは `list-case-folders` で探索して絶対パスを得る。

```
1. pull-pending                      # 未処理一覧
2. for each item:
     download <doc_id>               # 画像/PDF を取得 → Cowork が Read で中身を見る
     list-cases                      # Notion 案件候補（タスク名ベース）
     list-case-folders               # SharePoint 案件フォルダ候補（絶対パス付き）
     ── Cowork が案件名 fuzzy match して案件フォルダの絶対パスを決定 ──
     ├ マッチあり・確信あり:
     │   write-task --case <案件名> --title ...        # Notion「仕分け待ち」row
     │   place-file --src <local> --case-folder <絶対パス> --title ...   # 09.LINEやりとり資料/ へ
     │   write-log  --case-folder <絶対パス> --date ... --content -      # 議事ログ（stdin）
     │   update-task --page-id ... --priority 通常 --onedrive-link ...   # 仕分け完了化
     │   mark-done <doc_id>
     └ マッチなし・確信なし:
         けいすけにその場で対話確認 → 案件フォルダ手動作成 → 再仕分け
         または mark-review <doc_id> --reason ...      # needs_review に残す（GCS 保持）
```

- `list-case-folders` の `has_line_yaritori_folder` / `child_dir_count` / `last_modified` を案件判定のヒントに使う
- 案件フォルダ自体の自動作成はしない（NG）。`09.LINEやりとり資料/` サブフォルダは place-file/write-log が自動作成する

### 議事ログ Markdown の構造（旧 log_writer.build_session_log）

```markdown
# YYYY-MM-DD 議事ログ

対象 LINE グループ: <group_id>
対象時刻範囲: <start> 〜 <end>

---

## YYYY-MM-DD HH:MM [テキスト]

<本文>

## YYYY-MM-DD HH:MM [ファイル: <fileName>]

→ ../09.受領資料/<fileName>
```

- 同 groupId 内で対象時刻の前後 N 時間（旧既定 24h）の text/file を時系列に並べる
- Phase C' では Cowork がこの Markdown を組み立て、`pc_cli write-log --content` で書き込む
- （`log_writer.build_session_log` は pc_worker に参照用として残置。Firestore からの集約が必要になったとき流用可）

---

## 6. サンドボックス実行の確定仕様（2026-05-30、実行経路 A 案）

Cowork サンドボックス（Ubuntu 22 / Python 3.10 / OneDrive 選択フォルダのみマウント / ネットワーク開）から pc_cli を完動させるための、Skill が依拠する確定仕様。

### 6-1. ブートストラップ（揮発サンドボックス、起動毎）— git clone を正とする

**重要（2026-05-30 確定）**: コードを OneDrive コピーから読んではいけない。OneDrive Files-On-Demand のプレースホルダは Cowork の Linux マウント越しに**中身が途中で切れて読めない**（`notion_writer.py` が 5395B で頭打ち→AST 失敗）。`attrib +P`(Pinned) でも実体ハイドレートは保証されず、WSL 側のどの対策でも安定解消しなかった。よって **コードは GitHub から git clone** し、OneDrive からは「小サイズで完全に読める」`.env` と SA 鍵だけを使う。

Skill は毎回先頭でこれを実行する（リポジトリの `scripts/sandbox-bootstrap.sh` が clone＋prep＋検証まで行う）:

```bash
ONEDRIVE=$(ls -d /sessions/*/mnt/51.LINE投稿ボット/pc_cli 2>/dev/null | head -1)
export GITHUB_PAT=$(grep -E '^GITHUB_PAT=' "$ONEDRIVE/.env" | head -1 | cut -d= -f2- | tr -d '\r')
export REPO_REF=main          # main マージ前のテストは work ブランチ名を指定（例: work/2026-05-28-phaseC）

# bootstrap スクリプトを PAT 付きで取得して実行（clone→.env コピー→pip→AST 検証）
curl -fsSL -H "Authorization: token $GITHUB_PAT" \
  "https://raw.githubusercontent.com/k-probox-design/LineTaskCollection/$REPO_REF/scripts/sandbox-bootstrap.sh" \
  -o /tmp/sandbox-bootstrap.sh

# stdout は「PCWORKER=<実行ごとユニークな pc_worker 絶対パス>」の 1 行のみ。これを拾って後続で使う。
PCWORKER=$(bash /tmp/sandbox-bootstrap.sh | sed -n 's/^PCWORKER=//p' | tail -1)
trap 'rm -rf "$(dirname "$PCWORKER")" 2>/dev/null || true' EXIT   # 自分が作った dir を実行終了時に best-effort 削除

cd "$PCWORKER"
export PYTHONPATH="$PWD"
RUN_ID="$(date +%Y%m%d-%H%M%S)-cowork"
```

- **clone 先は実行ごとにユニーク**（bootstrap が `mktemp -d /tmp/linetask.XXXXXX`）。スケジュール実行は前回と別のサンドボックスユーザーで走るため固定パスだと前回分を `rm -rf` できず詰まる。bootstrap は起動時に「自分が消せる 1 時間以上前の `/tmp/linetask.*`」だけ best-effort 掃除する（他ユーザー所有はスキップ）。
- **後片付けは呼び出し側（Skill）の責務**。bootstrap は別プロセスなので自前の `trap EXIT` で消すと Skill が使う前に消えてしまう。上記のように **Skill のトップレベル shell で `trap ... EXIT`** を張る（消せなくても警告のみで継続）。
- 後続の各 pc_cli 呼び出しが別 bash になる場合は、その都度 `cd "$PCWORKER" && PYTHONPATH="$PCWORKER"` を再設定する（`PCWORKER` の値を Skill 側で保持しておく）。
- **clone 先は必ずネイティブ fs**。OneDrive マウント（`/sessions/<sess>/mnt/...`）や `/outputs` 直下では、書込不可／`.git/config.lock` の unlink 非対応で clone が失敗する（2026-05-30 実測）。`WORK_DIR` を明示する場合もネイティブ fs を選ぶこと。
- ブランチ名にスラッシュがあり raw URL が解決しづらいテスト時は、`curl` の代わりに直接
  `WORK=$(mktemp -d /tmp/linetask.XXXXXX); git clone --depth1 --branch <ref> https://oauth2:$GITHUB_PAT@github.com/k-probox-design/LineTaskCollection.git "$WORK"` し、`cp "$ONEDRIVE/.env" "$WORK/pc_worker/.env"` → `cd "$WORK/pc_worker"` → pip → AST 検証、の順で手動実行してよい。
- 依存は `requirements.txt`（バージョン固定、Python 3.10/3.12 双方で解決可）を毎回 pip。`google-cloud-*` のバイナリ wheel があるため vendoring はしない。pip 実測 約6秒（2026-05-30 スモーク）。
- `.env` は OneDrive `pc_cli/.env`（けいすけ記入済み）を clone 内へコピーして使う。SA 鍵は `.env` の `GOOGLE_APPLICATION_CREDENTIALS`（Windows パス）が実行時に MOUNT_MAP の glob で実マウントへ解決され、OneDrive `secrets/` から直接読まれる（小サイズで可読）。
- pc_cli を `/tmp` から動かしても、`mounts.py` は session ベース検出に失敗した後 `/sessions/*/mnt/<名>` の glob でマウントを解決するため `@@@`/winpath 変換は機能する。

### 6-2. マウント解決と winpath 一般化（動的パスの吸収）

**動的パス解決の責務は pc_cli 側**。Skill はセッション名を注入しなくてよい。`.env` のパス系は**静的な Windows 絶対パス**で書けば、pc_cli が実行時に実マウント先へ解決する。

仕組み:

- `.env` の `MOUNT_MAP` に、マウントしている Windows フォルダの絶対パスを `;` 区切りで列挙する。
  ```
  MOUNT_MAP=C:\Users\knaka\OneDrive - 株式会社ビギン\@@@;C:\Users\knaka\OneDrive - 株式会社ビギン\@@設計\51.LINE投稿ボット
  ```
- pc_cli は各エントリの「フォルダ名（末尾要素）」を、次の優先順で実マウント unix パスに解決する:
  1. pc_cli 自身（`app/mounts.py`）の位置から現セッションの mnt ベース（`/sessions/<現>/mnt`）を割り出し `<base>/<フォルダ名>`
  2. WSL の `/mnt/<drive>/...`（`windows_to_unix`）
  3. `/sessions/*/mnt/<フォルダ名>` の glob
- 解決した (unix 接頭辞 ↔ windows 接頭辞) の写像で、`SHAREPOINT_ROOT` 等の入力 Windows パスを unix に解決し、`destination_windows` / `absolute_path_windows` / `local_path_windows` 等の出力を `C:\...` 形に戻す。
- 写像に当たらない `/mnt/c/...` は従来規則（`/mnt/c`→`C:`）でフォールバック。WSL 開発では `MOUNT_MAP` 空でも動く。

**Skill が触る環境変数（.env、確定）**:

| 変数 | 値の形 | 役割 |
|------|--------|------|
| `GITHUB_PAT` | 秘密値（けいすけ記入） | private repo Contents:Read の PAT。git clone でコード取得 |
| `NOTION_API_KEY` | 秘密値（けいすけ記入） | Notion 認証 |
| `NOTION_DATABASE_ID_DESIGN_TASK` | `1eb17f63-...`（記入済み） | 設計タスク管理 DB |
| `GCS_BUCKET` / `FIRESTORE_PROJECT` | 記入済み | GCP リソース |
| `GOOGLE_APPLICATION_CREDENTIALS` | SA 鍵パス（Windows 形可） | GCP 認証。未設定なら ADC |
| `MOUNT_MAP` | Windows 絶対パスの `;` 列挙 | 動的マウント解決の種 |
| `SHAREPOINT_ROOT` | Windows 絶対パス（例 `...\@@@`） | `list-case-folders` の起点 |
| `TMP_DOWNLOAD_DIR` / `LOG_OUTPUT_DIR` | Windows 絶対パス | DL 先 / ログ複製先 |

### 6-3. 認証

- `GOOGLE_APPLICATION_CREDENTIALS` を設定 → SA 鍵認証。未設定 → ADC フォールバック（WSL 開発用）。
- pc_cli は鍵パスが Windows 形式なら実マウントへ解決してから `os.environ` に書き戻す（`google-cloud` ライブラリが読む）。鍵 JSON は `51.LINE投稿ボット/secrets/` に置き、同期・コミットしない。

### 6-4. スモーク手順（Cowork が実環境で答え合わせ）

ブートストラップ後、各サブコマンドを順に叩いて期待挙動を確認する。`<doc_id>` は `pull-pending` 出力から拾う。

| # | コマンド | 期待 |
|---|---------|------|
| 0a | `python -c "import ast,glob; [ast.parse(open(f,encoding='utf-8').read()) for f in glob.glob('app/*.py')]; print('AST OK', len(glob.glob('app/*.py')))"` | 全 `app/*.py` が完全に読めて構文 OK（**Windows 側 size ではなくサンドボックスが読むバイト列で確認**）。bootstrap が git clone していれば必ず通る |
| 0b | `python -c "from app import mounts,config; print(config.settings.path_maps); print(config.settings.sharepoint_root)"` | 写像が `[(/sessions/<現>/mnt/@@@, C:\...\@@@), ...]`、sharepoint_root が `/sessions/<現>/mnt/@@@` |
| 1 | `python -m app.cli pull-pending --limit 5 --log-run-id "$RUN_ID"` | stdout に pending メタの JSON 配列。Firestore 到達（SA 鍵）確認 |
| 2 | `python -m app.cli download <doc_id> --log-run-id "$RUN_ID"` | `local_path_unix` が `/sessions/<現>/mnt/.../pc_worker_tmp/<doc_id>.<ext>`、`local_path_windows` が `C:\...` 形 |
| 3 | `python -m app.cli list-cases --days 90 --log-run-id "$RUN_ID"` | Notion 案件候補の JSON 配列。Notion 到達確認 |
| 4 | `python -m app.cli list-case-folders --max-depth 3 --log-run-id "$RUN_ID"` | `@@@` 配下の案件候補。各要素の `absolute_path_windows` が `C:\Users\knaka\OneDrive - 株式会社ビギン\@@@\...` 形 |
| 5 | `python -m app.cli place-file --src <local> --case-folder "<手順4の絶対パス>" --title "スモーク" --log-run-id "$RUN_ID"` | `09.LINEやりとり資料/` に配置、`destination_windows` が `C:\...` 形、`created_subfolder` 真偽 |
| 6 | `echo "# smoke" \| python -m app.cli write-log --case-folder "<同上>" --date "$(date +%F)" --content - --log-run-id "$RUN_ID"` | 同フォルダに `<date> 議事ログ.md` |
| 7 | `python -m app.cli write-task --case "スモーク案件" --title "【LINE】スモーク" --log-run-id "$RUN_ID"` | `page_id` 返却。Notion に row |
| 8 | `python -m app.cli mark-review <doc_id> --reason "smoke" --log-run-id "$RUN_ID"` | Firestore status=needs_review（mark-done は GCS 削除するのでスモークでは review 推奨）|

- ④⑤⑥はテスト案件フォルダ（実害のない場所）で行うか、けいすけと確認した案件で行う。`mark-done` は GCS 実削除なので本番投稿のスモークでのみ。
- `LOG_OUTPUT_DIR` 設定時は `<LOG_OUTPUT_DIR>/YYYY-MM-DD/$RUN_ID.jsonl` に各手順のログが追記される（監査用）。

### 6-5. Notion データソース API（2025-09-03、notion-client 3.1.0）

notion-client 3.1.0 は既定で Notion-Version `2025-09-03` を使い、DB クエリ／page 作成が **DB 単位 → データソース単位**に変わった。pc_cli は対応済み:

- `list-cases` は `data_sources.query(data_source_id=...)` を使う（`databases.query` は廃止）。
- `write-task` の page parent は `{"type": "data_source_id", "data_source_id": ...}`。
- data_source_id は `NOTION_DATA_SOURCE_ID` があればそれ、無ければ `databases.retrieve` の `data_sources[0]` を自動解決してキャッシュ。設計タスク管理 DB の実値は `1eb17f63-e23f-8070-aeb2-000b0f9cd108`（単一データソース）。
- プロパティ名（`タスク名`/`優先度`/`備考`/`OneDrive`、優先度 option `仕分け待ち`）は実 DB と一致、変更不要。

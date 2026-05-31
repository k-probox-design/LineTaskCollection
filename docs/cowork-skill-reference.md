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
            update-task(page_id, onedrive_link=dest, status=完了)  # 「仕分け完了」へ（status 型。"通常" 優先度は無い）
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
     list-case-folders --max-depth 1                       # ブランチ列挙（速い）
     list-case-folders --root <branch> --query <案件名片>   # ブランチに絞って名前引き（速い・絶対パス付き）
     ── Cowork が案件名 fuzzy match して案件フォルダの絶対パスを決定 ──
     ├ マッチあり・確信あり:
     │   write-task --case <案件名> --title ...        # Notion「仕分け待ち」row
     │   place-file --src <local> --case-folder <windows 絶対パス> --title ...   # 09.LINEやりとり資料/ へ（bug1 修正後は windows パスでよい）
     │   list-messages --around-doc <doc_id> --window-hours 48   # 前後会話を取得 → Cowork が関連分だけ選別
     │   write-log  --case-folder <windows 絶対パス> --date ... --filename "<date> 議事ログ.html" --content -   # 議事ログ HTML（stdin）
     │   update-task --page-id ... --status 完了 --onedrive-link ...   # 仕分け完了化（status 型）
     │   mark-done <doc_id>
     └ マッチなし・確信なし:
         けいすけにその場で対話確認 → 案件フォルダ手動作成 → 再仕分け
         または mark-review <doc_id> --reason ...      # needs_review に残す（GCS 保持）
```

- `list-case-folders` の `has_line_yaritori_folder` / `child_dir_count` / `last_modified` を案件判定のヒントに使う
- 案件フォルダ自体の自動作成はしない（NG）。`09.LINEやりとり資料/` サブフォルダは place-file/write-log が自動作成する

#### ★ list-case-folders は「2 段スコープ」で引く（A-2 性能対策、2026-05-30 実測）

`@@@` 全体を `--query` で再帰すると、サンドボックスの OneDrive オンデマンドマウントでは
非葉ディレクトリ毎の scandir ハイドレートで **45 秒の bash 制約を超える**（全走査は実用不可）。
代わりに**ブランチに絞ってから引く**:

```
# Phase1: トップレベルのブランチ一覧（速い・実測 ~0.7s）
list-case-folders --max-depth 1
#  → @@@決定案件 / @@HESTA_産業見積もり案件 / @@関電_Kenes / @HESTA_住宅決定案件 /
#     @HESTA_住宅見積もり案件 / テラチャージ / 野立て太陽光 … など

# Phase2: Notion 案件名/客先のヒントでブランチを推定し、--root で絞って名前引き（速い・実測 ~1.3s）
list-case-folders --root "C:\Users\knaka\OneDrive - 株式会社ビギン\@@@\@@関電_Kenes" --query 姫路
#  → hits=1（兵庫県_三和鶏園_姫路農場_様、absolute_path_windows 付き）
```

- `--root` は Windows パスでよい（実行時に実マウントへ解決）。
- 当てるブランチが分からなければ、客先/カテゴリから候補を 2〜3 個に絞って順に scoped query すればよい（各ブランチ内は速い）。
- 高速化の中身: `^\d{2}\.` 始まり（`00.案件…` や `09.受領資料`）は葉として配下に降りず、名前が query に合わない葉は dir 判定の stat すら省く。重いメタ（child数/mtime 等）はマッチ分だけ計算。

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

---

## 7. 議事ログ・会話取得・送信者（2026-05-30 拡張）

### 7-1. list-messages（議事ログの素材取得）

Firestore `intake_messages` から同一グループの前後メッセージを時系列（昇順）で返す。関連/非関連の判断は持たず、範囲内を機械的に全部返す（絞り込みは Cowork）。

```
list-messages --group-id <gid> [--around-doc <doc_id> | --since <iso> --until <iso>] [--window-hours 48] [--limit 200]
```

- `--around-doc <doc_id>`: その doc の `receivedAt` を中心に ±`window-hours`。資料 doc を中心に前後会話を取る糖衣。
- `--around-doc` 無しは `--since`/`--until`（ISO8601）で範囲指定。どちらも無ければ範囲無制限で最新 `--limit` 件。
- 返す各要素（値が無いキーは省略）: `doc_id` / `group_id` / `received_at`(ISO, UTC) / `message_type`(text/image/file/join 等) / `text` / `status` / `file_name` / `has_gcs`(bool) / `sender_user_id` / `sender_display_name` / `group_name`。
- `group_name` は `intake_groups.groupName`（受信側が LINE group summary API で解決保存した実グループ名）。グループ投稿なら実名、1:1/room や未取得は付かない。議事ログの部屋名に最優先で使う（Skill §4: group_name → room_names.txt → 自動ラベル）。

### 7-2. 議事ログ HTML 化（write-log --filename）

議事ログは HTML（LINE 風チャット）に標準化。**保存口は `write-log` を採用**（`place-file` ではない）。理由: write-log は `09.LINEやりとり資料/` 固定・上書き(overwrite=True) 意味論で、再生成される単一ログに合う。`place-file` は受領資料向けで重複時 ` (2)` 連番化するためログ上書きに不適。

- Cowork が HTML 文字列を生成し `write-log --filename "<date> 議事ログ.html" --content -`（stdin）で保存。
- `--filename` 省略時は従来どおり `<date> 議事ログ.md`。
- 旧 `.md` 議事ログは、同 date なら `.html` とは別名で残る。整理はけいすけ手動削除（Cowork マウントからは削除不可）。

### 7-3. 送信者（発言者）

- Cloud Run 受信側（Phase B 拡張）が message event の `source.userId` を保存し、LINE group member profile API で表示名解決して `senderUserId` / `senderDisplayName` を Firestore に保存する（best-effort・短期キャッシュ・受信本処理はブロックしない）。
- **この対応が Cloud Run にデプロイされた後に受信したメッセージのみ**送信者を持つ（過去分は webhook 原データに userId が無く遡及不可）。
- `list-messages` の `sender_display_name`（無ければ `sender_user_id`、それも無ければ「発言者不明」）を議事ログの発言者表示に使う。

### 7-4. Notion 優先度・ステータス・担当（実 DB 確認 2026-05-30）

- 優先度 select option: `Claude追記 / 仕分け待ち / すぐ / 高 / 中 / 低 / 趣味`。**"通常" は存在しない**。`Claude追記`（紫）はボット起因の目印で `write-task` の既定（`NOTION_DEFAULT_PRIORITY`）。
- **担当**(person 型): `write-task` が `NOTION_DEFAULT_ASSIGNEE_USER_ID`（けいすけ user_id `1b2d872b-594c-81ad-a589-00021d50994d`）を自動セットして人別ビューに乗せる。`--assignee-user-id` で個別指定も可。未設定だと作成者＝LineTaskBot になり人別グループから外れる。
- 完了の表現は status 型プロパティ **`ステータス`**（option: `未着手 / 情報待ち / 進行中 / 依頼中 / 中断中 / 中村確認待 / 修正依頼済 / 社内確認待 / レイアウト完了 / 不要 / 完了`、既定 `未着手`）。`update-task --status <値>`。
- **宿題（けいすけ）**: 仕分け/完了の状態管理を「優先度（Claude追記→本来値）」と「ステータス（→完了）」のどちらで回すか、mark-done 後の Notion 更新方針が未確定。決まり次第 Cowork へ通知される。

## 8. 実績 HTML の生成（export-results-html、2026-05-31）

定期実行の最後に **決定的コマンド** `export-results-html` を 1 回叩き、ブックマーク用の静的 HTML
`…\51.LINE投稿ボット\LINE仕分け実績.html` を Notion からまるごと再生成する（LLM 判断なし）。

```
python -m app.cli export-results-html      # 既定 out に上書き（--out で変更可、Windows パス可）
```

- **Notion『設計タスク管理』の【LINE】タスクが唯一の真実**。既存 HTML は読まない（OneDrive 未ハイドレートの罠回避）。Notion 失敗時は exit!=0 で既存ファイルを壊さない（atomic rename）。
- そのため **`write-task` 時に実ファイル名・確信度を備考へ機械可読に残す**こと（HTML が Notion だけから復元できるように）。`write-task --file-name "<実ファイル名>" --confidence "<確信度>"` を渡すと備考が次の書式になる:
  ```
  案件: 三和鶏園 姫路農場
  ファイル: 2026-05-30 提案01図面 三和鶏園姫路農場 野立て147.68kw.pdf
  確信度: 高
  groupId: Cd42d2bcf838ae883edd71ac4cee84ab7   ← 従来どおり --note 等で備考に含める
  ```
  needs_review（仕分け待ち）は案件・ファイル未確定なので `--file-name`/`--confidence` は省略可（HTML 側は空なら「—」表示）。
- SKILL.md の末尾とスケジュール 4 本の prompt に「最後に `export-results-html` を 1 回」を追記する（Cowork 宿題）。

### 8-1. 実データ頑健化（2026-05-31）— 抽出は備考の独立行に依存しない

実 Notion 備考は独立行でなくインライン（`key=value`、`<br>`/スラッシュ/句点区切り）なので、抽出を頑健化した:
- **gid**: `groupId\s*[=:：]\s*(C[0-9a-fA-F]{32})`。直後の `(部屋名)` を `room_name` に保持（行データに入れるが現テンプレ表示は未対応＝gid フォールバックのまま。表示は Cowork が後日）。
- **conf**: `確信度\s*[=:：]\s*([^\s。/、（(<]+)`（`高/中/低` 等）。
- **fname**: ①備考 `ファイル:` 行（新書式・最優先）→ ②OneDrive プロパティ末尾が拡張子付きならその basename → ③空（多ファイル/フォルダ止まり）。
- **folder**: OneDrive が **http(s)** のときだけ 09 フォルダ URL を導出（ファイル URL は親、フォルダ URL はそのまま、末尾が `09.LINEやりとり資料` でなければ付加）。**`%20` 等はデコードして生スペースで持つ**（テンプレが `encodeURI` するので二重エンコード回避）。ローカルパスは `folder` 空＝リンク無し。
- **case**: 備考 `案件:` 行（trim・全角スペース→半角のみ。深い正規化はしない）。

**Skill 側の含意**: HTML に資料/会話ログのリンクと確信度を出すには、`write-task` 時に **OneDrive プロパティへ正確な SharePoint URL**（単一資料はファイル URL、複数は 09 フォルダ URL）を入れること。確信度・部屋名は備考のインライン（`確信度=…` / `groupId=…(部屋名)`）でも `--confidence` でも拾える。

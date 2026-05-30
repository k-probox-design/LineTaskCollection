# 決定ログ

## 2026-05-27 — Phase A 技術判断

### line-bot-sdk v3 を採用（v4 ではなく）

v3 系は安定リリースで広く利用されている。Phase A では署名検証にのみ使用するが、将来の拡張性を考慮して SDK を依存に含めた。ただし Phase A の Webhook 処理は SDK のハンドラ機構を使わず、自前で `X-Line-Signature` を検証している（SDK の `WebhookParser` は同期的で FastAPI の async と相性が悪いため）。

### コンテンツダウンロードに httpx を使用（line-bot-sdk 内蔵メソッドではなく）

line-bot-sdk v3 の `LineBotApi.get_message_content()` は同期 I/O。FastAPI の async エンドポイント内で `httpx.AsyncClient` を使い非同期ダウンロードする方が自然。Phase B で GCS ストリーミングアップロードに切り替える際もこの方が拡張しやすい。

### Phase A では Webhook を同期処理

画像 1 枚なら数秒以内で完了する想定。5 秒を超えるケース（大きい動画など）が出た場合は Phase B で BackgroundTasks に分離する。

## 2026-05-28 — Phase B 判断（Cowork 確定、CLAUDE.md に永続決定として記載済み）

### Firestore / GCS Emulator は使わず本番直書き

Emulator の学習コストが見合わない。Phase A〜B は本番 1 プロジェクト方針と整合し、小規模なら無料枠内で収まる。

### テキストメッセージも Firestore に保存

受信ログ＝検索アーカイブの方針と整合。テキストも過去検索で使う価値がある。ファイル本体は保存せず、メタ＋ text フィールドのみ。

### BackgroundTasks でコンテンツダウンロードを分離

Cloud Run のタイムアウト＋ LINE Webhook の即 200 要件。画像複数枚や動画で Webhook 応答が遅れるリスクを排除。FastAPI の `BackgroundTasks` を使用。

### line-bot-sdk-python を依存から外す

Phase A で SDK を入れていたが未使用。自前検証＋httpx が async と相性がよく、Phase B でも継続。未使用依存を残さない方針。

### コンテンツダウンロードを同期 httpx.Client に変更

BackgroundTasks はスレッドプールで実行されるため、async I/O を使う意味が薄い。`httpx.Client`（同期）でシンプルに。GCS の `upload_from_string` も同期 API のため統一。

## 2026-05-28 — Phase B 残課題対応

### Cloud Run min-instances=1 + Startup CPU Boost を採用

min-instances=0 だと cold start で初回 Webhook がタイムアウトし、LINE 取りこぼしのリスク（実際に Webhook 検証 1 回目失敗を観測）。業務用ボットの取りこぼし回避のため min-instances=1 で常駐。月額 ¥1,000〜2,000 の上振れは許容（Cowork 判断）。CPU Boost は無料で再起動時の起動短縮にも効く二重対策。

### structured logging は案 A（python-json-logger で stdout に JSON）を採用

`gcloud run services logs read` のデフォルト出力にアプリ層 `logger.info` が出ない問題への対応。案 B（google-cloud-logging ハンドラで直接 API 送信）は起動時 Auth 解決や例外時の挙動に注意が要り、Phase B 軽量化方針に合わない。案 A は stdout に JSON を吐くだけで Cloud Logging が jsonPayload として解釈し、追加の認証・ネットワーク依存がない。`levelname` を `severity` にリネームして重大度も認識させる。

## 2026-05-28 — Phase C 技術判断

### 案件名 → SharePoint フォルダのマッピングは (a)「案件名 = フォルダ名」を採用

kickoff の選択肢 (a)/(b) のうち (a) を初期採用。`SHAREPOINT_ROOT/<案件名>/09.受領資料/` のように案件名をそのままフォルダ名に使う。設計事務所の業務実態として案件名と SharePoint フォルダ名は一致しているのが通例で、(b)（Notion の OneDrive URL フィールド参照）より実装がシンプル。運用で不整合が出たら (b) に切り替える。

### 仕分け判断は Claude Sonnet 4.6 + 構造化出力（messages.parse）

kickoff 指定どおり `claude-sonnet-4-6` を採用（マルチモーダルで画像/PDF を読む必要がある）。出力は `client.messages.parse(output_format=ClassifyResult)` で Pydantic 検証付きの構造化 JSON を取得。プロンプトキャッシュはシステムプロンプト+案件候補リスト（1 run 内で不変）に `cache_control` を付与。thinking は分類タスクのため disabled でコスト・レイテンシを抑える。

### 確信度しきい値の判定は orchestrator 側に集約

classify はモデルの生出力（case_name と confidence）をそのまま返し、しきい値（0.8）による分岐は orchestrator が一元的に行う。classify を純粋な「Claude 呼び出し」に保ち、テストとロジックを分離するため。

### 議事ログのファイル名と個別ファイル名の厳密な相互リンクは Phase C 後の精緻化とする

議事ログ Markdown 内のファイル参照は受信時の元ファイル名（`fileName`）で `../09.受領資料/<元ファイル名>` を指す。個別ファイルは `YYYY-MM-DD <Claude推測タイトル>.<ext>` で保存されるため、現状リンクは厳密一致しない。両者を完全一致させるには分類結果のタイトルを log_writer に渡す必要があり、複雑化を避けて Phase C 後に精緻化する。

### コンテンツダウンロードと Notion OneDrive リンク

PC 側スクリプトは同期 SDK（google-cloud-storage / firestore / notion-client / anthropic 同期クライアント）で実装。Notion の OneDrive フィールドには SharePoint URL ではなくローカルパスの `file://` URL を入れる（kickoff §注意事項のとおり、OneDrive 同期に任せ SharePoint API での URL 取得は避ける方針）。けいすけが Notion から開いたとき同期済みなら参照できる。

## 2026-05-29 — Phase C 実行環境を WSL 一本化（A 方針）、Cowork 監査はログ複製で代替

pc_worker の実行環境を **WSL2 リポジトリ内に一本化**（A 方針）。OneDrive 配下へ一式コピーして Windows Python で動かす B-2 案は不採用。

- 理由: WSL リポジトリと OneDrive コピーの二重管理が運用負債になる（更新の都度コピーを忘れるとバージョン乖離）
- `.env` も WSL 側のみ。SharePoint 書き込みは WSL から `/mnt/c/.../OneDrive/...` 経由で同期に委ねる
- A 方針では Cowork がコード・`.env`・実行コンソールに直接アクセスできないため、監査経路を 2 点で代替:
  1. `pc_worker/.env.example` を受け渡しフォルダ（`Coworkとの受け渡し/`）に複製し、Cowork が必要項目を把握できるようにする（実値は共有しない）
  2. `config.add_file_handler(run_id)` で実行ログを `$LOG_OUTPUT_DIR/YYYY-MM-DD/<run_id>.jsonl`（OneDrive 配下）に JSON Lines で複製出力。`LOG_OUTPUT_DIR` 未設定・書込不可時は WARN を出してコンソールのみで継続（ログ複製のために本処理を止めない）

これにより CLAUDE.md §永続決定事項 Phase C 実装方針の項目 17/18（Cowork 許可フォルダへコピー配置）は本決定で上書きされる。

## 2026-05-29 — Phase C を Cowork 主導仕分けに転換（Phase C'）

Phase C 実地確認の手前で、仕分け判断を **Cowork（Opus）が担う構成**に転換。pc_worker（判定ロジック内蔵）を、判定を持たない薄い CLI ラッパー **pc_cli** に再構築した。

### 転換理由（5 つ）

1. **コスト**: API 案 月 ¥1,000〜3,000 → Cowork 案 ¥0（Claude Max 20x サブスク内で完結、`ANTHROPIC_API_KEY` 不要）
2. **精度**: claude-sonnet-4-6（API）→ claude-opus-4-7（Cowork）の上位モデル
3. **運用品質**: 確信度低のものをけいすけにその場で対話確認できる（API 案の needs_review は溜まる一方）
4. **Phase D 連続性**: アーカイブ検索ヘルパーも Cowork なので仕分け・記録・検索が同一プロセスで完結
5. **鍵管理の簡素化**: `ANTHROPIC_API_KEY` が不要に

### Cowork 案 vs API 案

| 観点 | API 案（Phase C） | Cowork 案（Phase C'）|
|------|------------------|---------------------|
| コスト | 月 ¥1,000〜3,000 | ¥0（サブスク内）|
| 判定モデル | claude-sonnet-4-6 | claude-opus-4-7 |
| 即時性 | バッチ 1 回実行 | スケジュール 4 回/日（朝昼夕夜）。数時間以内反映で十分 |
| 確信度低の扱い | needs_review に溜まる | その場でけいすけに対話確認 |
| 運用負担 | スクリプト保守 | Cowork Skill + pc_cli |

投稿想定（けいすけヒアリング 2026-05-29）: ファイル 1 日 50 件未満 / テキスト多め（タスク化要あり）/ 即時性は数時間以内で十分。

### 旧実装の流用・廃止判定

| ファイル | 判定 |
|---|---|
| config.py | 流用（判定系変数 ANTHROPIC_API_KEY/CLASSIFY_*/LOG_AGGREGATION_HOURS/CANDIDATE_LOOKBACK_DAYS 削除、TMP_DOWNLOAD_DIR 追加、ログを stderr 化）|
| pull.py | 流用 → CLI 化（list_pending / download / mark_done / mark_review）|
| notion_writer.py | 流用 → CLI 化（list_cases / write_task / update_task、3 req/sec スロットル維持）|
| sharepoint_writer.py | 流用 → CLI 化（place-file、overwrite 追加、パストラバーサル対策維持）|
| log_writer.py | 流用（build_session_log は参照用に残置、write-log は Cowork 提供 content を書く）|
| classify.py | **削除**（Cowork が直接マルチモーダル判定）|
| orchestrator.py | **削除**（Cowork が pc_cli を順序立てて呼ぶ）|
| main.py | **削除** → cli.py に置換 |
| cli.py / winpath.py | **新規**（Typer 9 サブコマンド / unix↔windows パス変換）|

旧 classify のシステムプロンプト・orchestrator の確信度分岐フローは `docs/cowork-skill-reference.md` に退避（Cowork Skill 移植用）。

### pc_cli の出力契約

stdout=結果 JSON のみ、ログ=stderr（+ LOG_OUTPUT_DIR ファイル）。Cowork が stdout の JSON だけをパースできるよう、Phase B/C ではコンソールログを stdout に出していたのを **stderr に変更**。

## 2026-05-29 — SHAREPOINT_ROOT 配下構造ヒアリングを受けて、固定パス前提から絶対パス指定 + 再帰探索に変更

Phase C' kickoff は `<SHAREPOINT_ROOT>/<案件名>/09.受領資料/` の固定パスを前提にしていたが、けいすけの実 SharePoint 構造（`SHAREPOINT_ROOT=/mnt/c/Users/knaka/OneDrive - 株式会社ビギン/@@@`）を Cowork が確認した結果、固定パスが成立しないと判明:

- ステータスフォルダ（`@@@決定案件` 等）配下の案件 / 直接案件 / 非案件フォルダが混在
- 階層深さが案件ごとに 2〜3 階層と不規則（年フォルダ経由もあり）
- 案件内の番号付きサブフォルダ命名が不統一（同じ `09.` でも意味が違う）

### 変更内容

- **`list-case-folders` 新設**: SHAREPOINT_ROOT 配下を `iterdir()` 再帰（`--max-depth` 既定 3）でスキャンし、案件フォルダ候補のメタ（folder_name / parent / depth / 絶対パス unix+windows / child_dir_count / has_line_yaritori_folder / last_modified）を返す。Cowork が案件名と fuzzy match する材料
- **`place-file` / `write-log` を `--case-folder <絶対パス>` 指定に変更**（`--case`/`--kind` 廃止）。Cowork が list-case-folders で得た絶対パスを直接渡す

### けいすけ確定の運用ルール（5 点）

1. **仕分け対象範囲**: SHAREPOINT_ROOT 直下フォルダ全部（ステータスフォルダ配下も）。除外リストは設けず Cowork の judgement に任せる（マッチしなければ needs_review）
2. **LINE 由来資料の統一格納**: 画像/PDF/議事ログ すべて `<案件フォルダ>/09.LINEやりとり資料/` に統一（`09.受領資料` は使わない）
3. **`09.XXX` 並列許容**: 同じ案件フォルダ内に `09.受領資料` と `09.LINEやりとり資料` が並んでも OK
4. **サブフォルダ自動作成 OK**: `09.LINEやりとり資料/` が無ければ pc_cli が新規作成（`created_subfolder` フラグで通知）
5. **案件フォルダ自体の自動作成 NG**: マッチする案件フォルダがなければ needs_review。けいすけが手動でフォルダ作成 → 再仕分け

パストラバーサル対策（タイトルのサニタイズ + 案件フォルダ配下への封じ込め）は維持。`--case-folder` が存在しない場合は exit!=0 + `{"error":"case_folder_not_found"}`。

## 2026-05-30 — Phase C' 実行経路を A 案（Cowork サンドボックス内で仕分け完結）に確定

2026-05-29 の A 方針（pc_cli は WSL でのみ実行、Cowork は監査のみ）は、Cowork の実行環境を実機確認した結果見直した。

### 確認した事実（Cowork 実機、2026-05-30）

- Cowork の bash は WSL ではなく**独立した Linux サンドボックス**（Ubuntu 22 / Python 3.10）
- マウントは OneDrive の選択フォルダのみ（`/sessions/<動的セッション名>/mnt/<フォルダ名>/`、セッション名は実行毎に変わる）。WSL リポジトリ・`@@@` には未到達（追加マウントで `@@@` は到達可に）
- ターミナルへの自動入力は権限ティアでブロック（無人で WSL ターミナルを叩く道は無い）
- ネットワークは開いている（Cloud Run / Firestore / Notion / pypi 到達可）

### 決定（けいすけ承認済み）

- 実行経路 **A 案**: pc_cli の実行・認証・`@@@` 参照を Cowork サンドボックスが届く場所（OneDrive 配下＋追加マウント）に寄せ、仕分けをサンドボックス内で完結させる。B 案（Cloud Run に HTTP API を生やす）は不採用。
- Phase C の「実行は WSL 完結 / 鍵は WSL のみ / 鍵ファイル無し」は本件で見直し。

### 実装（このタスク）

- **動的マウントパスの実行時解決は pc_cli 側の責務**（`app/mounts.py` 新設）。`.env` の `MOUNT_MAP` に静的 Windows パスを列挙すれば、pc_cli が ①自身の位置から現セッション mnt ベース → ②WSL `/mnt/c` → ③`/sessions/*/mnt` glob の順で実マウントを特定。Skill はセッション名を注入しなくてよい。
- **winpath 一般化**（`app/winpath.py`）: (unix 接頭辞 ↔ windows 接頭辞) 写像を最長一致で適用し、`/mnt/<drive>` 規則をフォールバックに残す。`destination_windows` 等が `/sessions/<動的>/mnt/@@@/...` でも `C:\...\@@@\...` に戻る。
- **パス系 .env（SHAREPOINT_ROOT / TMP_DOWNLOAD_DIR / LOG_OUTPUT_DIR / GOOGLE_APPLICATION_CREDENTIALS）は Windows パスでも unix パスでも記述可**。Windows 形式なら実行時に unix へ解決（後方互換: WSL 開発は従来の `/mnt/c` 値のまま）。
- **GCP 認証は SA 鍵ファイル（`GOOGLE_APPLICATION_CREDENTIALS`）＋ ADC 両対応**。鍵パスが Windows 形式なら実マウントへ解決して `os.environ` に書き戻す。鍵 JSON は `secrets/`（同期・コミット対象外）。
- **依存はバージョン固定 `requirements.txt`**（Python 3.10/3.12 双方で解決可）。揮発サンドボックス前提で起動毎に `pip install -r requirements.txt --break-system-packages`。vendoring は `google-cloud-*` のバイナリ依存が重いため不採用。
- **OneDrive 実行コピーへの同期**: 正は WSL リポジトリ。`scripts/sync-pc-cli-to-onedrive.sh` で `51.LINE投稿ボット/pc_cli/` へ rsync（`.env` / `secrets/` は同期せず秘密値を保護）。
- 不要になった `ANTHROPIC_API_KEY` / `CLASSIFY_CONFIDENCE_THRESHOLD` を config / conftest から撤去。

`requires-python` を 3.11 → 3.10 に引き下げ（サンドボックスが 3.10）。テストは 42 → 64 pass（mounts / winpath 一般化 / config の Windows パス解決・鍵正規化を追加）。

## 2026-05-30 — notion_writer を Notion データソース API（2025-09-03）対応に修正

サンドボックススモークで `list-cases` が `'DatabasesEndpoint' object has no attribute 'query'` で exit=1。原因は **notion-client 3.1.0 が既定で Notion-Version `2025-09-03` を使う**こと。このバージョンで DB クエリ／page 作成が DB 単位 → データソース単位に移動した。

### 対応（案 A: データソース API へ移行を採用、案 B のバージョン据え置きは退避策として不採用）

- `data_source_id` を `databases.retrieve(database_id)["data_sources"][0]` から解決してキャッシュ（`_get_data_source_id`）。`NOTION_DATA_SOURCE_ID` で固定も可（未設定なら自動解決）。当 DB は単一データソース前提（複数化したら index 0 固定を見直す）。
- `list_cases`: `databases.query` → `data_sources.query(data_source_id=...)`。filter/start_cursor/has_more/next_cursor は従来どおり。
- `write_task`: page parent を `{"type": "data_source_id", "data_source_id": <dsid>}` に変更。
- `update_task`: `pages.update(page_id=...)` は page_id 指定のため変更不要。
- スモークで実 DB のプロパティ名（`タスク名`/`優先度`/`備考`/`OneDrive`、優先度 option `仕分け待ち`）が定数と一致と確認済み、変更なし。実 data_source_id = `1eb17f63-e23f-8070-aeb2-000b0f9cd108`。

`write_task` の実 DB 作成は副作用（row 増）のためけいすけ立ち会いで 1 回だけ検証 → 作成 row は削除する運用。テストは 64 → 66 pass（data_source_id 解決 + parent 形状を新 API に追従）。

## 2026-05-30 — 同期スクリプトに OneDrive ピン留め（Pinned）を組み込み

Notion 修正の再スモークで、OneDrive 実行コピー `51.LINE投稿ボット\pc_cli\` の変更 `.py` が「クラウドのみ（未ハイドレート）」になり、Cowork の Linux マウント越しに**中身が途中で切れて読めない**実害が出た（`notion_writer.py` が 5395B で頭打ち → `ast.parse` 失敗、さらに残存 `.pyc` で旧挙動に化ける二次被害）。

### 対応（`scripts/sync-pc-cli-to-onedrive.sh`）

- rsync 直後に **`attrib +P -U "<pc_cli>\*" /S /D`**（cmd.exe interop）で配下を Pinned 化＝OneDrive が実体をローカル保持し続ける。
- rsync `-t` が引き継ぐ古い mtime のキャッシュ巻き戻りを避けるため、実コピーの mtime を `find -exec touch` で現在時刻へ更新（`secrets/`/`pc_worker_tmp/`/`pc_worker_logs/` は prune）。
- 末尾に代表ファイル（`app/notion_writer.py`）の正↔コピーのサイズ一致検証を入れ、未ハイドレート時に WARN。
- `--dry-run` 時は mtime 更新・ピン留め・検証をスキップ。

検証結果: `pc_cli\app\*.py` 全 10 ファイルが `pinned=True` / `offline=False`、サイズ正一致。`.env`（けいすけの実値）と `secrets/` は rsync 除外のまま保持（同期・削除・コミットなし）。けいすけの手動ピンは今後不要。

## 2026-05-30 — ハイドレート恒久対策を「OneDrive ピン留め」から「git clone」に変更（A 案）

再スモークで、`290d384` のピン留めは **Cowork の Linux マウントからは効いていない**ことが実測判明。Windows 側 Read は完全（`offline=False`/`pinned=True`/size 一致）だが、同一セッションの Cowork bash マウントは依然 `notion_writer.py` を 5395B で途中切れ・mtime も 5/29 に巻き戻ったまま返す。`attrib +P` は「evict しない」フラグであって実体ハイドレートを保証せず、新セッション再マウントでも解消しなかった。Windows PowerShell 検証は Cowork 可読性を保証しない。

ロジック自体は再スモークで全 green（`list-cases` 199 案件 / `write-task` 本番 row 作成→archive 成功 / SA 鍵 / MOUNT_MAP・winpath）。残ブロッカーはハイドレート 1 点のみ。

### 決定（候補 a/b/c から b を採用）

- **(b) git clone を本番の正**: Cowork サンドボックスはコードを GitHub private repo から git clone してネイティブ fs `/outputs/linetask` で実行する。OneDrive プレースホルダ依存を断つ。`scripts/sandbox-bootstrap.sh`（clone→`.env` コピー→pip→**AST 検証**）を新設し、Skill は PAT 付き curl で取得して実行。
- OneDrive からは「小サイズで完全に読める」`.env`（PAT/Notion 鍵等）と SA 鍵だけを読む。`GOOGLE_APPLICATION_CREDENTIALS` は Windows パスのまま、`mounts.py` の `/sessions/*/mnt` glob フォールバックで実マウントへ解決（`/outputs` から動かしても機能、テスト追加で担保）。
- 検証方法の是正: Windows 側 size ではなく **「サンドボックスが実際に読むバイト列」で AST parse**（bootstrap と smoke 手順 0a）。
- (a) 強制ハイドレート（`/mnt/c` 越し全 `.py` read→pin）は `sync-pc-cli-to-onedrive.sh` に**補助として残す**が、Cowork マウント追随は保証外。OneDrive コピーの役割は「WSL 開発／git 不達フォールバック／`.env.sandbox.example` 配布」に降格。
- (c) FoD 外配置は Cowork が OneDrive 選択フォルダしかマウントできず不成立。

### けいすけ手作業（増分）

- GitHub fine-grained PAT（対象 repo = 当 repo のみ、Contents:Read のみ）を発行し、OneDrive `pc_cli/.env` の `GITHUB_PAT=` に記入。

テストは 66 → 67 pass（`/outputs` 実行＝session 外での glob フォールバック解決を追加）。

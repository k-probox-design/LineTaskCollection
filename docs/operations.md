# 運用手順

## LINE 公式アカウント初期設定（けいすけ手作業）

1. [LINE for Business](https://www.linebiz.com/) で公式アカウントを作成（無料・コミュニケーションプラン）
2. 公式アカウントマネージャー「設定 → Messaging API → 利用する」を実行
3. LINE Developers でチャネルアクセストークン（長期）を発行、チャネルシークレットを控える
4. 応答設定: 「応答メッセージ OFF」「Webhook ON」
5. **【最重要】アカウント設定 → トークへの参加 → 「グループ・複数人トークへの参加を許可する」を ON**
   - **これを忘れるとボットがグループ招待直後に退出する。必ず確認すること**
6. Webhook URL に `<エンドポイント>/line/webhook` を登録（Phase A は ngrok URL、Phase B 以降は Cloud Run URL）
7. 個人 LINE で公式アカウントを友だち追加 → テスト用グループに招待

## ローカル動作確認手順（Phase A）

### 前提

- WSL2 / Ubuntu 24.04
- Python 3.11+
- ngrok インストール済み

### 手順

```bash
# 1. サーバーディレクトリへ移動
cd ~/projects/LineTaskCollection/server

# 2. 仮想環境の作成・有効化
python3 -m venv .venv
source .venv/bin/activate

# 3. 依存パッケージのインストール
pip install -e ".[dev]"

# 4. .env を作成し、けいすけがシークレットを入力
cp .env.example .env
# → LINE_CHANNEL_SECRET と LINE_CHANNEL_ACCESS_TOKEN の値を入れる

# 5. FastAPI 起動
uvicorn app.main:app --reload --port 8000

# 6. 別ターミナルで ngrok を起動
ngrok http 8000
# → 表示された https URL を控える（例: https://xxxx.ngrok-free.app）

# 7. LINE Developers の Webhook URL に設定
#    <ngrok-url>/line/webhook
#    → 「Verify」ボタンで接続確認

# 8. テストグループにボットを招待
#    → サーバーログに [JOIN] groupId=<...> が出ることを確認

# 9. テストグループに画像を1枚投稿
#    → server/tmp/ にファイルが保存されることを確認
ls server/tmp/
```

### テスト実行

```bash
cd ~/projects/LineTaskCollection/server
source .venv/bin/activate
pytest tests/ -v
```

## Phase B: GCP プロジェクト初期設定手順（けい��け手作業）

### Step 1: GCP プロジェクト作成

1. [GCP コンソール](https://console.cloud.google.com/) → 新規プロジェクト作成
2. プロジェクト名: `probox-linetask-prod`、組織: なし
3. 課金アカウントを既存個人 Billing Account に紐付け
4. 以下の API を有効化（「API とサービス → ライブラリ」から検索）:
   - Cloud Run Admin API
   - Cloud Build API
   - Cloud Storage API
   - Cloud Firestore API
   - Secret Manager API
   - Artifact Registry API

### Step 2: Firestore データベース作成

1. [Firestore コンソール](https://console.cloud.google.com/firestore) → 「データベースを作成」
2. モード: **ネイティブモード**
3. リージョン: **asia-northeast1（東京）**

### Step 3: GCS バケット作成

1. [GCS コンソール](https://console.cloud.google.com/storage) → 「バケットを作成」
2. 名前: `probox-linetask-prod-intake`
3. リージョン: **asia-northeast1（東京）**
4. ストレージクラス: **Standard**
5. アクセス制御: 均一（uniform）

### Step 4: Secret Manager にシークレット登録

1. [Secret Manager](https://console.cloud.google.com/security/secret-manager) → 「シークレットを作成」
2. 2 つ作成:
   - `line-channel-secret` ← チャネルシークレットの値
   - `line-channel-access-token` ← チャネルアクセストークン（長期）の値

CLI で作成する場合:
```bash
gcloud secrets create line-channel-secret --replication-policy=automatic --project=probox-linetask-prod
echo -n "<値>" | gcloud secrets versions add line-channel-secret --data-file=- --project=probox-linetask-prod

gcloud secrets create line-channel-access-token --replication-policy=automatic --project=probox-linetask-prod
echo -n "<値>" | gcloud secrets versions add line-channel-access-token --data-file=- --project=probox-linetask-prod
```

### Step 5: Cloud Run 用サービスアカウント作成＋権限付与

1. [IAM → サービスアカウント](https://console.cloud.google.com/iam-admin/serviceaccounts) → 作成
2. 名前: `linetask-cloudrun`、ID: `linetask-cloudrun@probox-linetask-prod.iam.gserviceaccount.com`
3. 以下のロールを付与:
   - プロジェクト全体: `Cloud Datastore ユーザー`（Firestore 読み書き）
   - GCS バケット `probox-linetask-prod-intake` に対して: `Storage Object 管理者`
   - Secret `line-channel-secret` に対して: `Secret Manager Secret Accessor`
   - Secret `line-channel-access-token` に対して: `Secret Manager Secret Accessor`

### 推奨: Budget Alert 設定

「課金 → 予算とアラート」で月額 ¥1,000 のアラートを設定しておくと安心。

---

## Cloud Run デプロイ手順（Claude Code 実施）

### 前提

- けいすけが Step 1〜5 を完了していること
- WSL2 で `gcloud` CLI がインストール済みかつ認証済み

### デプロイ実行

```bash
cd ~/projects/LineTaskCollection/server
./cloudrun-deploy.sh
```

デプロイ完了後、出力に表示される Service URL（例: `https://linetask-receive-xxxxx-an.a.run.app`）を控える。

---

## Cloud Run のログの見方

アプリは structured logging（stdout に JSON）でログを出す。Cloud Logging は `severity` と `message` を認識する。

**注意**: `gcloud run services logs read` の簡易ビューは JSON ログ（jsonPayload）を**空行で表示してしまう**（textPayload しか表示しない CLI の制約）。アプリ層ログ（`[JOIN]`、`[GCS]`、`[SIGNATURE]` 等）を見るには次のいずれかを使う。

### 方法1: gcloud logging read（推奨）

```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=linetask-receive AND jsonPayload.message:*" \
  --project=probox-linetask-prod --limit=30 \
  --format="table(timestamp, severity, jsonPayload.name, jsonPayload.message)"
```

### 方法2: Cloud Run コンソールの「ログ」タブ

Cloud Run → linetask-receive → ログ。`message` フィールドが要約行に表示され、severity でフィルタもできる。

### リクエストアクセスログ（uvicorn）を見る

GET/POST のアクセスログは textPayload なので `gcloud run services logs read linetask-receive --region=asia-northeast1 --limit=30` で見える。

---

## LINE Webhook URL 切替手順（けいすけ手作業）

Cloud Run デプロイ後に実施:

1. LINE Developers → チャネル設定 → Messaging API → Webhook URL
2. URL を `https://<cloud-run-url>/line/webhook` に変更
3. 「検証」ボタンをクリック → 成功を確認
4. テストグループに画像を投稿 → GCS + Firestore に書き込まれることを確認

---

## WSL2 で ADC（Application Default Credentials）を設定する

ローカル開発で本番 GCP（Firestore / GCS）に直書きするとき、ADC が必要。
本番 Cloud Run はサービスアカウントで動くため ADC 不要だが、ローカルから実機テストしたい場合に使う。
WSL2 ではブラウザ連携が不安定（`gio: Operation not supported`）なため `--no-browser` フローで設定する。

1. WSL2 で以下を実行:
   ```bash
   gcloud auth application-default login --no-browser
   ```
2. 出力された URL をコピーして、Windows 側のブラウザに貼り付け
3. Google アカウントで認証
4. リダイレクト先の URL（`http://localhost...` のような文字列）をコピー
5. WSL2 のターミナルに戻って、表示されているプロンプトにペースト
6. `Credentials saved to file: ...` が出れば成功

確認:
```bash
gcloud auth application-default print-access-token
```
何か文字列が出れば OK。

### トラブル時の対応

- `gcloud` が見つからない場合: Google Cloud SDK が未インストール。`$HOME/google-cloud-sdk/bin` を PATH に追加するか、`$HOME/google-cloud-sdk/bin/gcloud` とフルパスで呼ぶ
- `--no-browser` でも CSRF state mismatch が出る場合: 一度 `gcloud auth application-default revoke` してからやり直す。ブラウザのタブは 1 つだけ開いて操作する

---

## Phase C: Notion Integration「LineTaskBot」のセットアップ（けいすけ手作業）

### Step 1: Integration「LineTaskBot」作成

1. [Notion Integrations](https://www.notion.so/profile/integrations) を開く
2. 「+ 新しいインテグレーション」をクリック
3. 名前: **LineTaskBot**、関連付けるワークスペース: ビギン
4. タイプ: 「内部インテグレーション」
5. 「保存」→ 詳細画面で **「内部インテグレーションシークレット」をコピー**（`secret_xxxxx...` または `ntn_xxxxx...` 形式）
6. シークレットは **後で `pc_worker/.env` に直接貼り付け**、チャットや受け渡しフォルダには貼らない（`NOTION_API_KEY`）

### Step 2: 設計タスク管理 DB に LineTaskBot を招待

1. Notion で「設計タスク管理」DB のページを開く
2. 右上「…」→「接続」→ **LineTaskBot** を選択 →「確認」

### Step 3: Database ID を控える

1. DB ページの URL を開く（例: `https://www.notion.so/xxxxxxxx?v=yyyyyyy`）
2. URL の `?v=` より前の 32 文字 hex が **Database ID**
3. `pc_worker/.env` の `NOTION_DATABASE_ID_DESIGN_TASK` に貼り付け

> **実地確認時の注意**: `pc_worker/app/notion_writer.py` 冒頭の `PROP_TITLE` / `PROP_PRIORITY` / `PROP_NOTE` / `PROP_ONEDRIVE` は設計タスク管理 DB の実際のプロパティ名を推定値で定義している。DB の実際のプロパティ名と相違があれば、この定数だけ修正する。

---

## Phase C: SharePoint 同期フォルダのルートパス確認（けいすけ手作業）

PC の OneDrive 同期フォルダで、案件フォルダの**親ディレクトリ**のパスを確認する。例:

```
C:\Users\knaka\OneDrive - 株式会社ビギン\Documents\案件\
└── コスモス ソラプロ\
    ├── 09.受領資料\        ← 個別ファイルの格納先
    └── 09.LINEやりとり資料\ ← 議事ログの格納先
```

上の例なら `C:\Users\knaka\OneDrive - 株式会社ビギン\Documents\案件\` を `pc_worker/.env` の `SHAREPOINT_ROOT` に貼り付ける（シークレットではないのでチャット共有可）。

---

## Phase C': pc_cli の使い方（Cowork 主導仕分け）

Phase C' で仕分け判断は **Cowork（Opus）が担う**。pc_cli は GCS pull / Notion write / SharePoint write の**薄い API ラッパー**で、判定ロジックを持たない。Cowork が Skill 経由で各サブコマンドを bash で順序立てて呼ぶ。

### セットアップ

```bash
cd pc_worker
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
# NOTION_API_KEY / NOTION_DATABASE_ID_DESIGN_TASK / SHAREPOINT_ROOT / TMP_DOWNLOAD_DIR / LOG_OUTPUT_DIR を入力
# GCP は ADC（gcloud auth application-default login）で解決。ANTHROPIC_API_KEY は不要（Cowork が判定）
```

### 起動

```bash
python -m app.cli <subcommand> [options]
```

stdout は結果 JSON のみ、ログは stderr（+ `LOG_OUTPUT_DIR` ファイル）に出る。エラー時は exit code != 0 で stderr に `{"error": "...", "detail": "..."}`。

### サブコマンド一覧（10 個）

| サブコマンド | 役割 |
|------------|------|
| `pull-pending [--limit=50]` | Firestore status=pending をメタのみ JSON 配列で出力（GCS は触らない）|
| `download <doc_id> [--dest-dir]` | GCS バイナリを DL、unix/windows 両形式のパスを返す |
| `list-cases [--days=90]` | Notion から直近 N 日更新の案件名候補を出力 |
| `list-case-folders [--root] [--max-depth=3]` | SHAREPOINT_ROOT 配下を再帰スキャンして案件フォルダ候補を出力 |
| `write-task --case --title [--priority=仕分け待ち] [--note] [--onedrive-link]` | Notion 新規 row |
| `update-task --page-id [--case --title --priority --note --onedrive-link]` | Notion 部分更新（優先度変更で仕分け完了扱い）|
| `place-file --src --case-folder --title [--date]` | 案件フォルダ(絶対パス)配下の 09.LINEやりとり資料/ にファイル配置 |
| `write-log --case-folder --date --content` | 議事ログ Markdown を 09.LINEやりとり資料/ に書き込み（固定名・上書き、`--content -` で stdin）|
| `mark-done <doc_id>` | Firestore done + GCS 削除 |
| `mark-review <doc_id> [--reason]` | Firestore needs_review、GCS 保持 |

全サブコマンドに `--log-run-id=<外部ID>` オプションがあり、Cowork 側から共通 run_id を渡して同一仕分けセッションのログを束ねられる。

LINE 由来資料（画像/PDF/議事ログ）は案件フォルダ配下の **`09.LINEやりとり資料/` に統一**して格納する（`09.受領資料` は使わない）。`09.LINEやりとり資料/` は存在しなければ pc_cli が自動作成（案件フォルダ自体の自動作成はしない）。

### 実行例とサンプル出力

```bash
# 1) 未処理を取得
$ python -m app.cli pull-pending --limit 50
[{"doc_id":"abc123","type":"image","group_id":"Cxxx","timestamp":"2026-05-29T08:23:45+09:00","gcs_path":"gs://.../abc123.jpg"}]

# 2) バイナリを DL（Cowork が Read tool で読む）
$ python -m app.cli download abc123 --dest-dir "/mnt/c/.../pc_worker_tmp"
{"doc_id":"abc123","local_path_unix":"/mnt/c/.../abc123.jpg","local_path_windows":"C:\\...\\abc123.jpg"}

# 3) 案件フォルダ候補をスキャン → Cowork が案件名と fuzzy match
$ python -m app.cli list-case-folders --max-depth 3
[{"folder_name":"00.HESTA_..._様","parent_folder_name":"@@@決定案件","depth":2,"absolute_path_unix":"/mnt/c/.../@@@/@@@決定案件/00.HESTA_..._様","absolute_path_windows":"C:\\...","child_dir_count":18,"has_line_yaritori_folder":true,"last_modified":"2026-05-25T01:53:00+09:00"}]

# 4) Notion にタスク追加
$ python -m app.cli write-task --case "佐藤邸新築" --title "【LINE】2026-05-29 概算見積" --note "確信度 0.92"
{"page_id":"page-xxxxx","url":"https://www.notion.so/..."}

# 5) SharePoint 格納（案件フォルダ絶対パス指定）→ 完了化 → GCS 削除
$ python -m app.cli place-file --src "/mnt/c/.../abc123.pdf" --case-folder "/mnt/c/.../@@@決定案件/00.HESTA_..._様" --title "概算見積"
{"destination_unix":"/mnt/c/.../09.LINEやりとり資料/2026-05-29 概算見積.pdf","destination_windows":"C:\\...","onedrive_link":null,"created_subfolder":false}
$ python -m app.cli update-task --page-id page-xxxxx --priority 通常 --onedrive-link "C:\\..."
$ python -m app.cli mark-done abc123
{"doc_id":"abc123","status":"done","gcs_deleted":true}
```

### SharePoint フォルダ構造の探索

`SHAREPOINT_ROOT`（`/mnt/c/Users/.../@@@`）配下は階層・命名が不規則（ステータスフォルダ配下の案件 / 直接案件 / 年フォルダ経由の 3 階層 / 非案件フォルダ混在）。固定パスを組み立てず、`list-case-folders` で候補を取得して Cowork が案件名と突合し、得た **絶対パス**を `place-file --case-folder` / `write-log --case-folder` に渡す。

出力の読み方:
- `depth` / `parent_folder_name`: ステータスフォルダ配下か直接案件かの判別
- `child_dir_count`: 多ければ集合フォルダ（年フォルダやステータスフォルダ）の可能性。少なければ単一案件
- `has_line_yaritori_folder`: 既に `09.LINEやりとり資料/` があるか（初回かどうか）
- `last_modified`: 最近触られた = アクティブ案件のヒント

マッチする案件フォルダが無ければ Cowork は `mark-review <doc_id> --reason ...` で needs_review に振り分け、けいすけが手動でフォルダ作成 → 再仕分けする。

### Cowork からの呼び出し例（bash 経由）

Cowork Skill は同一セッションの全 pc_cli 呼び出しに共通 run_id を渡してログを束ねる:

```bash
RUN_ID="$(date +%Y%m%d-%H%M%S)-cowork"
cd ~/projects/LineTaskCollection/pc_worker && source .venv/bin/activate

# 未処理一覧を取得 → Cowork がマルチモーダル判定 → 各 item を順に処理
python -m app.cli pull-pending --limit 50 --log-run-id "$RUN_ID"
python -m app.cli download abc123 --log-run-id "$RUN_ID"          # Cowork が画像/PDF を Read
python -m app.cli list-cases --log-run-id "$RUN_ID"               # Notion 案件候補
python -m app.cli list-case-folders --log-run-id "$RUN_ID"        # SharePoint 案件フォルダ候補 → 絶対パスを得る
python -m app.cli write-task --case "佐藤邸新築" --title "..." --log-run-id "$RUN_ID"
python -m app.cli place-file --src "..." --case-folder "/mnt/c/.../@@@決定案件/00.HESTA_..._様" --title "概算見積" --log-run-id "$RUN_ID"
python -m app.cli mark-done abc123 --log-run-id "$RUN_ID"
```

確信度が低い／案件不明なものは Cowork がけいすけにその場で対話確認するか、`mark-review <doc_id> --reason ...` で needs_review に残す。

### テスト

```bash
pytest tests/ -v
```

外部 API（GCS / Firestore / Notion）はすべてモック。

### 実行環境（2026-05-29 A 方針 → 2026-05-30 実行経路 A 案で上書き）

> 2026-05-29 の A 方針（pc_cli は WSL でのみ実行、Cowork は監査のみ）は、2026-05-30 に Cowork の実行環境を実機確認した結果見直した。Cowork の bash は WSL ではなく**独立した Linux サンドボックス**で、マウントされるのは OneDrive の選択フォルダのみ・WSL リポジトリには到達不可だった。そこで pc_cli を**サンドボックスからも実行できる形**にし、仕分けをサンドボックス内で完結させる「実行経路 A 案」に確定。下記「Cowork サンドボックスからの実行」が現行手順。WSL 実行は引き続き開発・ローカルテスト用として有効。

開発の「正」は WSL リポジトリ `pc_worker/`。Cowork から実行するための複製を `scripts/sync-pc-cli-to-onedrive.sh` で OneDrive `51.LINE投稿ボット/pc_cli/` に同期する（`.env` / `secrets/` は同期せず、けいすけが置いた秘密値を保護）。

---

## Phase C': Cowork サンドボックスからの実行（2026-05-30 確定、実行経路 A 案）

Cowork の bash は **Ubuntu 22 / Python 3.10 の揮発サンドボックス**。マウントは OneDrive の選択フォルダのみ（`/sessions/<動的セッション名>/mnt/<フォルダ名>/`、セッション名は実行毎に変わる）。ネットワークは開いている（Firestore / Notion / pypi 到達可）。この前提で pc_cli を完動させる。

### ① ブートストラップ（git clone を正とする、起動毎）

**コードは OneDrive コピーから読まない**。OneDrive Files-On-Demand のプレースホルダは Cowork の Linux マウント越しに中身が途中で切れて読めず（2026-05-30 実測、`attrib +P` でも安定解消せず）、無人スケジュール実行では Windows Read で補正もできない。よって **コードは GitHub から git clone** してサンドボックスのネイティブ fs（`/outputs`）で実行する。OneDrive からは小サイズで完全に読める `.env` と SA 鍵だけを使う。

`scripts/sandbox-bootstrap.sh` が clone→`.env` コピー→`pip install`→AST 検証まで行う。Skill 先頭での呼び出しは `docs/cowork-skill-reference.md` §6-1 を参照。要旨:

```bash
ONEDRIVE=$(ls -d /sessions/*/mnt/51.LINE投稿ボット/pc_cli | head -1)
export GITHUB_PAT=$(grep -E '^GITHUB_PAT=' "$ONEDRIVE/.env" | head -1 | cut -d= -f2- | tr -d '\r')
export REPO_REF=main
curl -fsSL -H "Authorization: token $GITHUB_PAT" \
  "https://raw.githubusercontent.com/k-probox-design/LineTaskCollection/$REPO_REF/scripts/sandbox-bootstrap.sh" -o /tmp/b.sh
bash /tmp/b.sh
cd /tmp/linetask/pc_worker && export PYTHONPATH="$PWD"
```

clone 先は**ネイティブ fs（既定 `/tmp/linetask`）必須**。OneDrive マウントや `/outputs` 直下では git の内部操作が失敗する（2026-05-30 実測）。依存はバイナリ wheel を含む `google-cloud-*` があるため vendoring せず **毎回 pip**（実測 約6秒、2026-05-30）。`/tmp` から動かしても `mounts.py` の glob フォールバックで `@@@`/winpath は解決される。

### ② 認証（GCP サービスアカウント鍵）

サンドボックスには ADC が無いため **SA 鍵ファイル**で認証する。`.env` の `GOOGLE_APPLICATION_CREDENTIALS` に鍵 JSON のパス（Windows 形式可）を書くと、pc_cli が実行時に実マウントへ解決して `google-cloud` ライブラリに渡す。鍵 JSON は `51.LINE投稿ボット/secrets/`（同期・コミット対象外）に置く。鍵の作成・IAM 付与はけいすけ手作業（SA 名 `linetask-puller`、`roles/datastore.user` ＋バケットに `roles/storage.objectAdmin`）。

### ③ 動的マウントパスの実行時解決（最重要）

`.env` のパス系（`SHAREPOINT_ROOT` / `TMP_DOWNLOAD_DIR` / `LOG_OUTPUT_DIR` / `GOOGLE_APPLICATION_CREDENTIALS`）は**静的な Windows 絶対パス**で書く。pc_cli が実行時に実マウント先へ解決するため、Skill 側でセッション名を注入する必要はない（動的解決の責務は pc_cli 側）。

解決の鍵が `MOUNT_MAP`: Cowork にマウントしている Windows フォルダの絶対パスを `;` 区切りで列挙すると、pc_cli が以下の順で実マウント unix パスを特定する:

1. pc_cli 自身の位置（`/sessions/<現セッション>/mnt/...` 配下）から現セッションの mnt ベースを割り出し `<base>/<フォルダ名>` を確認
2. WSL の `/mnt/<drive>/...`
3. `/sessions/*/mnt/<フォルダ名>` の glob

特定した (unix 接頭辞 ↔ windows 接頭辞) の写像で、`destination_windows` 等の出力を正しい `C:\...` 形へ戻す（winpath 一般化）。詳細仕様は `docs/cowork-skill-reference.md`「マウント解決と winpath 一般化」。

### ④ .env の用意（けいすけ手作業）

`pc_cli/.env.sandbox.example`（既知値記入済み）を OneDrive `pc_cli/.env` にコピーし、けいすけが下記 3 点を行えば動く（`NOTION_DATABASE_ID_DESIGN_TASK` / `GCS_BUCKET` / `FIRESTORE_PROJECT` / `NOTION_DATA_SOURCE_ID` / `MOUNT_MAP` / パス系は記入済み）:

1. `NOTION_API_KEY` を記入
2. `secrets/linetask-puller.json` に GCP SA 鍵を配置（`GOOGLE_APPLICATION_CREDENTIALS` は記入済み）
3. **`GITHUB_PAT` を記入** — GitHub fine-grained PAT（対象 repo = `k-probox-design/LineTaskCollection` のみ、権限 = Contents:Read のみ、有効期限は任意）。サンドボックスが git clone でコードを取得するために使う。作成は GitHub → Settings → Developer settings → Fine-grained tokens。

`.env` は OneDrive 配下にあり小サイズなのでマウント越しに完全に読める（コード本体と違いハイドレート問題は起きない）。

---

## Phase C': 実行ログの OneDrive 複製設定

各 pc_cli 実行のログ（どの item をどう処理したか・エラー）を Cowork が OneDrive 経由で監査できるよう、stderr ログを OneDrive 配下にも複製出力する。

- `.env` の `LOG_OUTPUT_DIR` に出力先を指定すると、`$LOG_OUTPUT_DIR/YYYY-MM-DD/<run_id>.jsonl` に JSON Lines 形式で複製される（コンソール=stderr 出力は維持、ファイルは追加）
- `<run_id>` はサブコマンド呼び出しごとに発行（`YYYYMMDD-HHMMSS-<6桁>`）。`--log-run-id` で Cowork 側から共通 ID を渡せる
- 日付フォルダはランタイムで自動作成

### LOG_OUTPUT_DIR の値の決め方

Cowork が読める OneDrive 同期フォルダ内のパスを `/mnt/c/...` 形式で指定する。例:

```
LOG_OUTPUT_DIR=/mnt/c/Users/knaka/OneDrive - 株式会社ビギン/@@設計/51.LINE投稿ボット/pc_worker_logs
```

### フォールバック挙動

ログ複製は「あれば便利」な監査補助であり、本処理を止めない設計:

- `LOG_OUTPUT_DIR` 未設定 → ファイル出力ハンドラを登録せず、コンソールのみ。WARN を 1 行出して継続
- パスが存在しない / 書き込めない → 同様にスキップして WARN、本処理は継続

---

## Phase C: GCS ライフサイクルルール設定（けいすけ手作業 / Cloud Shell）

仕分け取り残しの保険として、90 日経過の `pending/` オブジェクトを自動削除する。

```bash
cat > /tmp/lifecycle.json <<'EOF'
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 90, "matchesPrefix": ["pending/"]}
      }
    ]
  }
}
EOF
gcloud storage buckets update gs://probox-linetask-prod-intake --lifecycle-file=/tmp/lifecycle.json
rm /tmp/lifecycle.json
```

---

## トラブルシュート

### ボットを招待した直後にグループから退出する

「グループ・複数人トークへの参加を許可する」が OFF になっている。公式アカウントマネージャー → アカウント設定 → トークへの参加 で ON にする。

### Webhook が 401 / 403 になる

- チャネルアクセストークンが `.env` に正しく設定されているか確認
- LINE Developers の Webhook URL が `https://<ngrok-url>/line/webhook` になっているか確認（末尾の `/line/webhook` を忘れやすい）

### ngrok を再起動したら Webhook が届かなくなった

ngrok の無料プランは再起動のたびに URL が変わる。LINE Developers の Webhook URL を新しい ngrok URL に更新すること。

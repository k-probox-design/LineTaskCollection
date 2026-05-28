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

## Phase C: pc_worker の起動（Cowork 実行）

### セットアップ

```bash
cd pc_worker
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
# ANTHROPIC_API_KEY / NOTION_API_KEY / NOTION_DATABASE_ID_DESIGN_TASK / SHAREPOINT_ROOT を入力
# GCP は ADC（gcloud auth application-default login）で解決
```

### 実行

```bash
python -m app.main
```

1 回実行して Firestore `status=pending` を全件さばいて終了する（常駐しない）。確信度 0.8 以上は SharePoint 格納 + Notion 更新 + GCS 削除、未満は「仕分け待ち」のまま残す。

### テスト

```bash
pytest tests/ -v
```

外部 API（GCS / Firestore / Notion / Anthropic）はすべてモック。

### Cowork 許可フォルダへの配置

リポジトリの `pc_worker/` 配下を `C:\Users\knaka\OneDrive - 株式会社ビギン\@@設計\51.LINE投稿ボット\pc_worker\` にコピーして運用する（鍵・スクリプトは Cowork 許可フォルダ内に置く）。

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

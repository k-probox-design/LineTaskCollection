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

## トラブルシュート

### ボットを招待した直後にグループから退出する

「グループ・複数人トークへの参加を許可する」が OFF になっている。公式アカウントマネージャー → アカウント設定 → トークへの参加 で ON にする。

### Webhook が 401 / 403 になる

- チャネルアクセストークンが `.env` に正しく設定されているか確認
- LINE Developers の Webhook URL が `https://<ngrok-url>/line/webhook` になっているか確認（末尾の `/line/webhook` を忘れやすい）

### ngrok を再起動したら Webhook が届かなくなった

ngrok の無料プランは再起動のたびに URL が変わる。LINE Developers の Webhook URL を新しい ngrok URL に更新すること。

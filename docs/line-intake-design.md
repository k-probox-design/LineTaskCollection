# LINE資料 自動取り込み — 実装ハンドオフ仕様

> 対象：Claude Code（実装）／ Cowork（PC上での実行・検索）
> このドキュメントが最新の確定版。以前の `line-intake-design.md` の内容を上書きする。

---

## 0. 目的

LINEグループに届く案件資料（見積書・図面・写真など）を、人手をかけずに
**受信 → 仕分け → SharePoint格納 → Notion記録** まで自動処理する。
あわせて Firestore に検索可能な受信アーカイブを残し、Cowork から自然言語で過去を遡れるようにする。

---

## 1. 全体アーキテクチャ（確定）

```
[LINEグループ] 依頼主が資料を投稿
   │ Webhook（メッセージID付き）
   ▼
[Cloud Run] 受信専用・常時稼働（薄い／新規GCPプロジェクト＝別契約）
   ├ 署名検証
   ├ コンテンツを即ダウンロード（期限切れ対策）
   ├ 実体     → GCS（pending/ に保管）
   └ メタ情報 → Firestore に記録（status=pending、受信ログ兼アーカイブ）
        │
        │ PC起動時に pending を取りに行く（pull）
        ▼
[PC（Windows）＝ Cowork が実行]
   ├ GCSの pending を取得（＋Firestoreのメタ）
   ├ Claude で仕分け判断（中身＋groupId＋時刻、確信度つき）
   ├ 確信あり → SharePoint同期フォルダへ格納（OneDriveが自動アップ）＋ Notion記録
   ├ 迷い    → 「要確認」へ ＋ Notionに確認タスク
   └ 済みに更新し、GCSの一時ファイルを削除
        ▲
        │ 「先月の山田案件の資料は？」等
[Cowork 検索] Firestoreアーカイブを引く（PC内のヘルパー/Skill経由）
```

---

## 2. 確定した構成要素

| 役割 | 採用 | 補足 |
|------|------|------|
| 受信元 | LINE公式アカウント（Messaging API） | コミュニケーションプラン＝月額¥0。受信とReply APIは課金対象外 |
| 受信サーバー | FastAPI on Cloud Run（新規GCPプロジェクト） | 本体ProboxDesignとは別契約・別請求 |
| 一時バッファ | GCS（ファイル実体）＋ Firestore（メタ・ログ） | PCが引き取ったらGCSは削除 |
| 仕分け | Claudeが中身を判断（PC側） | groupIdと時刻を補助シグナルに |
| 最終格納先 | SharePoint（OneDrive同期フォルダ経由） | Azure登録・Graph API 不要 |
| タスク・記録 | Notion | Claudeから直接連携可能 |
| 検索アーカイブ | Firestore ＋ Cowork | Coworkが自然言語の窓口 |
| 実行環境 | Cowork on Windows | 2026/2/10にWindows対応済み（macOSとパリティ） |

---

## 3. コンポーネント別の仕様

### 3-1. LINE公式アカウント（手作業のコンソール設定）

1. 「LINE for Business」で公式アカウントを作成（無料）
2. 公式アカウントマネージャー「設定 → Messaging API → 利用する」を実行（LINE Developers にチャネルが生成される）
3. LINE Developers で **チャネルアクセストークン（長期）** を発行、**チャネルシークレット** を控える
4. 応答設定：「応答メッセージ OFF」「Webhook ON」
5. **【最重要】** アカウント設定 → トークへの参加 → **「グループ・複数人トークへの参加を許可する」を ON**（これを忘れるとボットがグループからすぐ退出する）
6. Webhook URL に Cloud Run のエンドポイント（`/line/webhook`、https）を登録
7. 個人LINEで公式アカウントを友だち追加 → 案件グループに招待
8. 招待時の `[JOIN]` イベントで **groupId** を取得し、案件と紐付けて登録

### 3-2. 受信サーバー（Cloud Run）— Claude Code が実装

- FastAPI。エンドポイント `POST /line/webhook`
- `X-Line-Signature` を HMAC-SHA256 で検証
- メッセージタイプが image / file / video / audio のとき、`https://api-data.line.me/v2/bot/message/{messageId}/content` から**即ダウンロード**（コンテンツには取得期限があるため遅延させない）
- 実体を GCS `pending/` に保存、メタ情報を Firestore に書き込み（status=pending）
- `join` イベントは groupId をログ＆Firestoreに記録（案件紐付けの起点）
- Webhookには**素早く200を返す**。大きいファイルはバックグラウンドDLに分離する（将来のハードニング）
- 環境変数：`LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` / GCS・Firestoreの認証
- **このサーバーにはMicrosoft（SharePoint）やNotion、Claudeの鍵を置かない**。持たせるのはLINEトークンとGCP内権限だけ
- ※ ベースとして別途共有済みの `line_webhook.py`（保存のみ版）を、GCS＋Firestore対応へ拡張する

### 3-3. 一時バッファ（GCS ＋ Firestore）

- GCS：`pending/` に未処理、処理後は削除（または `done/` へ短期移動）。Standardクラス（早期削除料金なし）
- Firestore：受信メタ＝そのまま「遡って検索できるアーカイブ」になる

### 3-4. PC側処理（Cowork が実行）— Claude Code が実装

PC起動時に動かすバッチ／ジョブとして実装し、Cowork から起動・監督する。

1. GCS `pending/` ＋ Firestore の未処理を取得
2. Claudeで仕分け判断（3-5）
3. 確信あり → 該当案件の SharePoint同期フォルダへ保存（OneDriveが自動でSharePointへ）＋ Notion記録
4. 迷い → 「要確認」フォルダへ ＋ Notionに確認タスク（Claudeの候補上位とリンクを併記）
5. Firestoreを status=done に更新し、GCSの一時ファイルを削除

### 3-5. 仕分けロジック（Claudeの判断）

- 入力：ファイル本体（画像・PDFはそのまま読める）＋ 候補となる**既存案件の一覧**（Notionの案件DB）＋ groupId ＋ 受信時刻
- 出力：`{ 案件名, 確信度, 判断理由 }`
- しきい値（初期値 **0.8**）で分岐
  - 0.8以上 → 自動格納＋記録
  - 0.8未満 → 要確認（人間に確認を挟む）※**この方針で確定**
- 注意：見積書・図面など文字のある資料は高精度。屋根写真など文字のない画像は精度が落ちるため、groupId と時刻の補助が効く

### 3-6. 最終格納先（SharePoint via OneDrive）

- PCのOneDrive同期フォルダ（SharePointのショートカット）に書き込むだけ。OneDriveクライアントが自動でSharePointへアップ
- **Azureのアプリ登録もMicrosoft Graph APIも不要**。Microsoft認証情報をサーバー側に持たせない

### 3-7. 検索（Firestore ＋ Cowork）

- Cowork（Windows、Hyper-Vの隔離VM内で動作）から自然言語で問い合わせ → Firestoreを引いて結果を返す
- 確実に動かすため、**「アーカイブの調べ方」を小さなヘルパー（スクリプト or Agent Skill）として用意**し、Cowork に許可したフォルダ内に置く
- **Firestoreの鍵・ヘルパーは、Coworkに権限を与えたフォルダの中**に配置（VM隔離のため、ここに無いとアクセスできない）

---

## 4. データ設計

### Firestore（コレクション例）

```
intake_groups/{groupId}
    caseName            案件名
    sharepointFolder    格納先（案件フォルダの識別子／パス）
    registeredAt

intake_messages/{messageId}      ← 受信ログ兼アーカイブ
    groupId
    type                image / file / video / text ...
    fileName            （fileメッセージのとき）
    text                （テキストメッセージのとき）
    receivedAt
    status              pending / done / needs_review
    classifiedCase      仕分け結果（案件名）
    confidence          確信度
    gcsPath / finalPath
```

### GCS

```
gs://<bucket>/pending/<timestamp>_<messageId>.<ext>
（処理後に削除）
```

### Notion タスク／記録（フィールド案）

| フィールド | 例 |
|-----------|-----|
| タイトル | 資料受領: 見積書_山田様.pdf |
| 案件 | （案件DBへのリレーション） |
| 受領日時 | 2026-05-26 14:30 |
| 確信度 | 0.92 |
| ステータス | 確認不要 / 要確認 |
| ファイル | SharePointリンク |

---

## 5. 重要な制約・落とし穴

- **LINEに過去ログ取得APIは無い**：Webhookで受け取れるのはリアルタイムのみ。ボット招待前に届いた資料は自動取り込み不可（LINEアプリから手動が唯一の手段）
- **コンテンツに取得期限**：受信したら即ダウンロードすること
- **受信は常時起動が前提**：受け取り口（Cloud Run）が落ちている間は取りこぼす。だから受信だけクラウドに常駐させ、重い処理はPC側に置く
- **グループ参加設定**：3-1の手順5を忘れるとボットが退出する
- **Webhookは即200**：処理は非同期で
- **groupIdが仕分けの起点**：JOIN時に必ず案件と紐付ける
- **Cowork（Windows）の置き場所**：鍵・ヘルパーはCowork許可フォルダ内に。Intel/AMD x64・Windows 10(1909+)/11・有料プランが条件

---

## 6. コスト（この規模なら実質無料）

| 項目 | 月額の目安 |
|------|-----------|
| LINE公式アカウント | ¥0（コミュニケーションプラン） |
| Cloud Run | ほぼ¥0（待機中ゼロ課金） |
| GCS | ほぼ¥0（一時保管・Standard・無料枠内） |
| Firestore | ほぼ¥0（小規模） |
| Cowork | 既存の有料Claudeプラン内 |

---

## 7. 構築フェーズ（推奨順）

- **Phase A**：LINE公式アカウント作成＋受信疎通（ngrok等で `[JOIN]`/ファイル受信を確認）
- **Phase B**：Cloud Run受信サーバー（GCS＋Firestore書き込み）を常時起動に
- **Phase C**：PC側処理（Cowork実行）— pull → Claude仕分け → SharePoint格納 → Notion記録
- **Phase D**：Cowork用アーカイブ検索ヘルパー（Skill）を整備

---

## 8. 未決事項（実装時に確定する）

- [ ] Notionの案件DB／タスクDBの構造を確認し、記録先と仕分け候補リストを確定
- [ ] タスク登録の方針：**推奨＝「確信ありは静かに記録（案件ページに1行）／要確認だけ実タスク」**（未確定。全受領を一覧化したい場合は変更）
- [ ] 案件フォルダ内の「受領資料の定位置」サブフォルダ名
- [ ] 仕分けの確信度しきい値（初期0.8で運用しながら調整）
- [ ] 受信ログにテキストメッセージも残すか（会話まるごとアーカイブ）／ファイルだけにするか
- [ ] 新規GCPプロジェクトの作成と、LINEトークンの保管先（Cloud Run側のみ）

---

## 9. 決定ログ（検討して見送った案）

| 案 | 判断 | 理由 |
|----|------|------|
| 全部ローカルPCで完結（クラウド無し） | 見送り | PC停止中に受信を取りこぼす（コンテンツ期限あり）。受信だけは常駐が必要 |
| VPSを1台借りる | 見送り | コストはほぼ互角だが、Cloud Run + GCS のほうが固定費ゼロ・既存スタックと親和。VPSはディスク完結が利点だったが、データはどのみち一時的でPCが即引き取るため決め手にならず |
| OneDriveを受信バッファに直書き | 見送り | サーバーからの書き込みにGraph API＝Azure登録が必要になり、Microsoft認証情報をクラウドに置くことになる。最終格納（PCの同期フォルダ経由）専用に留める |
| Firestoreを使わない（GCSのpending/doneのみ） | 見送り | 状態管理だけなら可能だが、過去ログの横断検索が苦しい。検索アーカイブを活かすため採用 |
| Cloud Runにファイルを保持 | 不可 | ステートレスでゼロスケールするため永続ディスクを持てない。GCSが必須 |
```

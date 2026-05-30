# CLAUDE.md

このファイルは Claude Code が LineTaskCollection リポジトリで作業するときに最優先で参照する「神様ファイル」。
プロジェクト全体に適用されるルール・前提・約束ごとをここに集約する。

---

## プロジェクト概要

- 名称: LineTaskCollection
- 内容: LINE グループに届く案件資料(見積書・図面・写真など)を自動で仕分け・格納するアプリ
- 詳細: `docs/line-intake-design.md`(本リポジトリの実装仕様、神様ファイルの次に重要)
- リポジトリ: https://github.com/k-probox-design/LineTaskCollection (private、作成済)

### 全体アーキテクチャ(要約)

```
[LINEグループ] 依頼主が資料を投稿
   │ Webhook(メッセージID付き)
   ▼
[Cloud Run] 受信専用・常時稼働(新規GCPプロジェクト)
   ├ 署名検証
   ├ コンテンツを即ダウンロード(期限切れ対策)
   ├ 実体     → GCS(pending/ に保管)
   └ メタ情報 → Firestore(status=pending、受信ログ兼アーカイブ)
        │
        │ PC起動時に pending を pull
        ▼
[PC(Windows)= Cowork が実行]
   ├ Claude で仕分け判断(確信度つき)
   ├ 確信あり → SharePoint同期フォルダ + Notion記録
   └ 迷い    → 要確認フォルダ + Notion確認タスク
        ▲
        │ 「先月の山田案件の資料は?」等
[Cowork 検索] Firestoreアーカイブを引く
```

役割分担(spec §1〜3):

- **受信(クラウド常駐)**: Cloud Run = FastAPI、LINE Webhook 受信 + GCS 一時保管 + Firestore メタ記録
- **仕分け・格納(PC 側)**: Cowork on Windows、Claude 判断 + SharePoint(OneDrive 同期経由)+ Notion
- **検索**: Cowork が Firestore アーカイブを自然言語で引く

---

## 環境

### 3 つの実行拠点

1. **Cloud Run(GCP、新規プロジェクト `probox-linetask-prod`)** — 受信専用、常時稼働。LINE トークンと GCP 内権限のみ持つ
2. **WSL2(けいすけ PC)** — Claude Code が開発作業をする場所。`~/projects/LineTaskCollection/`
3. **Cowork 隔離 VM(Windows、Hyper-V)** — PC 側処理(仕分け・SharePoint 格納・Notion 記録・Firestore 検索)を実行する場所。鍵とヘルパースクリプトは Cowork 許可フォルダ内に置く

### 開発環境(WSL2 側)

- OS: WSL2 / Ubuntu 24.04 LTS (Windows 11 ホスト)
- 作業ディレクトリ: `~/projects/LineTaskCollection/`
- シェル: bash
- Git ユーザー: k-probox-design

### Claude Code 実行規約

ProboxDesign で確立した規約を踏襲する:

- **WSL bash 実行規約**:`bash -ic`(interactive)ではなく `bash -lc`(login shell)または `bash -c`(non-interactive)を使う
- **クォート規約**:bash 引数は **シングルクォート優先**、ダブル必要時はバックスラッシュエスケープ
- **頻発スクリプト化**:同じ bash コマンドを繰り返す場合は `scripts/` 配下にスクリプト化を推奨
- **エラーメッセージの読み方**:CP932 文字化け(`�` の連続)が出たら Windows PowerShell ロケール由来

### dev サーバ起動(Cloud Run 部分のローカル動作確認)

```bash
# 1. .env 配置(template から複製)
cp ~/projects/LineTaskCollection/server/.env.example ~/projects/LineTaskCollection/server/.env

# 2. FastAPI ローカル起動
cd ~/projects/LineTaskCollection/server && uvicorn app.main:app --reload

# 3. LINE Webhook を local に向けるとき(動作確認時のみ)
ngrok http 8000   # 生成された https URL を LINE Developers に登録
```

ローカル動作確認では Firestore Emulator / GCS Emulator を使うか、開発用の別プロジェクトに書く判断を Phase B 着手時に確定。

---

## ディレクトリ構成(初期想定)

```
LineTaskCollection/
├── CLAUDE.md                ← このファイル(最優先ルール)
├── README.md                プロジェクト概要(リポジトリ訪問者向け)
├── .gitignore
├── docs/
│   ├── line-intake-design.md   実装仕様(神様ファイルの次に重要)
│   ├── setup-log.md            環境構築ログ(Phase A 着手時に作成)
│   ├── operations.md           運用手順(LINE 公式アカウント設定 / Cloud Run デプロイ / PC 側起動)
│   └── decision-log.md         決定ログ(設計判断の履歴)
├── server/                  Cloud Run 受信サーバー(Python / FastAPI)
│   ├── app/
│   │   ├── main.py
│   │   ├── line_webhook.py     ベース: 別途共有済みファイルを GCS+Firestore 対応に拡張
│   │   ├── gcs.py              (Phase B)
│   │   └── firestore.py        (Phase B)
│   ├── tests/
│   ├── Dockerfile              (Phase B)
│   ├── pyproject.toml
│   └── .env.example
├── pc_worker/               PC 側処理(Cowork 実行、Python、Phase C)
│   ├── pull_pending.py
│   ├── classify.py
│   ├── sharepoint_writer.py
│   ├── notion_writer.py
│   └── tests/
├── cowork_helpers/          Cowork が呼ぶアーカイブ検索ヘルパー(Skill or スクリプト、Phase D)
│   └── search_archive.py
├── scripts/                 頻発コマンドのスクリプト化置き場
└── .github/workflows/       CI(将来)
```

`pc_worker/` と `cowork_helpers/` は **Cowork 許可フォルダ内に配置**(Cowork は VM 隔離のため、許可フォルダ外のファイルを読めない)。具体的なパスは Phase C 着手時に確定。

---

## コミュニケーション

- 言語: 日本語で回答する
- 口調: 丁寧すぎず簡潔に。技術用語はそのまま使ってよい
- ファイル/コード参照: `[filename.py:42](server/app/filename.py#L42)` 形式のクリッカブルリンクで示す

## 開発フロー(けいすけ判断役 + Cowork 相談役 + Claude Code 自動進行)

ProboxDesign と同じ 3 者運用。Claude Code は基本的に autonomous 自動進行する。

### 役割分担

- **けいすけ(判断役)**: 業務判断 / スコープ判断 / 設計方針承認 / セッション開始・終了サイン / main マージ承認 / **受け渡しフォルダ間のファイル運搬(手動)**
- **Cowork(相談役、Claude Opus、Windows デスクトップ)**: けいすけと相談して設計方針を決定、md ファイル(kickoff)にまとめて Claude Code 指示役に依頼。重大事故対応 / 判断点での助言 / 教訓集メンテも担当。**実装には踏み込まない**
- **Claude Code(指示役 + コーディング役 + レビュー役、Claude Sonnet、WSL2、autonomous default)**:
  - **指示役(司令役主スレ)**: 進行管理 / Agent 指示分配 / E2E spec / 最終 commit / push 権限 / Cowork 完走報告
  - **コーディング役(Agent)**: 実装 / 単体テスト / dev サーバ運用 / ドキュメント更新
  - **レビュー役(独立 context Agent)**: commit 前独立検証 / 致命的禁止事項チェック

### 進行フロー

1. けいすけ ↔ Cowork で相談 → 設計方針確定
2. Cowork が md ファイル(kickoff)にまとめ → 受け渡しフォルダ経由で Claude Code 指示役に渡す
3. Claude Code 指示役 → コーディング役 dispatch → レビュー役 独立検証 → commit / push(autonomous)
4. Claude Code が md ファイル(完走報告)にまとめて Cowork に報告(受け渡しフォルダ経由)
5. Cowork がけいすけに「<filename>.md 読んで」とファイル名通知のみ
6. Cowork ↔ けいすけで完走報告 audit → 次フェーズ着手判断 → 1. に戻る

### 受け渡しフォルダ運用(2026-05-27 確定)

非対称設計。各エージェントは自分のネイティブなファイルシステムに書き込み、けいすけさんが手動で運搬する。

| フォルダ | 役割 | 書く人 | 読む人 |
|---------|------|--------|--------|
| `C:\Users\knaka\OneDrive - 株式会社ビギン\@@設計\51.LINE投稿ボット\ClaudeCodeとの受け渡し\` | kickoff(指示) | Cowork | Claude Code(けいすけが WSL へ運搬後) |
| `\\wsl.localhost\Ubuntu-24.04\home\knaka\projects\LineTaskCollection\Coworkとの受け渡し\` | report(完走報告) | Claude Code | Cowork(けいすけが OneDrive へ運搬後) |

- **命名規約**: `YYYY-MM-DD_<phase>_<kickoff or report>_<topic>.md`
  - 例: `2026-05-27_phaseA_kickoff_line-receive-smoke.md` / `2026-05-28_phaseA_report.md`
- **サブフォルダ**: フラット運用、50 個超で `_archive/` 検討
- **Cowork → Claude Code 応答はチャット返答禁止、すべてファイル化必須**(例外:けいすけ宛の短文メタ応答のみ)

### Cowork 起動の判断基準

Cowork は **相談役として常時稼働 default**。以下は Claude Code 単独で完結:

- 既存判断 / 規約に沿った実装
- バグ修正 / テスト追加 / ドキュメント整理
- 動作確認(pytest / 手動 curl 等)
- autonomous default の機能実装(Cowork kickoff 確定後)

## 作業ルール

- 既存ファイルの編集を優先。新規ファイルは必要なときだけ作る
- ドキュメント(`*.md`)を勝手に増やさない。ユーザーが明示的に頼んだときだけ作成
- コメントはデフォルトで書かない。「なぜそうしたか」が非自明なときだけ短く書く
- 絵文字は明示的に頼まれたときだけ使う

## Git / コミット

- コミットはユーザーが明示的に頼んだときだけ作成する(Phase 完走報告の前に commit / push が標準)
- `git add .` / `git add -A` ではなくファイル名指定で `git add` する
- `--no-verify`、`--force`、`reset --hard` などの破壊的操作はユーザー承認を必須とする
- コミットメッセージは「なぜ変更したか」を 1〜2 文で

### ブランチ運用(必須)

**日々の作業は日付ベースのブランチで行う。`main` には直接コミットしない。**

```bash
git checkout main
git pull origin main
git checkout -b work/YYYY-MM-DD
```

`main` への取り込みは **けいすけが明示的に依頼したとき** にのみ実施する。

**例外**: 最初の commit(CLAUDE.md / README.md / docs / ディレクトリ雛形 / .gitignore の配置)は `main` に直接 push 可。Phase A の実装着手時から `work/YYYY-MM-DD` ブランチ運用を開始する。

## 危険な操作の確認

以下はけいすけに確認してから実行する:

- ファイル/ブランチの削除、`rm -rf`
- 強制プッシュ、`reset --hard`、`amend` 済みコミットへの再 amend
- 共有リソース(GitHub PR/Issue、Notion DB、Firestore 本番)への書き込み
- 依存パッケージの削除・ダウングレード
- **LINE 公式アカウントの設定変更**(応答メッセージ ON/OFF、Webhook URL、グループ参加設定)
- **Cloud Run デプロイ**(本番反映)
- **Secret Manager の書き換え**

---

## 採用する技術・サービス(確定済み)

### 受信サーバー(Cloud Run)

- Python 3.11+
- FastAPI
- google-cloud-storage / google-cloud-firestore
- line-bot-sdk-python(署名検証 + コンテンツ取得)
- Pydantic v2(型定義・検証)

### PC 側処理(Cowork 実行)

- Python 3.11+
- Anthropic SDK(Claude による仕分け判断)
- google-cloud-storage / google-cloud-firestore(pull)
- notion-client(Notion 記録)
- SharePoint は OneDrive 同期フォルダへのファイル書き込みのみ(Graph API 不使用)

### Google Cloud(新規プロジェクト `probox-linetask-prod`、ProboxDesign とは別請求扱い)

- 受信サーバー実行: Cloud Run
- 一時バッファ: Cloud Storage(`pending/` に保管、処理後削除)
- メタ・アーカイブ: Firestore
- シークレット: Secret Manager(LINE トークン、Firestore Admin SDK の鍵)

### Microsoft 365

- SharePoint(OneDrive 同期経由で書き込み、認証情報をサーバーに置かない)

### Notion

- 案件 DB / タスク DB(構造は **Phase C 着手前に別途相談して確定**。Phase A / B では一切触らない)
- 認証: Notion インテグレーショントークン(PC 側 .env に保管)

### 開発環境

- WSL2 / Ubuntu 24.04(Claude Code 作業場所)
- Cowork on Windows(PC 側処理の実行・検索の窓口)

---

## シークレット管理(★ 最重要)

> spec §3-2 の原則:**受信サーバー(Cloud Run)には Microsoft / Notion / Claude の鍵を置かない**。持たせるのは LINE トークンと GCP 内権限だけ。

### Cloud Run 側(受信サーバー)

- **GCP Secret Manager で管理**
- 必要なシークレット(命名規約: ケバブケース、Cloud Run 環境変数注入時に SNAKE_CASE へリネーム):
  - `line-channel-secret` → `LINE_CHANNEL_SECRET`(署名検証用)
  - `line-channel-access-token` → `LINE_CHANNEL_ACCESS_TOKEN`(コンテンツ取得用、長期トークン)
- バージョニング: **`:latest` 参照**(ローテーション楽。バージョン固定は事故時のロールバックでだけ使う)
- 権限: **Secret 単位で Cloud Run サービスアカウントに `roles/secretmanager.secretAccessor` を付与**(プロジェクト全体には付与しない)
- Firestore / GCS は Cloud Run サービスアカウントの IAM 権限で解決(鍵ファイル不要)
- **.env は Cloud Run には置かない**(Secret Manager から実行時に注入)
- ローテーション: 定期更新はしない。漏洩疑い時は「LINE Developers でトークン再発行 → Secret Manager に新バージョン追加 → Cloud Run 再デプロイ不要(`:latest` 参照なので次回起動から反映)」を `docs/operations.md` に明記

### PC 側(Cowork 実行)

- **`.env`(Cowork 許可フォルダ内、絶対に Git にコミットしない)** で管理
- 必要なシークレット:
  - `ANTHROPIC_API_KEY`(仕分け判断用)
  - `NOTION_API_KEY` / `NOTION_DATABASE_ID_案件` / `NOTION_DATABASE_ID_タスク`
  - `FIRESTORE_SERVICE_ACCOUNT_JSON_PATH`(Firestore 読み書き用、または Application Default Credentials)
- `.env.example` をリポジトリにコミット(値は空、変数名と説明のみ)
- `.gitignore` に `.env` / `*.json`(service account)を必ず追加

### 共通ルール

- **鍵を生のままチャットや受け渡しフォルダに貼らない**。漏れた疑いがあるトークンは即ローテーション
- Cowork が VM 隔離のため、PC 側鍵は **必ず Cowork 許可フォルダ内** に置く(VM 外のフォルダは Cowork から見えない)

---

## LINE 固有の落とし穴(★ 最重要、spec §5 集約)

これらは「知らずに踏むと取りこぼし or 動作停止」する罠。実装・運用の両方で常に意識する。

1. **LINE に過去ログ取得 API は無い** — Webhook で受け取れるのはリアルタイムのみ。ボット招待前に届いた資料は自動取り込み不可。「過去資料は手動で LINE アプリから保存してね」と運用書類に明記
2. **コンテンツに取得期限がある** — 受信したら即ダウンロードする。Cloud Run で受け取った直後に `https://api-data.line.me/v2/bot/message/{messageId}/content` を叩いて GCS に保存。遅延させない
3. **受信は常時起動が前提** — Cloud Run が落ちている間は取りこぼす。受信だけクラウド常駐させ、重い処理(仕分け・格納)は PC 側で OK
4. **グループ参加設定 ON が絶対条件** — 公式アカウントマネージャー「アカウント設定 → トークへの参加 → グループ・複数人トークへの参加を許可する」を ON。OFF だと招待しても即退出する。`docs/operations.md` の LINE 設定手順に必ず書く
5. **Webhook には素早く 200 を返す** — LINE 側は数秒でタイムアウト判定。重い処理は背景タスクに分離する(将来のハードニング項目)
6. **groupId が仕分けの起点** — ボット招待時の `[JOIN]` イベントで groupId を取得し、案件と紐付けて `intake_groups` コレクションに登録。これを忘れると後段の仕分けが「迷い」連発になる
7. **Cowork(Windows)の動作要件** — Intel/AMD x64、Windows 10(1909+)/11、Cowork 有料プラン、Hyper-V 隔離 VM 内で動作。鍵・ヘルパーは Cowork 許可フォルダ内に置く

---

## 構築フェーズ

spec §7 を踏襲。各 Phase の完了基準は着手時に Cowork と確定する。

| Phase | 内容 | 状態 |
|-------|------|------|
| Phase A | LINE 公式アカウント作成 + 受信疎通(ngrok 等で `[JOIN]`/ファイル受信を確認) | **完走(2026-05-28)** |
| Phase B | Cloud Run 受信サーバー(GCS + Firestore 書き込み)を常時起動に | **完走(2026-05-28)** |
| Phase C | PC 側処理(Cowork 実行)— pull → Claude 仕分け → SharePoint 格納 → Notion 記録 | **Phase C' に転換、再構築中(2026-05-29)** |
| Phase D | Cowork 用アーカイブ検索ヘルパー(Skill)を整備 | 未着手 |

---

## データ設計(初期スキーマ、Phase B 着手時に確定)

### Firestore

```
intake_groups/{groupId}
    caseName            案件名
    sharepointFolder    格納先(案件フォルダの識別子 / パス)
    registeredAt

intake_messages/{messageId}      ← 受信ログ兼アーカイブ
    groupId
    type                image / file / video / text ...
    fileName            (file メッセージのとき)
    text                (text メッセージのとき)
    receivedAt
    status              pending / done / needs_review
    classifiedCase      仕分け結果(案件名)
    confidence          確信度
    gcsPath / finalPath
```

### GCS

```
gs://<bucket>/pending/<timestamp>_<messageId>.<ext>
(処理後に削除)
```

### Notion(フィールド案、Phase C 着手前に確定)

| フィールド | 例 |
|-----------|-----|
| タイトル | 資料受領: 見積書_山田様.pdf |
| 案件 | (案件 DB へのリレーション) |
| 受領日時 | 2026-05-26 14:30 |
| 確信度 | 0.92 |
| ステータス | 確認不要 / 要確認 |
| ファイル | SharePoint リンク |

---

## 仕分けロジック(Claude 判断、spec §3-5)

- 入力:ファイル本体 + 候補となる **既存案件の一覧**(Notion の案件 DB)+ groupId + 受信時刻
- 出力:`{ 案件名, 確信度, 判断理由 }`
- しきい値(初期値 **0.8**)で分岐
  - 0.8 以上 → 自動格納 + 記録
  - 0.8 未満 → 要確認(人間に確認を挟む)※ **この方針で確定**
- 注意:見積書・図面など文字のある資料は高精度。屋根写真など文字のない画像は精度が落ちるため、groupId と時刻の補助が効く

---

## コスト想定(この規模なら実質無料)

| 項目 | 月額の目安 |
|------|-----------|
| LINE 公式アカウント | ¥0(コミュニケーションプラン) |
| Cloud Run | ほぼ¥0(待機中ゼロ課金) |
| GCS | ほぼ¥0(一時保管・Standard・無料枠内) |
| Firestore | ほぼ¥0(小規模) |
| Cowork | 既存の有料 Claude プラン内 |

---

## 永続決定事項(Cowork 判断確定済み)

Cowork 判断で確定した「以後の実装で従うルール」をここに追記する。テーマ単位で見出しを切り、決定日と理由を併記する。

### アーキテクチャ(2026-05-27 確定、spec §1 + §9)

- 受信は **Cloud Run 常駐**、仕分け・格納は **PC 側(Cowork 実行)**、検索は **Cowork が Firestore を引く**
- 全部ローカル PC で完結する案は **見送り**(PC 停止中の取りこぼし懸念、コンテンツ期限あり)
- VPS 1 台借りる案は **見送り**(Cloud Run + GCS のほうが固定費ゼロ・既存スタックと親和)
- OneDrive を受信バッファに直書きする案は **見送り**(Graph API が必要、Microsoft 認証情報をクラウドに置かない方針に反する)
- Firestore を使わず GCS のみで状態管理する案は **見送り**(過去ログの横断検索が苦しい)
- Cloud Run にファイルを保持する案は **不可**(ステートレス・ゼロスケールのため永続ディスクを持てない、GCS 必須)

### シークレット境界(2026-05-27 確定)

- Cloud Run には LINE 鍵と GCP 内権限のみ
- SharePoint / Notion / Anthropic の鍵は PC 側のみ(Cowork 許可フォルダ内 `.env`)
- Secret 命名はケバブケース、Cloud Run 注入時に SNAKE_CASE へリネーム
- `:latest` 参照、Secret 単位で `secretAccessor` 付与、定期ローテーションなし

### GCP プロジェクト(2026-05-27 確定)

- プロジェクト名: `probox-linetask-prod`
- 請求先: けいすけ既存個人 Billing Account に紐付け(プロジェクト単位でコスト可視化)
- Phase A〜B は本番 1 プロジェクトのみで開始、dev 分離は Phase C 着手時に再判断
- プロジェクト作成・初期 IAM 設定はけいすけが手作業で実施

### 受け渡しフォルダ(2026-05-27 確定)

- Cowork → Claude Code: `C:\Users\knaka\OneDrive - 株式会社ビギン\@@設計\51.LINE投稿ボット\ClaudeCodeとの受け渡し\`
- Claude Code → Cowork: `\\wsl.localhost\Ubuntu-24.04\home\knaka\projects\LineTaskCollection\Coworkとの受け渡し\`
- ファイル運搬はけいすけが手動。各エージェントは自分のネイティブな FS にだけ書く
- 命名: `YYYY-MM-DD_<phase>_<kickoff or report>_<topic>.md`、フラット運用、50 個超で `_archive/` 検討

### GitHub リポジトリ(2026-05-27 確定)

- URL: `https://github.com/k-probox-design/LineTaskCollection`(private、作成済)
- 初期 commit は `main` に直 push 可。CLAUDE.md / README.md / `docs/line-intake-design.md` / ディレクトリ雛形 / `.gitignore` を含める
- Phase A の実装着手から `work/YYYY-MM-DD` ブランチ運用を開始
- `.gitignore` は Python 標準 + `.env` + `*.json`(service account) + `.idea/` `.vscode/` + `*.log`

### Phase B 実装方針(2026-05-28 確定)

1. **開発時の DB/Storage**: Firestore / GCS Emulator は使わず、**本番プロジェクト `probox-linetask-prod` に直書き**で開発する
   - 理由: Phase A〜B は本番 1 プロジェクト方針と整合、Emulator 学習コストが見合わない、Firestore/GCS とも小規模なら無料枠内
2. **テキストメッセージの扱い**: text タイプも **Firestore `intake_messages` に保存する**(ファイル本体は保存しない、メタ＋ text フィールドのみ)
   - 理由: 受信ログ＝検索アーカイブの方針と整合、テキストもアーカイブ価値が高い
3. **コンテンツダウンロード**: FastAPI **BackgroundTasks に分離**して Webhook には即 200 を返す
   - 理由: Cloud Run のタイムアウト＋ LINE Webhook の即 200 要件、画像複数や動画で詰まらないため
4. **line-bot-sdk-python**: **依存から外す**、自前検証＋httpx を継続
   - 理由: Phase A の判断(async との相性が悪い)が Phase B でも有効、未使用依存を残さない
5. **Cloud Run デプロイ権限分担**: **GCP プロジェクト作成・初回 IAM 設定・サービスアカウント作成・GCS バケット作成・Firestore DB 作成・Secret Manager への鍵登録はけいすけ手作業**、**`gcloud run deploy` 以降は Claude Code 実施**
   - 理由: 課金・権限を握る初期設定はけいすけが直接、デプロイ手順は autonomous

### Cloud Run 稼働方針(2026-05-28 確定)

- min-instances=1(常時 1 インスタンス常駐、cold start 排除)
- Startup CPU Boost ON(再起動時の起動高速化)
- 理由: LINE Webhook の取りこぼし防止。月額 ¥1,000〜2,000 程度の上振れは業務影響と引き換えに許容
- 月額が想定を超えた場合の見直しトリガー: GCP Budget Alert を別途設定(けいすけ手作業、未実施)

### Phase C 実装方針(2026-05-28 確定 — ★ 2026-05-29 に Phase C' へ転換、下記方針で上書き)

> 以下 18 項目は API 案前提。仕分けを Cowork 主導に転換したため取り消し線扱い。データ設計(Notion DB/プロパティ、SharePoint パス、Firestore 遷移)は Phase C' でも踏襲する。

#### Notion 連携

1. **既存 DB「設計タスク管理」を活用**、新規 DB を作らない、新規フィールドも追加しない
2. **既存「仕分け待ち」優先度タグを使用**(LINE 受信ファイルは全件これで投入)
3. **専用 Integration「LineTaskBot」を新規作成**、けいすけ手動で設計タスク管理 DB に招待
4. **作成者フィールドが LineTaskBot になることでけいすけ手動投入と区別**

#### Notion タスクの粒度

5. **1 ファイル = 1 タスク**(複数ファイル同時受信時は連投をメタで紐付け、集約はけいすけ手動)

#### Notion タスク命名

6. **タスク名: `【LINE】YYYY-MM-DD Claude推測タイトル`**
7. **タイトル: Claude が完全自動推測**(ファイル内容＋直近の text メッセージ＋ファイル名から)
8. **備考フィールドに Claude 推測詳細**(案件候補・確信度・判断理由・同 groupId 内の関連メッセージ ID)

#### SharePoint 保存先

9. **個別ファイル**: `案件名/09.受領資料/YYYY-MM-DD タイトル.<ext>`
10. **議事ログ**: `案件名/09.LINEやりとり資料/YYYY-MM-DD 議事ログ.md`
11. **09 番号は意図的に既存「09.受領資料」と並列、両方 09**
12. **議事ログ Markdown**: テキスト＋画像リンク(個別ファイルへの相対パス)が時系列に並ぶ形式
13. **書き込み手段**: PC の OneDrive 同期フォルダへのファイル書き込みのみ(Microsoft Graph API 不使用、Azure 登録不要)

#### ステージング・削除

14. **GCS pending/ は仕分け確定まで保持**、SharePoint 移動後に GCS から削除
15. **GCS ライフサイクル**: 90 日経過の pending/ オブジェクト自動削除(保険)
16. **Firestore `intake_messages.status` は pending → done に更新**、ドキュメントは削除しない(アーカイブ)

#### Cowork 許可フォルダ

17. ~~**`C:\Users\knaka\OneDrive - 株式会社ビギン\@@設計\51.LINE投稿ボット\pc_worker\`** に PC 側スクリプトと `.env` を配置~~ → **2026-05-29 A 方針で上書き(下記)**
18. ~~リポジトリの `pc_worker/` 配下を上記パスにコピーして運用~~ → **2026-05-29 A 方針で上書き(下記)**

### Phase C 実行環境(2026-05-29 確定、A 方針 — 項目 17/18 を上書き)

- pc_worker は **WSL2 リポジトリ内で開発・実行**(OneDrive へのコピー配置=B-2 案は不採用、二重管理の運用負債を避ける)
- `.env` も WSL 側 `pc_worker/.env` のみ。SharePoint 書き込みは WSL から `/mnt/c/.../OneDrive/...` 経由で同期に委ねる
- Cowork はコード・`.env`・実行コンソールに直接アクセスできないため、監査経路を 2 点で代替:
  1. `pc_worker/.env.example` を `Coworkとの受け渡し/` に複製(実値は共有しない)
  2. 実行ログを `$LOG_OUTPUT_DIR/YYYY-MM-DD/<run_id>.jsonl`(OneDrive 配下)に JSON Lines 複製。未設定・書込不可時は WARN でスキップし本処理は継続

### Phase C' 実装方針(2026-05-29 確定 — 仕分けを Cowork 主導に転換)

- **仕分け判断は Cowork(Opus, claude-opus-4-7)が担う**。pc_worker は判定ロジックを持たない薄い CLI **pc_cli** に再構築
- 転換理由: コスト(API 月 ¥1,000〜3,000 → ¥0)/ 精度(sonnet-4-6 → opus-4-7)/ 確信度低をその場で対話確認 / Phase D 連続性 / `ANTHROPIC_API_KEY` 不要
- **pc_cli**(`python -m app.cli <subcommand>`): pull-pending / download / list-cases / write-task / update-task / place-file / write-log / mark-done / mark-review の 9 サブコマンド。stdout=結果 JSON、stderr=ログ
- **削除**: classify.py / orchestrator.py / main.py(判定ロジックは `docs/cowork-skill-reference.md` に退避し Cowork Skill へ移植)
- 起動運用: スケジュールタスク 4 回/日(朝 9・昼 13・夕 18・夜 21)で Cowork 自動起動(Cowork 側で設定、pc_cli は関与しない)
- データ設計(Notion DB「設計タスク管理」/「仕分け待ち」優先度 / Firestore status 遷移)は Phase C の確定事項を踏襲
- **SHAREPOINT_ROOT 配下は階層・命名が不規則**(ステータスフォルダ配下案件 / 直接案件 / 非案件 / 2〜3 階層混在)。固定パスを組み立てず、`list-case-folders` で候補を再帰スキャン → Cowork が案件名と突合 → 得た**絶対パス**を `place-file --case-folder` / `write-log --case-folder` に渡す。LINE 由来資料は `<案件フォルダ>/09.LINEやりとり資料/` に統一格納(サブフォルダ自動作成 OK、案件フォルダ自体の自動作成は NG=needs_review 運用)

### Phase C' 実行経路(2026-05-30 確定、A 案 — 2026-05-29 A 方針を上書き)

Cowork の bash は **WSL ではなく独立した Linux サンドボックス**(Ubuntu 22 / Python 3.10)。マウントは OneDrive の選択フォルダのみ(`/sessions/<動的セッション名>/mnt/<フォルダ名>/`、セッション名は実行毎に変わる)、WSL リポジトリには未到達、ネットワークは開。よって仕分けは **Cowork サンドボックス内で完結**させる(B 案=Cloud Run に HTTP API は不採用)。

- **動的マウントパスの解決は pc_cli 側の責務**。`.env` の `MOUNT_MAP`(Windows 絶対パスの `;` 列挙)から、pc_cli が実行時に実マウント先を特定(①自身の位置から現セッション mnt ベース→②WSL `/mnt/c`→③`/sessions/*/mnt` glob)。Skill はセッション名を注入しない
- **winpath 一般化**: (unix↔windows) 写像を最長一致適用、`/mnt/<drive>` をフォールバック。`destination_windows` 等が `/sessions/<動的>/mnt/@@@/...` でも `C:\...\@@@\...` に戻る
- **パス系 .env(SHAREPOINT_ROOT / TMP_DOWNLOAD_DIR / LOG_OUTPUT_DIR / GOOGLE_APPLICATION_CREDENTIALS)は Windows パスでも unix パスでも記述可**(Windows 形式なら実行時 unix 解決、WSL 開発は従来の `/mnt/c` 値で後方互換)
- **GCP 認証は SA 鍵ファイル + ADC 両対応**(サンドボックスは鍵、WSL は ADC)。鍵 JSON は `51.LINE投稿ボット/secrets/`(同期・コミット対象外)
- **正は WSL リポジトリ。OneDrive 実行コピーは `scripts/sync-pc-cli-to-onedrive.sh` で同期**(`.env` / `secrets/` は同期せず秘密値保護)。依存は `requirements.txt` 固定、揮発サンドボックスで起動毎に `pip install --break-system-packages`
- **サンドボックスへのコード配布は git clone を正とする(2026-05-30)**。OneDrive Files-On-Demand のプレースホルダは Cowork の Linux マウント越しに中身が途中で切れて読めず、`attrib +P` でも安定解消しないため。`scripts/sandbox-bootstrap.sh` が GitHub private repo を**ネイティブ fs(`/tmp/linetask`)**に clone→`.env` コピー→pip→AST 検証。OneDrive マウントや `/outputs` 直下は git 内部操作が失敗するため clone 先はネイティブ fs 必須。OneDrive からは小サイズで完全に読める `.env`・SA 鍵のみ使用。clone 用に `GITHUB_PAT`(Contents:Read のみの fine-grained PAT)を OneDrive `.env` に置く。検証は Windows 側 size でなく「サンドボックスが読むバイト列」で AST parse する

> 新しい決定をしたら、その都度ここを更新する。

---

## 申し送り(教訓集)

実装・運用で踏んだ罠と回避策を積み上げていくセクション。本セクションは空のまま開始、Phase A 着手後に蓄積する。

ProboxDesign で実証済みの汎用教訓(autonomous 連続完走の規模圧縮要因 / 3 役運用 / 受け渡しフォルダ運用)はそのまま継承する。

### Cowork サンドボックスの動的マウント(2026-05-30)

- Cowork の bash は WSL ではなく**揮発する独立 Linux サンドボックス**。OneDrive 選択フォルダが `/sessions/<動的セッション名>/mnt/<フォルダ名>/` にマウントされ、**セッション名は実行毎に変わる**ので固定値に依存してはいけない。
- 回避策: 実行コードは**自分自身の `__file__` パス**から現セッションの mnt ベースを割り出せる(`/sessions/<x>/mnt/...` 配下で動いているため)。これでセッション名注入なしに動的解決できる。glob `/sessions/*/mnt/<名>` は複数セッション残存時に誤るのでフォールバック扱い。
- マウントのフォルダ名(末尾要素)から Windows 親パスは導けない(`@@@`→`...\@@@` だが `51.LINE投稿ボット`→`...\@@設計\51.LINE投稿ボット`)。Windows 側絶対パスは明示設定(`MOUNT_MAP`)が必要。

---

## 未決事項(実装時に確定する)

- [ ] Notion の案件 DB / タスク DB の構造を確認し、記録先と仕分け候補リストを確定(**Phase C 着手前に Cowork と相談**)
- [ ] タスク登録の方針:**推奨 = 「確信ありは静かに記録(案件ページに 1 行)/ 要確認だけ実タスク」**(未確定、Phase C 着手時に確定)
- [ ] 案件フォルダ内の「受領資料の定位置」サブフォルダ名(Phase C 着手時に確定)
- [ ] 仕分けの確信度しきい値(初期 0.8 で運用しながら調整)
- [ ] 受信ログにテキストメッセージも残すか(会話まるごとアーカイブ)/ ファイルだけにするか(Phase B 着手時に確定)
- [ ] Firestore Emulator / GCS Emulator を開発で使うか、開発用の別プロジェクトに書くか(Phase B 着手時に判断)
- [ ] Cowork 許可フォルダの具体パス(Phase C 着手時に確定)

---

## 検討中・保留中の項目

将来的に検討する項目。確定したらこのファイルに追記する。

- 受信したファイルが大きい場合のバックグラウンド DL 分離(Webhook 即 200 を守りつつ)
- アーカイブ検索の自然言語クエリパターン整理(Cowork Skill 化、Phase D)
- 仕分け失敗時のリトライ戦略(API エラー / Claude タイムアウト)
- 多言語対応(現状は日本語前提)
- 受信元の拡張(将来メールや別チャットツールを加える場合、`case-intake` 的に抽象化するか判断)

> 新しい決定をしたら、その都度ここを更新する。

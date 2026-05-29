# LineTaskCollection

LINE グループに届く案件資料（見積書・図面・写真など）を自動で仕分け・格納するアプリ。

## アーキテクチャ（2026-05-29 Phase C' 転換後）

```
[LINEグループ] 依頼主が資料を投稿
   │ Webhook
   ▼
[Cloud Run] 受信専用・常時稼働（Phase B 完成、変更なし）
   ├ 署名検証 → コンテンツ即DL
   ├ 実体     → GCS（pending/）
   └ メタ     → Firestore（status=pending）
        │
        │ pc_cli（薄い CLI ラッパー、判定ロジックなし）を bash 経由で呼ぶ
        ▼
[Cowork（Opus）= 仕分け判断]  ← スケジュールタスク 4回/日 or 手動起動
   ├ pull-pending / download でファイル取得 → マルチモーダル判定
   ├ 確信あり → place-file（SharePoint）+ write-task/update-task（Notion）+ mark-done
   └ 迷い    → けいすけに対話確認 or mark-review
```

仕分け判断は **Cowork（Opus）** が担い、`pc_cli` は GCS / Notion / SharePoint の API ラッパーに徹する。

- プロジェクトルール: [CLAUDE.md](CLAUDE.md)
- 実装仕様: [docs/line-intake-design.md](docs/line-intake-design.md)
- pc_cli の使い方: [docs/operations.md](docs/operations.md) §Phase C': pc_cli の使い方
- Cowork Skill 移植用リファレンス: [docs/cowork-skill-reference.md](docs/cowork-skill-reference.md)

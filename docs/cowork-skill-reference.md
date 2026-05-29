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

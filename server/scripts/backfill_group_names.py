"""既存 groupId の intake_groups.groupName を一括バックフィルする（任意・一回限り）。

★ 実行場所の制約: LINE チャネルアクセストークンを使うため、**LINE トークンと Firestore 認証が
   揃った server 環境でのみ**実行する（例: Cloud Shell で `LINE_CHANNEL_ACCESS_TOKEN` を export ＋
   ADC、または Cloud Run ジョブ）。**PC 側 pc_cli では実行しない**（PC に LINE トークンを置かない方針）。

使い方（server/ ディレクトリから）:
    LINE_CHANNEL_ACCESS_TOKEN=<token> FIRESTORE_PROJECT=probox-linetask-prod \
      python scripts/backfill_group_names.py [--overwrite]

- intake_messages から重複排除した groupId を集め、未取得（または --overwrite）の groupName を
  group summary API で解決して intake_groups に保存する。
- 解決失敗（room/1:1/退室済み等）はスキップ。新規受信ぶんは受信ハンドラが自動で埋めるので、
  本スクリプトは過去分の補完用。
"""

import sys
from pathlib import Path

# server/ を import パスに通す（app.* を解決）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import profile  # noqa: E402
from app.firestore import _get_client, set_group_name  # noqa: E402


def main(overwrite: bool = False) -> None:
    fs = _get_client()

    # 既存 intake_groups の groupName 取得状況
    have: dict[str, bool] = {}
    for doc in fs.collection("intake_groups").stream():
        have[doc.id] = bool((doc.to_dict() or {}).get("groupName"))

    # intake_messages から groupId を収集（join 行含む）
    group_ids = set()
    for doc in fs.collection("intake_messages").stream():
        gid = (doc.to_dict() or {}).get("groupId")
        if gid and gid != "N/A":
            group_ids.add(gid)

    resolved = skipped = 0
    for gid in sorted(group_ids):
        if have.get(gid) and not overwrite:
            continue
        name = profile.resolve_group_name(gid)
        if name:
            set_group_name(gid, name)
            resolved += 1
            print(f"[backfill] {gid} -> {name}")
        else:
            skipped += 1
            print(f"[backfill] {gid} -> (解決できずスキップ)")

    print(f"[backfill] done: resolved={resolved} skipped={skipped} total_groups={len(group_ids)}")


if __name__ == "__main__":
    main(overwrite="--overwrite" in sys.argv)

"""実績 HTML の決定的生成（Notion を唯一の真実に、毎回まるごと上書き）。

Notion の【LINE】タスクページ群 → §3 行スキーマ → テンプレ HTML の「データ部」と「生成日時」だけ
差し替えて出力する。LLM 判断は介さない。OneDrive は書くだけ（読まない＝未ハイドレートの罠を避ける）。
"""

import json
import re
from urllib.parse import unquote

from app.notion_writer import (
    LINE_TASK_PREFIX,
    PROP_DATE,
    PROP_DATE_REGISTERED,
    PROP_NOTE,
    PROP_ONEDRIVE,
    PROP_PRIORITY,
    PROP_STATUS,
    PROP_TITLE,
)

_GEN_MARKER = "★ここを生成日時に差し替え★"
_DATA_MARKER = "★ここに §3 の行配列 JSON を差し込む★"
LINE_SUBFOLDER = "09.LINEやりとり資料"

# 実データの備考は独立行でなく key=value のインライン（<br>・スラッシュ・句点区切り）。
# `=` と `:`（半角/全角）両対応で抽出する（2026-05-31 頑健化）。
_CASE_RE = re.compile(r"案件\s*[:：]\s*(.+?)(?:<br>|\n|$)")
_GID_RE = re.compile(r"groupId\s*[=:：]\s*(C[0-9a-fA-F]{32})")
_GID_ROOM_RE = re.compile(r"groupId\s*[=:：]\s*C[0-9a-fA-F]{32}\s*[(（]([^)）]+)[)）]")
_CONF_RE = re.compile(r"確信度\s*[=:：]\s*([^\s。/、（(<]+)")
_FILE_LINE_RE = re.compile(r"ファイル\s*[:=：]\s*(.+?)(?:<br>|\n|$)")
_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,8}$")


def _plain(rich: list) -> str:
    return "".join(part.get("plain_text", "") for part in (rich or [])).strip()


def _search1(rx: re.Pattern, note: str) -> str:
    m = rx.search(note)
    return m.group(1).strip() if m else ""


def _basename(path: str) -> str:
    return re.split(r"[\\/]", path.rstrip("/\\"))[-1]


def _has_ext(name: str) -> bool:
    return bool(_EXT_RE.search(name))


def _derive_fname(note: str, onedrive: str) -> str:
    """fname 決定: ①備考の『ファイル:』行 → ②OneDrive 末尾が拡張子付きならその basename → ③空。"""
    line = _search1(_FILE_LINE_RE, note)
    if line:
        return line
    base = _basename(unquote(onedrive)) if onedrive else ""
    return base if _has_ext(base) else ""


def _derive_folder(onedrive: str) -> str:
    """09.LINEやりとり資料 フォルダの SharePoint URL を導出（生スペース＝未エンコードで返す）。

    http(s) のみ対象（ローカルパスは機械変換不可＝空）。ファイル URL は親、フォルダ URL はそのまま。
    末尾が 09 フォルダでなければ付加。テンプレが encodeURI するので `%20` でなく生スペースで持つ。
    """
    if not onedrive.startswith(("http://", "https://")):
        return ""
    url = unquote(onedrive).rstrip("/")
    if _has_ext(_basename(url)):
        url = url.rsplit("/", 1)[0]  # ファイル URL → 親フォルダ
    if LINE_SUBFOLDER not in url.split("/"):
        url = url + "/" + LINE_SUBFOLDER
    return url


def _norm_case(s: str) -> str:
    return s.replace("　", " ").strip()


def _date_value(props: dict, key: str) -> str:
    d = props.get(key, {}).get("date")
    if d and d.get("start"):
        return d["start"][:10]
    return ""


def _strip_title(title: str) -> str:
    """タスク名から先頭の【LINE】と日付プレフィックスを除いた表示用タイトル。"""
    t = title
    if t.startswith(LINE_TASK_PREFIX):
        t = t[len(LINE_TASK_PREFIX):]
    t = t.strip()
    m = re.match(r"^\d{4}-\d{2}-\d{2}\s+(.*)$", t)
    return m.group(1).strip() if m else t


def _notion_url(page_id: str) -> str:
    if not page_id:
        return ""
    return "https://www.notion.so/" + page_id.replace("-", "")


def build_rows(pages: list[dict]) -> list[dict]:
    """Notion ページ群を §3 の行スキーマ（テンプレ JS が消費するキー）に変換する。

    独立行ではなく実データのインライン（key=value）にも頑健に対応し、fname/folder は
    OneDrive プロパティから導出する。folder/fname は未エンコードの生文字列で持つ
    （テンプレが encodeURI するため二重エンコードを避ける）。
    """
    rows: list[dict] = []
    for page in pages:
        props = page.get("properties", {})
        title = _plain(props.get(PROP_TITLE, {}).get("title", []))
        note = _plain(props.get(PROP_NOTE, {}).get("rich_text", []))
        onedrive = props.get(PROP_ONEDRIVE, {}).get("url") or ""

        status = (props.get(PROP_STATUS, {}).get("status") or {}).get("name", "") or ""
        pri = (props.get(PROP_PRIORITY, {}).get("select") or {}).get("name", "") or ""
        date = _date_value(props, PROP_DATE_REGISTERED) or _date_value(props, PROP_DATE)

        rows.append({
            "date": date,
            "case": _norm_case(_search1(_CASE_RE, note)),
            "file": _strip_title(title),
            "fname": _derive_fname(note, onedrive),
            "folder": _derive_folder(onedrive),
            "status": status,
            "pri": pri,
            "link": _notion_url(page.get("id", "")),
            "gid": _search1(_GID_RE, note),
            "conf": _search1(_CONF_RE, note),
            "room_name": _search1(_GID_ROOM_RE, note),
        })
    return rows


def render_html(rows: list[dict], generated_at: str) -> str:
    """テンプレ HTML の (A) データ部 JSON と (B) 生成日時 の 2 箇所だけ差し替えて返す。"""
    # `<` を \\u003c に逃がして </script> ブレイクアウトを防ぐ（JSON.parse 上は等価）
    data_json = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    return _TEMPLATE.replace(_GEN_MARKER, generated_at).replace(_DATA_MARKER, data_json)


_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LINE 仕分け実績 — 配置先一覧</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin:0; background:#f7f7f5; color:#1f1f1f;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,sans-serif;
  font-size:14px; line-height:1.5; }
.wrap { max-width:1240px; margin:0 auto; padding:18px 16px 48px; }
header h1 { font-size:19px; margin:0 0 2px; }
header .sub { color:#6b6b6b; font-size:12.5px; margin-bottom:6px; }
.gen { color:#9a9a9a; font-size:12px; margin-bottom:14px; }
.gen a { margin-left:10px; }
.legend { display:flex; flex-wrap:wrap; gap:10px; margin:4px 0 14px; align-items:center; }
.controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:12px; }
.controls input[type=search]{ flex:1 1 240px; min-width:180px; padding:8px 11px; border:1px solid #d8d8d4; border-radius:8px; font-size:13.5px; background:#fff; }
.controls select,.controls button{ padding:7px 11px; border:1px solid #d8d8d4; border-radius:8px; background:#fff; font-size:13px; cursor:pointer; color:#1f1f1f; }
.controls button.active{ background:#1f1f1f; color:#fff; border-color:#1f1f1f; }
.summary { color:#6b6b6b; font-size:12.5px; margin-bottom:10px; }
table { width:100%; border-collapse:collapse; background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 1px 2px rgba(0,0,0,.05); }
thead th { text-align:left; font-size:12px; color:#555; font-weight:600; padding:10px 11px; border-bottom:1px solid #ececea; background:#fafaf8; cursor:pointer; white-space:nowrap; user-select:none; }
thead th .arrow { color:#b0b0b0; font-size:10px; margin-left:3px; }
tbody td { padding:10px 11px; border-bottom:1px solid #f1f1ef; vertical-align:top; }
tbody tr:hover { background:#fafaf8; }
.case { font-weight:600; }
.file { color:#2b2b2b; }
.note { color:#8a8a8a; font-size:12px; margin-top:3px; }
.chip { display:inline-flex; align-items:center; gap:5px; padding:2px 8px; border-radius:999px; font-size:12px; white-space:nowrap; background:#fff; border:1px solid #ececea; }
.dot { width:9px; height:9px; border-radius:50%; display:inline-block; }
.pri { padding:2px 8px; border-radius:6px; font-size:12px; white-space:nowrap; }
.pri-claude { background:#efe6fb; color:#6b32b8; }
.pri-wait { background:#e3edfb; color:#2563eb; }
.pri-other { background:#eee; color:#555; }
.status { padding:2px 8px; border-radius:6px; font-size:12px; background:#eef3ee; color:#3a6b46; white-space:nowrap; }
.status.done { background:#e9f5ec; color:#1f7a3d; }
.status.todo { background:#fdf6e3; color:#997404; }
a { color:#2563eb; text-decoration:none; }
a:hover { text-decoration:underline; }
.openlink { display:inline-block; padding:3px 9px; border:1px solid #d6e2fb; background:#f3f7ff; border-radius:7px; font-size:12.5px; margin:0 0 4px; }
.openlink.log { border-color:#e2d6fb; background:#f7f3ff; color:#6b32b8; }
.pathtext { color:#aaa; font-size:11px; word-break:break-all; margin-top:2px; }
.state { padding:40px 10px; text-align:center; color:#8a8a8a; }
.grouphdr td { background:#f2f1ee; font-weight:700; font-size:13px; padding:8px 11px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>LINE 仕分け実績 — 配置先一覧</h1>
    <div class="sub">LINE で届いた資料を、ボットがどの案件フォルダへ振り分けたかの一覧です。各行から資料本体と会話ログ（議事ログ）を開けます。</div>
    <div class="gen">スナップショット（生成: ★ここを生成日時に差し替え★）<a href="https://www.notion.so/1eb17f63e23f8049b326d299bae15518" target="_blank" rel="noopener">Notionで最新を見る ↗</a></div>
  </header>
  <div id="legend" class="legend"></div>
  <div class="controls">
    <input id="q" type="search" placeholder="案件・ファイル名・備考で絞り込み…">
    <select id="fstatus"><option value="">ステータス：すべて</option></select>
    <button id="grp" title="案件ごとにまとめる">案件でグループ化</button>
    <button id="hidedone" title="ステータスが完了の行を隠す">完了を非表示</button>
  </div>
  <div id="summary" class="summary"></div>
  <table>
    <thead><tr id="head"></tr></thead>
    <tbody id="body"></tbody>
  </table>
</div>

<script type="application/json" id="data">
★ここに §3 の行配列 JSON を差し込む★
</script>

<script>
const PALETTE = ["#2563eb","#16a34a","#d97706","#9333ea","#dc2626","#0891b2","#ca8a04","#0d9488"];
const COLS = [
  {key:"date",label:"登録日"},{key:"case",label:"案件"},{key:"file",label:"ファイル / タスク"},
  {key:"open",label:"資料・会話ログ"},{key:"room",label:"トークルーム"},{key:"pri",label:"優先度"},
  {key:"status",label:"ステータス"},{key:"link",label:"Notion"}
];
let ROWS = JSON.parse(document.getElementById("data").textContent);
ROWS.forEach(r=>{
  r.room  = r.gid ? "…"+r.gid.slice(-6) : "";
  r.fileUrl = r.folder ? encodeURI(r.folder + "/" + r.fname) : "";
  r.logUrl  = r.folder ? encodeURI(r.folder + "/議事ログ.html") : "";
  r.open = r.fname || "";
});
let sortKey="date", sortDir=-1, grouped=false, hideDone=false;

function hashIdx(s){ let h=0; for(let i=0;i<(s||"").length;i++){ h=(h*31+s.charCodeAt(i))>>>0; } return h%PALETTE.length; }
function esc(s){ return (s==null?"":String(s)).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

function buildHead(){
  document.getElementById("head").innerHTML = COLS.map(c=>{
    const ar = sortKey===c.key ? (sortDir<0?"▼":"▲") : "";
    return '<th data-k="'+c.key+'">'+esc(c.label)+'<span class="arrow">'+ar+'</span></th>';
  }).join("");
  document.querySelectorAll("th[data-k]").forEach(th=>{
    th.onclick = ()=>{ const k=th.dataset.k; if(sortKey===k) sortDir*=-1; else {sortKey=k; sortDir=1;} buildHead(); render(currentFiltered()); };
  });
}
function buildStatusFilter(){
  const set = Array.from(new Set(ROWS.map(r=>r.status).filter(Boolean))).sort();
  document.getElementById("fstatus").innerHTML =
    '<option value="">ステータス：すべて</option>' + set.map(s=>'<option>'+esc(s)+'</option>').join("");
}
function buildLegend(){
  const keys = Array.from(new Set(ROWS.map(r=>r.gid).filter(Boolean)));
  const el = document.getElementById("legend");
  if(!keys.length){ el.innerHTML=""; return; }
  el.innerHTML = '<span class="sub" style="color:#6b6b6b">トークルーム：</span>' + keys.map(g=>{
    const c = PALETTE[hashIdx(g)];
    return '<span class="chip"><span class="dot" style="background:'+c+'"></span>…'+esc(g.slice(-6))+'</span>';
  }).join("");
}
function currentFiltered(){
  const q=(document.getElementById("q").value||"").toLowerCase().trim();
  const fs=document.getElementById("fstatus").value;
  let rows=ROWS.slice();
  if(hideDone) rows=rows.filter(r=>r.status!=="完了");
  if(fs) rows=rows.filter(r=>r.status===fs);
  if(q) rows=rows.filter(r=>(r.case+" "+r.file+" "+r.fname+" "+r.gid).toLowerCase().indexOf(q)>=0);
  rows.sort((a,b)=>{ let x=String(a[sortKey]||"").toLowerCase(), y=String(b[sortKey]||"").toLowerCase(); return x<y?-1*sortDir:x>y?1*sortDir:0; });
  return rows;
}
function openCell(r){
  let h="";
  if(r.fileUrl) h+='<a class="openlink" href="'+esc(r.fileUrl)+'" target="_blank" rel="noopener">資料を開く ↗</a>';
  if(r.logUrl)  h+='<a class="openlink log" href="'+esc(r.logUrl)+'" target="_blank" rel="noopener">会話ログ ↗</a>';
  if(r.fname)   h+='<div class="pathtext">'+esc(r.fname)+'</div>';
  return h || '<span class="pathtext">—</span>';
}
function priCell(p){ const cls=p==="Claude追記"?"pri-claude":(p==="仕分け待ち"?"pri-wait":"pri-other"); return p?'<span class="pri '+cls+'">'+esc(p)+'</span>':""; }
function statusCell(s){ const cls=s==="完了"?"done":(s==="未着手"?"todo":""); return s?'<span class="status '+cls+'">'+esc(s)+'</span>':""; }
function roomCell(g){ if(!g) return '<span class="pathtext">—</span>'; const c=PALETTE[hashIdx(g)]; return '<span class="chip"><span class="dot" style="background:'+c+'"></span>…'+esc(g.slice(-6))+'</span>'; }
function rowHtml(r){
  return '<tr>'+
    '<td>'+esc(r.date||"")+'</td>'+
    '<td class="case">'+esc(r.case||"")+'</td>'+
    '<td><div class="file">'+esc(r.file||"")+'</div>'+(r.conf?'<div class="note">確信度: '+esc(r.conf)+'</div>':'')+'</td>'+
    '<td>'+openCell(r)+'</td>'+
    '<td>'+roomCell(r.gid)+'</td>'+
    '<td>'+priCell(r.pri)+'</td>'+
    '<td>'+statusCell(r.status)+'</td>'+
    '<td>'+(r.link?'<a href="'+esc(r.link)+'" target="_blank" rel="noopener">開く ↗</a>':'')+'</td>'+
  '</tr>';
}
function render(rows){
  const body=document.getElementById("body");
  document.getElementById("summary").textContent = rows.length+" 件";
  if(!rows.length){ body.innerHTML='<tr><td class="state" colspan="8">該当なし。</td></tr>'; return; }
  if(grouped){
    const g={}; rows.forEach(r=>{ const k=r.case||"（案件不明）"; (g[k]=g[k]||[]).push(r); });
    let html=""; Object.keys(g).sort().forEach(k=>{
      html+='<tr class="grouphdr"><td colspan="8">'+esc(k)+'　<span style="font-weight:400;color:#888">'+g[k].length+'件</span></td></tr>';
      html+=g[k].map(rowHtml).join("");
    });
    body.innerHTML=html;
  } else { body.innerHTML=rows.map(rowHtml).join(""); }
}
document.getElementById("q").addEventListener("input",()=>render(currentFiltered()));
document.getElementById("fstatus").addEventListener("change",()=>render(currentFiltered()));
document.getElementById("grp").addEventListener("click",()=>{ grouped=!grouped; document.getElementById("grp").classList.toggle("active",grouped); render(currentFiltered()); });
document.getElementById("hidedone").addEventListener("click",()=>{ hideDone=!hideDone; document.getElementById("hidedone").classList.toggle("active",hideDone); render(currentFiltered()); });
buildHead(); buildStatusFilter(); buildLegend(); render(currentFiltered());
</script>
</body>
</html>
'''

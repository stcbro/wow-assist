# -*- coding: utf-8 -*-
"""
lanzou_gui.py — 浏览器版图形界面（纯标准库，零依赖）

用法:  python lanzou_gui.py   然后自动打开浏览器 http://127.0.0.1:8765
"""
import json
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lanzou_core import LanzouClient, DOMAIN_RE

PORT = 8765

# 每个线程一个独立客户端（Cookie 隔离，避免并发串号）
import threading as _t
_local = _t.local()

def get_client():
    if not hasattr(_local, "client"):
        _local.client = LanzouClient()
    return _local.client

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>蓝奏云直链解析器</title>
<style>
  :root { --bg:#f5f7fa; --card:#fff; --main:#4f6ef2; --ok:#18a058; --err:#d03050; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:"Segoe UI","Microsoft YaHei",sans-serif; background:var(--bg);
         min-height:100vh; display:flex; justify-content:center; padding:40px 16px; }
  .wrap { width:100%; max-width:760px; }
  h1 { font-size:22px; color:#333; margin-bottom:6px; }
  .sub { color:#888; font-size:13px; margin-bottom:20px; }
  .card { background:var(--card); border-radius:12px; padding:22px;
          box-shadow:0 2px 10px rgba(0,0,0,.06); margin-bottom:16px; }
  label { display:block; font-size:13px; color:#555; margin:10px 0 6px; }
  input[type=text] { width:100%; padding:10px 12px; border:1px solid #ddd; border-radius:8px;
          font-size:14px; outline:none; }
  input[type=text]:focus { border-color:var(--main); }
  .row { display:flex; gap:10px; }
  button { background:var(--main); color:#fff; border:none; border-radius:8px;
           padding:10px 22px; font-size:14px; cursor:pointer; }
  button:hover { opacity:.9; }
  button.ghost { background:#eef1f8; color:var(--main); }
  .results { margin-top:4px; }
  .item { border:1px solid #eee; border-radius:10px; padding:12px 14px; margin-top:10px; }
  .item .name { font-weight:600; color:#333; font-size:14px; word-break:break-all; }
  .item .info { color:#777; font-size:12px; margin:4px 0; }
  .item .link { color:var(--main); font-size:12px; word-break:break-all; cursor:pointer; }
  .item .err { color:var(--err); font-size:12px; }
  .tag { display:inline-block; font-size:11px; border-radius:4px; padding:1px 6px;
         margin-left:8px; vertical-align:middle; }
  .tag.ok { background:#e8f7ef; color:var(--ok); }
  .tag.err { background:#fdeef0; color:var(--err); }
  #log { font-family:Consolas,monospace; font-size:12px; color:#666; background:#fafafa;
         border-radius:8px; padding:10px; max-height:180px; overflow:auto; white-space:pre-wrap; }
  .spin { display:inline-block; width:14px; height:14px; border:2px solid #fff;
          border-top-color:transparent; border-radius:50%; animation:r 0.8s linear infinite; }
  @keyframes r { to { transform:rotate(360deg); } }
</style>
</head>
<body>
<div class="wrap">
  <h1>🌀 蓝奏云直链解析器</h1>
  <div class="sub">纯 Python 标准库实现 · 学习项目 · 算法参考 KCNLanzouDirectLink (AGPL-3.0)</div>

  <div class="card">
    <label>分享链接（每行一个，支持批量；格式：链接 [密码]，空格分隔）</label>
    <input type="text" id="input" placeholder="https://xxx.lanzouw.com/xxxxx [访问密码]" />
    <label>统一密码（可选，仅对加密链接生效）</label>
    <input type="text" id="pwd" placeholder="无密码留空" />
    <div class="row" style="margin-top:14px">
      <button id="btn" onclick="parse()">解析直链</button>
      <button class="ghost" onclick="copyAll()">复制全部直链</button>
      <button class="ghost" onclick="downloadAll()">批量下载</button>
    </div>
  </div>

  <div class="card">
    <div class="sub" style="margin-bottom:8px">解析结果</div>
    <div class="results" id="results"><div class="info" style="color:#aaa">暂无结果</div></div>
  </div>

  <div class="card">
    <div class="sub" style="margin-bottom:8px">运行日志</div>
    <div id="log">等待操作...</div>
  </div>
</div>
<script>
let lastLinks = [];
async function parse() {
  const input = document.getElementById('input').value.trim();
  if (!input) return alert('请输入分享链接');
  const pwd = document.getElementById('pwd').value.trim();
  const btn = document.getElementById('btn');
  btn.disabled = true; btn.textContent = '解析中...';
  document.getElementById('results').innerHTML = '<div class="info" style="color:#aaa">请求中，请稍候（含反爬计算与重试，通常 2~6 秒）...</div>';
  try {
    const r = await fetch('/api/parse', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ input, pwd }) });
    const d = await r.json();
    render(d.results || []);
    log((d.log || []).join('\\n') || '(无日志)');
  } catch(e) { alert('请求失败: ' + e); }
  btn.disabled = false; btn.textContent = '解析直链';
}
function render(items) {
  lastLinks = items.filter(i => i.link).map(i => i.link);
  const box = document.getElementById('results');
  if (!items.length) { box.innerHTML = '<div class="info">无结果</div>'; return; }
  box.innerHTML = items.map(i => `
    <div class="item">
      <div class="name">${esc(i.name || '(未知文件)')}
        <span class="tag ${i.state==='Success'?'ok':'err'}">${i.state}</span></div>
      ${i.info ? `<div class="info">${esc(i.info)}</div>` : ''}
      ${i.link
        ? `<div class="link" onclick="navigator.clipboard.writeText('${esc(i.link)}');this.style.color='#18a058'"
           title="点击复制">${esc(i.link)}</div>`
        : `<div class="err">解析失败: ${esc(i.state)}</div>`}
    </div>`).join('');
}
function esc(s){ const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }
function copyAll() {
  if (!lastLinks.length) return alert('暂无可复制的直链');
  navigator.clipboard.writeText(lastLinks.join('\\n'));
  alert('已复制 ' + lastLinks.length + ' 条直链');
}
async function downloadAll() {
  if (!lastLinks.length) return alert('暂无可下载的直链');
  const r = await fetch('/api/download', { method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({ links: lastLinks }) });
  const d = await r.json();
  log('下载任务: ' + (d.log||[]).join('\\n'));
  alert(d.msg || '已开始后台下载');
}
function log(t){ document.getElementById('log').textContent = t; }
</script>
</body>
</html>"""

SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return self._send(400, {"error": "bad json"})

        if self.path == "/api/parse":
            return self._api_parse(payload)
        if self.path == "/api/download":
            return self._api_download(payload)
        self._send(404, {"error": "not found"})

    def _api_parse(self, payload):
        raw = payload.get("input", "")
        unified_pwd = payload.get("pwd", "").strip()
        results, all_log = [], []

        # 每行: "url" 或 "url 密码"
        tasks = []
        for line in re.split(r"[\n;]+", raw):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"(\S+)(?:\s+(.+))?", line)
            if m and DOMAIN_RE.match(m.group(1)):
                tasks.append((m.group(1), (m.group(2) or "").strip()))
        if not tasks and DOMAIN_RE.match(raw.strip().split()[0] if raw.strip() else ""):
            tasks.append((raw.strip().split()[0], unified_pwd))

        for url, pwd in tasks:
            client = get_client()
            client.log_lines = []
            use_pwd = pwd or unified_pwd
            if use_pwd:
                state, link = client.get_direct_link(url, password=use_pwd, retries=3)
            else:
                state, link = client.get_direct_link(url, retries=2)
                if state == "PostsignNotFound" and unified_pwd:
                    state, link = client.get_direct_link(url, password=unified_pwd, retries=3)

            name, info = "", ""
            if state == "Success":
                st, fi = client.get_file_info(url, use_pwd)
                if st == "Success" and fi:
                    name = fi.get("文件名") or ""
                    info = " · ".join(f"{k}:{v}" for k, v in fi.items() if v and k != "文件名")
            results.append({
                "url": url, "state": state, "link": link or "",
                "name": name, "info": info,
            })
            all_log.append(f"== {url} ==")
            all_log.extend(client.log_lines or [])

        self._send(200, json.dumps({"results": results, "log": all_log}, ensure_ascii=False))

    def _api_download(self, payload):
        links = payload.get("links", [])
        os.makedirs(SAVE_DIR, exist_ok=True)

        def worker():
            import urllib.request
            for link in links:
                try:
                    name = urllib.parse.urlsplit(link).path.split("/")[-1] or "download.bin"
                    name = re.sub(r'[\\/:*?"<>|]', "_", name)
                    path = os.path.join(SAVE_DIR, name)
                    req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
                        while True:
                            chunk = r.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                    print(f"[下载完成] {name}")
                except Exception as e:
                    print(f"[下载失败] {e}")

        threading.Thread(target=worker, daemon=True).start()
        self._send(200, json.dumps(
            {"msg": f"已开始后台下载 {len(links)} 个文件到 downloads 目录", "log": []},
            ensure_ascii=False))

    def log_message(self, *a):
        pass


def main():
    os.makedirs(SAVE_DIR, exist_ok=True)
    url = f"http://127.0.0.1:{PORT}"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        # 端口被占用 = 工具已经在运行，直接打开浏览器即可
        print(f"工具已在运行中，直接打开 {url}")
        webbrowser.open(url)
        return
    print(f"蓝奏云直链解析器已启动: {url}  (Ctrl+C 退出)")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()

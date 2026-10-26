# -*- coding: utf-8 -*-
"""
验证分发链接是否正常（蓝奏云公开分享页）
==========================================
用法：
    python 验证分发链接.py                      # 用默认链接 + 提取码
    python 验证分发链接.py <链接> <提取码>        # 自定义

检查项：
    · 链接能否打开、是否需要提取码
    · 文件列表里有没有「魔兽助手 vX.YZ.exe」
    · 同一份 exe 是否出现重复（蓝奏云同名不覆盖、会并存）
    · 顺手截图存 temp/lz_link_final.png
"""
import os
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(HERE, "temp")
EDGE_CANDIDATES = [
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
]
DEFAULT_URL = "https://sycc.lanzoum.com/b01i5y3r7c"
DEFAULT_PWD = "9p81"
EXE_RE = re.compile(r"魔兽助手\s*v[0-9.]+\.exe")


def find_edge():
    for p in EDGE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    pwd = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PWD
    edge = find_edge()
    if not edge:
        print("[错误] 找不到 Edge/Chrome")
        return 2
    os.makedirs(TMP, exist_ok=True)

    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=edge, headless=True,
                              args=["--no-sandbox", "--disable-gpu"])
        pg = br.new_context().new_page()
        pg.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)
        if pg.query_selector("#pwd"):
            pg.fill("#pwd", pwd)
            pg.click("#sub")
            time.sleep(6)
        title = pg.title()
        texts = []
        for f in pg.frames:
            try:
                t = f.evaluate("()=>document.body.innerText") or ""
                if t.strip():
                    texts.append(t)
            except Exception:
                pass
        body = max(texts, key=len) if texts else ""
        exes = EXE_RE.findall(body)

        print("=" * 60)
        print(f"链接   : {url}")
        print(f"提取码 : {pwd}")
        print(f"页面标题: {title}")
        print("=" * 60)
        print("文件列表:")
        for line in (body or "").splitlines():
            s = line.strip()
            if s and (re.search(r"\.(exe|zip|txt)", s) or "M " in s or "B " in s):
                print("   ", s)
        print("-" * 60)
        if not exes:
            print("✘ 列表里没有找到「魔兽助手 vX.YZ.exe」")
            rc = 1
        else:
            print(f"✔ 找到 exe：{', '.join(sorted(set(exes)))}")
            if len(exes) > 1:
                print(f"⚠ 出现 {len(exes)} 份同名 exe（蓝奏云不覆盖同名文件）")
                print("   → 执行：python 上传蓝奏云.py --folder <文件夹名> --prune")
                rc = 2
            else:
                print("✔ 只有一份，无重复")
                rc = 0
        pg.screenshot(path=os.path.join(TMP, "lz_link_final.png"), full_page=True)
        print(f"截图已存: {os.path.join(TMP, 'lz_link_final.png')}")
        br.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())

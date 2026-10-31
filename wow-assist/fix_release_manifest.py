# -*- coding: utf-8 -*-
"""蓝奏云「wow-assist」文件夹：删除旧的 release_manifest.txt 副本，上传修正版，并下载回校验。

用法（凭据走环境变量，与 上传蓝奏云.py 一致）：
    LZ_USER=手机号 LZ_PW=密码 python fix_release_manifest.py
若 temp/lz_state.json 登录态仍有效，则免密复用。
"""
import os
import re
import sys
import json
import hashlib
import importlib.util
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 动态导入中文文件名模块 上传蓝奏云.py
spec = importlib.util.spec_from_file_location("ul", os.path.join(HERE, "上传蓝奏云.py"))
ul = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ul)

MANIFEST = os.path.join(HERE, "release_manifest.txt")
FOLDER = "wow-assist"


def main():
    with open(MANIFEST, "r", encoding="utf-8") as f:
        mdata = json.load(f)
    want_md5 = str(mdata["exe"]["md5"]).lower()
    want_size = int(mdata["exe"]["size"])
    print("[本地 manifest] version=%s exe.md5=%s size=%s"
          % (mdata.get("version"), want_md5, want_size))

    edge = ul.find_edge()
    if not edge:
        print("[错误] 找不到 Edge/Chrome"); return 3

    user, pwd = ul.get_creds(ul.DEFAULT_STATE)
    from playwright.sync_api import sync_playwright
    state_path = ul.DEFAULT_STATE
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=edge, headless=True,
                               args=["--no-sandbox", "--disable-gpu"])
        ctx = br.new_context(user_agent=ul.UA)
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        ok = False
        try:
            if os.path.isfile(state_path):
                try:
                    ctx2 = br.new_context(storage_state=state_path, user_agent=ul.UA)
                    page2 = ctx2.new_page()
                    fr = ul.logged_in(page2)
                    if fr:
                        page, ctx, ok = page2, ctx2, True
                        print("[登录] 复用登录态成功")
                except Exception as e:
                    print("[登录] 登录态失效: %s" % str(e)[:80])
            if not ok:
                print("[登录] 用账号密码登录 ...")
                for _ in range(3):
                    if ul.do_login(page, user, pwd):
                        fr = ul.logged_in(page)
                        if fr:
                            ok = True
                            break
                    print("  重试 ...")
            if not ok:
                print("[失败] 无法登录蓝奏云"); return 3

            # 进入文件夹
            fr = ul.get_files_frame(page)
            if fr is None:
                print("[错误] 找不到文件列表 iframe"); return 4
            if not ul.enter_folder(page, fr, FOLDER):
                print("[警告] 未成功进入「%s」，仍尝试在当前目录操作" % FOLDER)
            fr = ul.get_files_frame(page) or fr

            # 删除所有旧的 release_manifest.txt 副本
            rows = ul.list_rows(fr)
            mrows = [r for r in rows if "release_manifest.txt" in (r.get("txt") or "")]
            print("[清理] 找到 %d 个 release_manifest.txt 副本" % len(mrows))
            for r in mrows:
                print("   删除: %s  (id=%s)" % ((r.get("txt") or "")[:50], r.get("id")))
                ul.delete_row(fr, page, r["id"])
                fr = ul.get_files_frame(page) or fr

            # 刷新后上传修正版
            fr = ul.refresh_folder(page, fr, FOLDER)
            print("[上传] 上传修正版 release_manifest.txt ...")
            up_ok, fr = ul.upload_file(page, fr, MANIFEST, FOLDER)
            if not up_ok:
                print("[警告] 上传未确认成功，请到蓝奏云网页核对")

            # 校验：统计副本数 + 下载直链比对 md5
            fr = ul.get_files_frame(page) or fr
            rows = ul.list_rows(fr)
            mrows = [r for r in rows if "release_manifest.txt" in (r.get("txt") or "")]
            print("[校验] 当前 release_manifest.txt 副本数: %d" % len(mrows))
            try:
                from lanzou_core import LanzouClient
                url = mrows[0]["url"]
                c = LanzouClient(timeout=30)
                st, link = c.get_direct_link(url, pwd or "1acw")
                if st == "Success" and link:
                    req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
                    data = urllib.request.urlopen(req, timeout=20).read()
                    h = hashlib.md5(data).hexdigest().lower()
                    print("[校验] 远端 manifest md5=%s 期望=%s -> %s"
                          % (h, want_md5, "OK" if h == want_md5 else "MISMATCH"))
                    d = json.loads(data.decode("utf-8"))
                    em = d.get("exe") or {}
                    print("[校验] 远端 exe.md5=%s size=%s (期望 %s / %s)"
                          % (em.get("md5"), em.get("size"), want_md5, want_size))
                else:
                    print("[校验] 直链获取失败: %s" % st)
            except Exception as e:
                print("[校验] 下载校验跳过: %s" % str(e)[:120])
        finally:
            try:
                os.makedirs(os.path.dirname(state_path), exist_ok=True)
                ctx.storage_state(path=state_path)
                print("[登录态] 已保存 %s" % state_path)
            except Exception as e:
                print("[登录态] 保存失败: %s" % str(e)[:80])
            br.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

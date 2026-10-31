# -*- coding: utf-8 -*-
"""只读诊断：列出蓝奏云某文件夹里的文件行（不删除、不上传）。"""
import os
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("ul", os.path.join(HERE, "上传蓝奏云.py"))
ul = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ul)

FOLDER = sys.argv[1] if len(sys.argv) > 1 else "wow-assist"


def main():
    edge = ul.find_edge()
    if not edge:
        print("[错误] 找不到 Edge/Chrome")
        return 3
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
                for _ in range(3):
                    if ul.do_login(page, user, pwd):
                        if ul.logged_in(page):
                            ok = True
                            break
            if not ok:
                print("[失败] 无法登录")
                return 3
            fr = ul.get_files_frame(page)
            if fr is None:
                print("[错误] 找不到文件列表 iframe")
                return 4
            if not ul.enter_folder(page, fr, FOLDER):
                print("[警告] 未进入「%s」" % FOLDER)
            fr = ul.get_files_frame(page) or fr
            rows = ul.list_rows(fr)
            print("\n=== 文件夹「%s」当前文件 (%d 个) ===" % (FOLDER, len(rows)))
            for i, r in enumerate(rows):
                print("[%2d] id=%-12s %s" % (i, r.get("id"), r.get("txt", "")))
        finally:
            try:
                os.makedirs(os.path.dirname(state_path), exist_ok=True)
                ctx.storage_state(path=state_path)
            except Exception:
                pass
            br.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

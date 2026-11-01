# -*- coding: utf-8 -*-
"""manifest 单独补传：大文件上传后 Frame detached 的补救（不复传 exe）。"""
import os
import sys
import time
import importlib.util

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 wow-assist/
sys.path.insert(0, HERE)

spec = importlib.util.spec_from_file_location(
    "lz_helper", os.path.join(HERE, "上传蓝奏云.py"))
LZ = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LZ)

FOLDER = "wow-assist"
STATE = LZ.DEFAULT_STATE
MANIFEST = os.path.join(HERE, "release_manifest.txt")


def main():
    user, pwd = LZ.get_creds(STATE)
    edge = LZ.find_edge()
    if not edge:
        print("[错误] 找不到 Edge/Chrome")
        return 3
    from playwright.sync_api import sync_playwright

    page_holder = {}
    fr = [None]

    def refresh():
        fr[0] = LZ.refresh_folder(page_holder["page"], fr[0], FOLDER)
        return fr[0]

    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=edge, headless=True,
                               args=["--no-sandbox", "--disable-gpu"])
        ctx = br.new_context(user_agent=LZ.UA)
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        page_holder["page"] = page
        ok = False
        if STATE and os.path.isfile(STATE):
            try:
                ctx2 = br.new_context(storage_state=STATE, user_agent=LZ.UA)
                page2 = ctx2.new_page()
                page2.on("dialog", lambda d: d.accept())
                f = LZ.logged_in(page2)
                if f:
                    page, ctx, ok = page2, ctx2, True
                    page_holder["page"] = page
                    fr[0] = f
                    print("[登录] 复用登录态成功")
            except Exception as e:
                print(f"[登录] 登录态失效: {str(e)[:80]}")
        if not ok:
            print("[登录] 走账号密码登录 ...")
            for attempt in range(3):
                if LZ.do_login(page, user, pwd):
                    f = LZ.logged_in(page)
                    if f:
                        ok = True
                        fr[0] = f
                        print(f"[登录] 成功（第 {attempt+1} 次）")
                        break
                time.sleep(3)
        if not ok:
            print("[失败] 无法登录蓝奏云")
            return 3

        if fr[0] is None:
            fr[0] = LZ.get_files_frame(page)
        LZ.enter_folder(page, fr[0], FOLDER)
        fr[0] = LZ.get_files_frame(page) or fr[0]

        # 上传前先核对：manifest 应为 0 份（避免同名并存）
        rows = LZ.list_rows(fr[0])
        mt = [r for r in rows if "release_manifest.txt" in (r.get("txt", "") or "").lower()]
        if mt:
            print(f"[警告] manifest 已存在 {len(mt)} 份，先删再传 ...")
            for r in mt:
                LZ.delete_row(fr[0], page, r["id"])
                time.sleep(1.5)
            fr[0] = refresh()

        print("[补传] 上传 release_manifest.txt ...")
        LZ.upload_file(page, fr[0], MANIFEST, FOLDER)

        print("[复核] 刷新列表 ...")
        time.sleep(3)
        f = refresh()
        rows = LZ.list_rows(f)
        print("=== 最终文件夹内容 ===")
        for r in rows:
            print("   -", r.get("txt", "")[:80])
        v324 = [r for r in rows if "wowassist-v3.24.exe" in (r.get("txt", "") or "").lower()]
        v323 = [r for r in rows if "wowassist-v3.23.exe" in (r.get("txt", "") or "").lower()]
        v322 = [r for r in rows if "wowassist-v3.22.exe" in (r.get("txt", "") or "").lower()]
        mt = [r for r in rows if "release_manifest.txt" in (r.get("txt", "") or "").lower()]
        print(f"复核: v3.24={len(v324)}  v3.23={len(v323)}  v3.22={len(v322)}  manifest={len(mt)}")
        good = len(v324) == 1 and len(mt) == 1 and v323 and v322
        try:
            ctx.storage_state(path=STATE)
        except Exception:
            pass
        br.close()
    print("补传完成 ALL PASS" if good else "仍有异常，请人工核对")
    return 0 if good else 4


if __name__ == "__main__":
    sys.exit(main())

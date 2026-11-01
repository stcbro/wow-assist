# -*- coding: utf-8 -*-
"""
上传 v3.24 到「wow-assist」文件夹：
- 上传 wowassist-v3.24.exe + 新 release_manifest.txt
- 只删「旧 release_manifest.txt」（清单必须唯一，旧版 exe 一律保留——
  用户定的「上传后不删老版本」规则）
- 复核：v3.24 exe 副本数=1、manifest 副本数=1、历史版本仍在
复用 上传蓝奏云.py 的浏览器原语。
"""
import os
import sys
import time
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

spec = importlib.util.spec_from_file_location(
    "lz_helper", os.path.join(HERE, "上传蓝奏云.py"))
LZ = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LZ)

FOLDER = "wow-assist"
STATE = LZ.DEFAULT_STATE


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
        # 复用登录态
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

        # 进入文件夹
        if fr[0] is None:
            fr[0] = LZ.get_files_frame(page)
        LZ.enter_folder(page, fr[0], FOLDER)
        fr[0] = LZ.get_files_frame(page) or fr[0]

        # ---- 定向删除：旧 manifest（清单必须唯一；旧版 exe 全部保留）----
        def delete_all(keyword, label):
            n = 0
            while True:
                f = refresh()
                rows = LZ.list_rows(f)
                hits = [r for r in rows
                        if keyword.lower() in (r.get("txt", "") or "").lower()]
                if not hits:
                    break
                r = hits[0]
                print(f"  [删 {label}] {r['txt'][:50]}")
                LZ.delete_row(f, page, r["id"])
                n += 1
                time.sleep(1.5)
            print(f"  [删 {label}] 完成（共 {n} 份）")

        print("[1/3] 删除旧 release_manifest.txt ...")
        delete_all("release_manifest.txt", "manifest")

        # ---- 上传新版本 ----
        print("[2/3] 上传新 wowassist-v3.24.exe ...")
        ok1, fr[0] = LZ.upload_file(page, fr[0],
                                    os.path.join(HERE, "wowassist-v3.24.exe"), FOLDER)
        print("[3/3] 上传新 release_manifest.txt ...")
        ok2, fr[0] = LZ.upload_file(page, fr[0],
                                    os.path.join(HERE, "release_manifest.txt"), FOLDER)

        # ---- 复核（强刷列表后核对，铁律：不能只看上传完成提示）----
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
        if len(v324) != 1 or len(mt) != 1:
            print("[警告] v3.24 或 manifest 副本数不为 1，请到网页人工核对！")
            br.close()
            return 4
        if not v323 or not v322:
            print("[警告] 旧版本 exe 不在了？按规则应保留历史版本，请人工核对！")

        try:
            ctx.storage_state(path=STATE)
        except Exception:
            pass
        br.close()
    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""蓝奏云「wow-resources」文件夹：删除旧的 wowassist_字体.zip（侵权版），上传思源黑体替换版。

用法（凭据走环境变量，与 上传蓝奏云.py 一致）：
    LZ_USER=手机号 LZ_PW=密码 python upload_font_pack.py
若 temp/lz_state.json 登录态仍有效，则免密复用。
"""
import os
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 动态导入中文文件名模块 上传蓝奏云.py
spec = importlib.util.spec_from_file_location("ul", os.path.join(HERE, "上传蓝奏云.py"))
ul = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ul)

LOCAL_ZIP = r"D:/WorkBuddy/发布/蓝奏云资源包/wowassist_字体.zip"
FOLDER = "wow-resources"


def main():
    if not os.path.isfile(LOCAL_ZIP):
        raise SystemExit("[错误] 找不到本地字体包: " + LOCAL_ZIP)
    print("[本地] %s  (%.1f MB)"
          % (LOCAL_ZIP, os.path.getsize(LOCAL_ZIP) / 1048576))

    edge = ul.find_edge()
    if not edge:
        print("[错误] 找不到 Edge/Chrome")
        return 3

    from playwright.sync_api import sync_playwright
    state_path = ul.DEFAULT_STATE
    # 传入 state_path：未设凭据但存在登录态缓存时允许免密复用（不会直接退出）
    user, pwd = ul.get_creds(state_path)
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
                print("[失败] 无法登录蓝奏云")
                return 3

            # 进入文件夹
            fr = ul.get_files_frame(page)
            if fr is None:
                print("[错误] 找不到文件列表 iframe")
                return 4
            if not ul.enter_folder(page, fr, FOLDER):
                print("[警告] 未成功进入「%s」，仍尝试在当前目录操作" % FOLDER)
            fr = ul.get_files_frame(page) or fr

            # 删除所有旧的 字体 包副本（侵权版 + 旧命名）
            rows = ul.list_rows(fr)
            old = [r for r in rows
                   if ("wowassist_字体.zip" in (r.get("txt") or ""))
                   or ("魔兽助手" in (r.get("txt") or "") and ".zip" in (r.get("txt") or ""))]
            print("[清理] 找到 %d 个旧字体包副本" % len(old))
            for r in old:
                print("   删除: %s  (id=%s)" % ((r.get("txt") or "")[:50], r.get("id")))
                ul.delete_row(fr, page, r["id"])
                fr = ul.get_files_frame(page) or fr

            # 刷新后上传思源黑体版
            fr = ul.refresh_folder(page, fr, FOLDER)
            print("[上传] 上传思源黑体字体包 ...")
            up_ok, fr = ul.upload_file(page, fr, LOCAL_ZIP, FOLDER)
            if not up_ok:
                print("[警告] 上传未确认成功，请到蓝奏云网页核对")

            # 校验：统计副本数（应恰好 1 个）
            fr = ul.get_files_frame(page) or fr
            rows = ul.list_rows(fr)
            hits = [r for r in rows if "wowassist_字体.zip" in (r.get("txt") or "")]
            print("[校验] 当前 wowassist_字体.zip 副本数: %d" % len(hits))
            for r in hits:
                print("   - %s" % (r.get("txt") or "")[:60])
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

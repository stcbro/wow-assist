# -*- coding: utf-8 -*-
"""蓝奏云文件夹：删除旧的 <name> 副本，上传新的（替换式，保证只有 1 份）。

通用资源包上传：模组包/插件包/字体包 都可用。
删掉同名的旧副本（蓝奏云同名不覆盖、会并存），再上传新包，最后刷新列表校验副本数=1。

用法（凭据走环境变量，与 上传蓝奏云.py 一致）：
    LZ_USER=账号 LZ_PW=密码 python upload_resource_pack.py --name wowassist_模组包.zip --folder wow-resources
未设凭据时复用 temp/lz_state.json 登录态（免密）。
"""
import os
import sys
import argparse
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("ul", os.path.join(HERE, "上传蓝奏云.py"))
ul = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ul)

OUT = r"D:/WorkBuddy/发布/蓝奏云资源包"


def main():
    ap = argparse.ArgumentParser(description="资源包替换式上传（删旧+传新）")
    ap.add_argument("--name", required=True, help="要上传的 zip 文件名（位于 --src 目录）")
    ap.add_argument("--folder", default="wow-resources", help="蓝奏云目标文件夹")
    ap.add_argument("--src", default=OUT, help="本地资源包目录")
    args = ap.parse_args()

    local = os.path.join(args.src, args.name)
    if not os.path.isfile(local):
        raise SystemExit("[错误] 找不到本地文件: " + local)
    print("[本地] %s  (%.1f MB)" % (local, os.path.getsize(local) / 1048576))

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
                print("[登录] 用账号密码登录 ...")
                for _ in range(3):
                    if ul.do_login(page, user, pwd):
                        if ul.logged_in(page):
                            ok = True
                            break
                    print("  重试 ...")
            if not ok:
                print("[失败] 无法登录蓝奏云")
                return 3

            fr = ul.get_files_frame(page)
            if fr is None:
                print("[错误] 找不到文件列表 iframe")
                return 4
            if not ul.enter_folder(page, fr, args.folder):
                print("[警告] 未成功进入「%s」，仍尝试在当前目录操作" % args.folder)
            fr = ul.get_files_frame(page) or fr

            # 删掉所有旧副本（同名并存，必须清理）
            rows = ul.list_rows(fr)
            old = [r for r in rows if args.name in (r.get("txt") or "")]
            print("[清理] 找到 %d 个旧副本「%s」" % (len(old), args.name))
            for r in old:
                print("   删除: %s  (id=%s)" % ((r.get("txt") or "")[:50], r.get("id")))
                ul.delete_row(fr, page, r["id"])
                fr = ul.get_files_frame(page) or fr

            # 上传新包
            fr = ul.refresh_folder(page, fr, args.folder)
            print("[上传] 上传 %s ..." % args.name)
            up_ok, fr = ul.upload_file(page, fr, local, args.folder)
            if not up_ok:
                print("[警告] 上传未确认成功，请到蓝奏云网页核对")

            # 校验副本数
            fr = ul.get_files_frame(page) or fr
            rows = ul.list_rows(fr)
            hits = [r for r in rows if args.name in (r.get("txt") or "")]
            print("[校验] 当前「%s」副本数: %d" % (args.name, len(hits)))
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

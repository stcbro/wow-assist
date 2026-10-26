# -*- coding: utf-8 -*-
"""
WowAssist —— 资源包批量上传到蓝奏云
=====================================
把本地资源包目录里的 zip + 上传清单.txt 一次性传到蓝奏云指定文件夹，
并删除同目录下的**旧命名**同名资源（例如 魔兽助手_模组包.zip → wowassist_模组包.zip）。

用法：
    set LZ_USER=你的账号
    set LZ_PW=你的密码
    python 上传资源包.py --folder "乌龟服资源包20261025"
    python 上传资源包.py --folder "乌龟服资源包20261025" --src "D:/WorkBuddy/发布/蓝奏云资源包"

依赖：pip install playwright（复用系统 Edge）
"""
import os
import re
import sys
import time
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "temp", "lz_state.json")
EDGE_CANDIDATES = [
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0")
MYDISK = "https://up.woozooo.com/mydisk.php"
HOME_URLS = ["https://www.lanzou.com/", "https://lanzou.com/"]
DEFAULT_SRC = r"D:/WorkBuddy/发布/蓝奏云资源包"
# 旧命名（改名前的资源包文件名）→ 上传新文件后需要删掉
OLD_NAME_RE = re.compile(r"^魔兽助手[_-].*\.zip$")


def find_edge():
    for p in EDGE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def get_files_frame(page):
    for f in page.frames:
        if "item=files" in f.url:
            return f
    return None


def goto_retry(page, url, n=4, wait=1200):
    for _ in range(n):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(wait)
            return True
        except Exception:
            page.wait_for_timeout(1500)
    return False


def do_login(page, user, pwd):
    for home in HOME_URLS:
        try:
            if not goto_retry(page, home):
                continue
            page.wait_for_timeout(1500)
            try:
                page.click("text=登录", timeout=8000)
            except Exception:
                goto_retry(page, "https://up.woozooo.com/account.php?action=login")
            page.wait_for_timeout(3000)
            page.wait_for_selector("#username", timeout=12000)
            page.fill("#username", user)
            page.fill("#password", pwd)
            page.click("#s3")
            page.wait_for_timeout(5000)
            return True
        except Exception as e:
            print(f"    [登录] 失败: {type(e).__name__}: {str(e)[:90]}")
    return False


def enter_folder(page, fr, name):
    try:
        fr.get_by_text(name, exact=True).first.click(timeout=10000)
        page.wait_for_timeout(3500)
        return True
    except Exception as e:
        print(f"    [进入文件夹] 失败: {type(e).__name__}: {str(e)[:90]}")
        return False


def refresh_folder(page, fr, folder):
    if goto_retry(page, MYDISK):
        page.wait_for_timeout(4000)
        fr2 = get_files_frame(page)
        if fr2 is not None:
            enter_folder(page, fr2, folder)
            page.wait_for_timeout(3000)
            return get_files_frame(page) or fr2
    return fr


def list_rows(fr):
    return fr.evaluate("""()=>{
        const out=[];
        document.querySelectorAll('div.f_tb').forEach(d=>{
            const t=(d.innerText||'').trim().replace(/\\s+/g,' ');
            if(t) out.push({id:d.id, txt:t.slice(0,140)});
        });
        return out;
    }""")


def upload_one(page, fr, path, folder):
    """注入 -> 开始上传 -> 刷新列表确认真实存在（不能用 DOM 出现文件名判定）"""
    fname = os.path.basename(path)
    try:
        fr.get_by_text("上传文件", exact=True).first.click(timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(1800)
    try:
        fr.wait_for_selector("input[type=file]", timeout=12000, state="attached")
        fr.locator("input[type=file]").first.set_input_files(path)
    except Exception as e:
        print(f"    [上传] 注入失败: {type(e).__name__}: {str(e)[:110]}")
        return False, fr
    page.wait_for_timeout(2200)
    try:
        btn = fr.get_by_text("开始上传", exact=True)
        if btn.count() > 0:
            btn.first.click(timeout=6000)
    except Exception:
        pass
    for t in range(180):
        page.wait_for_timeout(2000)
        try:
            c = fr.content()
        except Exception:
            c = ""
        if re.search(r"100\s*%", c) or "上传成功" in c or "上传完成" in c:
            print(f"    [上传] {fname} 上传完成提示 (~{t*2}s)")
            break
    page.wait_for_timeout(2500)
    fr2 = refresh_folder(page, fr, folder)
    if fr2 is None:
        return False, fr
    names = [r.get("txt", "") for r in list_rows(fr2)]
    hit = [n for n in names if fname in n]
    if hit:
        print(f"    [上传] ✔ {fname} 已确认: {hit[0][:55]}")
        return True, fr2
    print(f"    [上传] ✘ {fname} 刷新后未在列表中找到")
    return False, fr2


def delete_row(fr, page, row_id):
    try:
        row = fr.locator(f"#{row_id}")
        if row.count() == 0:
            return False
        row.locator("a.f_selb").first.click(timeout=8000)
    except Exception as e:
        print(f"    [清理] {row_id} 打开菜单失败: {str(e)[:90]}")
        return False
    page.wait_for_timeout(1500)
    try:
        fr.get_by_text("删除文件", exact=True).first.click(timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1800)
    for sel in ["确定", "确认删除"]:
        try:
            btns = fr.get_by_text(sel, exact=True)
            if btns.count() > 0:
                btns.first.click(timeout=4000)
                break
        except Exception:
            pass
    try:
        pb = page.get_by_text("确定", exact=True)
        if pb.count() > 0:
            pb.first.click(timeout=4000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    gone = fr.locator(f"#{row_id}").count() == 0
    print(f"    [清理] {row_id} -> {'已删除' if gone else '已点删除(待刷新)'}")
    return gone


def main():
    ap = argparse.ArgumentParser(description="资源包批量上传")
    ap.add_argument("--src", default=DEFAULT_SRC, help="资源包本地目录")
    ap.add_argument("--folder", default="乌龟服资源包20261025", help="蓝奏云目标文件夹")
    ap.add_argument("--keep-old", action="store_true", help="保留旧命名文件（不删）")
    ap.add_argument("--only-clean", action="store_true", help="只清理旧命名文件，不重复上传")
    args = ap.parse_args()

    user = os.environ.get("LZ_USER", "").strip()
    pwd = (os.environ.get("LZ_PW") or os.environ.get("LZ_KEY") or "").strip()
    if not (user and pwd):
        print("[错误] 请设置环境变量 LZ_USER 与 LZ_PW（别用 LZ_PASS，会被过滤）")
        return 2

    files = sorted([os.path.join(args.src, f) for f in os.listdir(args.src)
                    if f.endswith(".zip") or f == "上传清单.txt"])
    if not files:
        print(f"[错误] {args.src} 里没有可上传的 zip")
        return 2
    total = sum(os.path.getsize(f) for f in files)
    print("=" * 62)
    print("  WowAssist —— 资源包批量上传")
    print("=" * 62)
    print(f"源目录: {args.src}")
    print(f"目标文件夹: {args.folder}")
    print(f"待传 {len(files)} 个文件，合计 {total/1048576:.1f} MB")
    for f in files:
        print(f"   - {os.path.basename(f)}  ({os.path.getsize(f)/1048576:.1f} MB)")

    edge = find_edge()
    if not edge:
        print("[错误] 找不到 Edge/Chrome")
        return 2

    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=edge, headless=True,
                              args=["--no-sandbox", "--disable-gpu"])
        ctx = br.new_context(user_agent=UA)
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        try:
            logged = False
            if os.path.isfile(STATE):
                print("[1/4] 尝试复用登录态 ...")
                try:
                    c2 = br.new_context(storage_state=STATE, user_agent=UA)
                    p2 = c2.new_page()
                    if goto_retry(p2, MYDISK):
                        p2.wait_for_timeout(4000)
                        fr = get_files_frame(p2)
                        if fr and fr.get_by_text("上传文件", exact=True).count() > 0:
                            page, ctx = p2, c2
                            logged = True
                            print("      登录态有效")
                except Exception:
                    pass
            if not logged:
                print("[2/4] 登录蓝奏云 ...")
                ok = False
                for _ in range(3):
                    if do_login(page, user, pwd):
                        if goto_retry(page, MYDISK):
                            page.wait_for_timeout(4000)
                            fr = get_files_frame(page)
                            if fr is not None and fr.get_by_text("上传文件", exact=True).count() > 0:
                                ok = True
                                break
                    time.sleep(3)
                if not ok:
                    print("[失败] 无法登录")
                    return 3
            print("[3/4] 进入文件夹「%s」 ..." % args.folder)
            fr = get_files_frame(page)
            if fr is None:
                print("      未找到文件列表 iframe")
                return 4
            enter_folder(page, fr, args.folder)
            page.wait_for_timeout(1500)
            fr = get_files_frame(page) or fr

            if args.only_clean:
                print("[4/4] 跳过上传 (--only-clean)")
            else:
                print("[4/4] 逐个上传 ...")
                for f in files:
                    print(f"  -> {os.path.basename(f)}")
                    ok, fr = upload_one(page, fr, f, args.folder)
                    if not ok:
                        print(f"  !! {os.path.basename(f)} 上传未确认成功")
                    page.wait_for_timeout(1500)

            # 清理旧命名文件
            if not args.keep_old:
                print("[清理] 删除旧命名资源包 ...")
                for round_i in range(30):
                    fr = refresh_folder(page, fr, args.folder)
                    target = None
                    for r in list_rows(fr):
                        m = re.search(r"魔兽助手[_-][^\s]*\.zip", r.get("txt", ""))
                        if m:
                            target = (r["id"], m.group(0))
                            break
                    if not target:
                        print(f"    旧命名文件已清理完毕（共 {round_i} 个）")
                        break
                    print(f"    删除 {target[1]}")
                    delete_row(fr, page, target[0])
        finally:
            try:
                ctx.storage_state(path=STATE)
            except Exception:
                pass
            br.close()
    print("=" * 62)
    print("  完成")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())

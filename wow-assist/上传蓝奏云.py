# -*- coding: utf-8 -*-
"""
WowAssist —— 蓝奏云一键上传（自动带版本号）
==================================================
用法（推荐：环境变量传凭据，一条命令搞定）：

    set LZ_USER=你的手机号
    set LZ_PW=你的密码
    python 上传蓝奏云.py

不设环境变量时，脚本会交互式提示输入（密码不回显，不落盘）。
注意：变量名请用 LZ_PW 而不是 LZ_PASS —— 部分执行环境会过滤含 PASS 的名字。

常用参数：
    --file "wowassist-v3.12.exe"   指定要上传的文件（默认自动取项目目录里最新的「wowassist-vX.YZ.exe」）
    --folder wow-assist             目标文件夹名（默认「wow-assist」）
    --prune                        上传成功后，删除该文件夹里其它旧版「wowassist-v*.exe」（只保留最新）
    --share                        上传后尝试读取该文件夹的分享链接与提取码
    --state 路径                   登录态缓存文件（默认 temp/lz_state.json，可重复使用免登录）
    --no-state                     不使用/不保存登录态
    --dry-run                      只检查本地文件与版本号，不联网

依赖：pip install playwright   （复用系统 Edge，无需下载 Chromium）
"""
import os
import re
import sys
import glob
import time
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(HERE, "temp")
DEFAULT_STATE = os.path.join(TMP, "lz_state.json")
EDGE_CANDIDATES = [
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0")

HOME_URLS = ["https://www.lanzou.com/", "https://lanzou.com/"]
MYDISK_URL = "https://up.woozooo.com/mydisk.php"


# ----------------------------------------------------------------- 本地工具
def read_app_version():
    """从 addon_helper.py 读取 APP_VERSION（单一版本来源）"""
    src = os.path.join(HERE, "addon_helper.py")
    try:
        with open(src, "r", encoding="utf-8") as f:
            m = re.search(r'APP_VERSION\s*=\s*"([0-9.]+)"', f.read())
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def find_exe(explicit=None):
    """定位要上传的 exe：显式指定 > 项目根最新「wowassist-v*.exe」> dist 里最新"""
    if explicit:
        p = os.path.abspath(explicit)
        return p if os.path.isfile(p) else None
    pats = [os.path.join(HERE, "wowassist-v*.exe"),
            os.path.join(HERE, "dist", "wowassist-v*.exe")]
    cands = []
    for pat in pats:
        cands += glob.glob(pat)
    if not cands:
        cands = glob.glob(os.path.join(HERE, "*.exe"))
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)


def human(n):
    try:
        n = float(n)
    except Exception:
        return str(n)
    for u in ["B", "K", "M", "G"]:
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} T"


def get_creds(state_path=None):
    """取凭据。

    注意坑：部分执行环境会过滤形如 *PASS* 的环境变量名（传进去会变成 None），
    所以这里同时接受 LZ_PASS / LZ_PW / LZ_KEY / LZ_SECRET 多个名字。

    若未提供凭据但存在登录态缓存文件（state_path），允许免凭据继续——
    登录环节会先尝试复用登录态，失效时再明确报错。
    """
    user = ""
    pwd = ""
    for k in ("LZ_USER", "LZ_PHONE", "LZ_NAME"):
        v = os.environ.get(k, "").strip()
        if v:
            user = v
            break
    for k in ("LZ_PW", "LZ_KEY", "LZ_SECRET", "LZ_PASS", "LZ_PWD"):
        v = os.environ.get(k, "").strip()
        if v:
            pwd = v
            break
    if user and pwd:
        return user, pwd
    if not sys.stdin.isatty():
        if state_path and os.path.isfile(state_path):
            print("[提示] 未设置凭据，但存在登录态缓存，将尝试复用登录态 ...")
            return user, pwd
        print("[错误] 未提供凭据：请设置环境变量 LZ_USER=账号 与 LZ_PW=密码")
        print("       （注意：用 LZ_PW，别用 LZ_PASS，部分环境会过滤含 PASS 的变量名）")
        sys.exit(2)
    import getpass
    if not user:
        user = input("蓝奏云账号(手机号): ").strip()
    if not pwd:
        pwd = getpass.getpass("蓝奏云密码(不回显): ").strip()
    return user, pwd


def find_edge():
    for p in EDGE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


# ----------------------------------------------------------------- 浏览器操作
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


def logged_in(page):
    """进入我的文件并确认拿到文件列表（= 登录有效）"""
    if not goto_retry(page, MYDISK_URL):
        return None
    page.wait_for_timeout(4000)
    f = get_files_frame(page)
    if f is None:
        return None
    try:
        if f.get_by_text("上传文件", exact=True).count() > 0:
            return f
    except Exception:
        pass
    return None


def do_login(page, user, pwd):
    """走官方网页登录流程：首页 -> 登录 -> 填表 -> 提交"""
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
            print(f"    [登录] {home} 失败: {type(e).__name__}: {str(e)[:100]}")
            continue
    return False


def enter_folder(page, fr, name):
    """在文件列表里进入指定文件夹"""
    try:
        fr.get_by_text(name, exact=True).first.click(timeout=10000)
        page.wait_for_timeout(3500)
        return True
    except Exception as e:
        print(f"    [进入文件夹] 失败: {type(e).__name__}: {str(e)[:120]}")
        return False


def list_rows(fr):
    """取文件列表行：[{id, text}]  id 形如 f326653283（DOM 顺序 = 时间倒序，最新在前）"""
    return fr.evaluate("""()=>{
        const out=[];
        document.querySelectorAll('div.f_tb').forEach(d=>{
            const t=(d.innerText||'').trim().replace(/\\s+/g,' ');
            if(t) out.push({id:d.id, txt:t.slice(0,140)});
        });
        return out;
    }""")


def upload_file(page, fr, path, folder):
    """点『上传文件』-> 注入 file input -> 『开始上传』-> 刷新列表确认真实存在。

    重要：不能用「DOM 里出现文件名」判断成功——webuploader 的待上传队列本来
    就含文件名，会立刻误判。必须等上传完成提示，再**刷新列表**核对。
    """
    fname = os.path.basename(path)
    try:
        fr.get_by_text("上传文件", exact=True).first.click(timeout=10000)
    except Exception as e:
        print(f"    [上传] 未找到『上传文件』按钮: {str(e)[:100]}")
    page.wait_for_timeout(1800)
    try:
        fr.wait_for_selector("input[type=file]", timeout=12000, state="attached")
        fr.locator("input[type=file]").first.set_input_files(path)
        print(f"    [上传] 已注入文件: {fname}")
    except Exception as e:
        print(f"    [上传] 注入文件失败: {type(e).__name__}: {str(e)[:150]}")
        return False, fr
    page.wait_for_timeout(2000)
    try:
        btn = fr.get_by_text("开始上传", exact=True)
        if btn.count() > 0:
            btn.first.click(timeout=6000)
            print("    [上传] 已点击『开始上传』")
    except Exception:
        pass
    # 等上传进度/完成提示
    for t in range(150):
        page.wait_for_timeout(2000)
        try:
            c = fr.content()
        except Exception:
            c = ""
        if re.search(r"100\s*%", c) or "上传成功" in c or "上传完成" in c:
            print(f"    [上传] 上传完成提示出现 (~{t*2}s)")
            break
    page.wait_for_timeout(2500)
    # 刷新列表确认真实存在
    fr2 = refresh_folder(page, fr, folder)
    if fr2 is None:
        return False, fr
    names = [r.get("txt", "") for r in list_rows(fr2)]
    hit = [n for n in names if fname in n]
    if hit:
        print(f"    [上传] ✔ 已确认存在于列表: {hit[0][:60]}")
        return True, fr2
    print("    [上传] ✘ 刷新后未在列表中找到，上传可能未真正提交")
    return False, fr2


def delete_row(fr, page, row_id):
    """按行 id 删除文件（『...』菜单 -> 『删除文件』-> 确认）"""
    try:
        row = fr.locator(f"#{row_id}")
        if row.count() == 0:
            print(f"    [清理] 找不到行 {row_id}")
            return False
        row.locator("a.f_selb").first.click(timeout=8000)
    except Exception as e:
        print(f"    [清理] {row_id} 打开菜单失败: {str(e)[:100]}")
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
    page.wait_for_timeout(4000)
    try:
        gone = fr.locator(f"#{row_id}").count() == 0
    except Exception:
        gone = False
    print(f"    [清理] {row_id} -> {'已删除' if gone else '已点删除(列表待刷新)'}")
    return gone


def refresh_folder(page, fr, folder):
    """重新载入『我的文件』并进入指定文件夹，返回最新的文件列表 frame"""
    if goto_retry(page, MYDISK_URL):
        page.wait_for_timeout(4000)
        fr2 = get_files_frame(page)
        if fr2 is not None:
            enter_folder(page, fr2, folder)
            page.wait_for_timeout(3000)
            fr2 = get_files_frame(page) or fr2
            return fr2
    return fr


def prune_folder(page, fr, keep_name, folder):
    """清理：删除旧版本号文件 + 同名重复副本（保留最新一个），最后刷新复核。

    注意：上传后蓝奏云列表是异步刷新的，所以进来先强制刷新一遍再统计，
    否则读到的还是上传前的旧列表，会漏删重复副本。
    """
    fr = refresh_folder(page, fr, folder)
    rows = list_rows(fr)
    same, olds = [], []
    for r in rows:
        txt = r.get("txt", "")
        for m in re.finditer(r"wowassist-v[0-9.]+\.exe", txt):
            nm = m.group(0)
            if nm == keep_name:
                if r["id"] not in [x[0] for x in same]:
                    same.append((r["id"], nm))
            elif nm not in [x[0] for x in olds]:
                olds.append((r["id"], nm))
    if len(same) > 1:
        print(f"    [清理] 发现 {len(same)} 份『{keep_name}』，保留最新 1 份，删除其余 {len(same)-1} 份")
        for rid, nm in same[1:]:
            delete_row(fr, page, rid)
    if olds:
        print(f"    [清理] 删除旧版本: {', '.join(n for _, n in olds)}")
        for rid, nm in olds:
            delete_row(fr, page, rid)
    if not same and not olds:
        print("    [清理] 无重复/旧版本文件")
        return
    # 刷新复核
    page.wait_for_timeout(2000)
    fr2 = refresh_folder(page, fr, folder)
    if fr2 is None:
        return
    left = [r for r in list_rows(fr2)
            if keep_name in r.get("txt", "") or re.search(r"wowassist-v[0-9.]+\.exe", r.get("txt", ""))]
    print(f"    [清理] 复核：当前该文件夹内相关文件 {len(left)} 份")
    for r in left:
        print(f"             - {r.get('txt','')[:70]}")


def try_get_share(page, fr, folder):
    """读取文件夹分享链接：只读页面内容，绝不点击任何菜单/删除类元素"""
    try:
        txt = page.evaluate("()=>document.body.innerText") or ""
        m = re.search(r"https?://[\w.-]*lanzou[\w.-]*/[\w-]+", txt)
        code = re.search(r"提取码[:：\s]*([0-9a-zA-Z]{4})", txt)
        if m:
            return {"link": m.group(0), "code": code.group(1) if code else ""}
    except Exception as e:
        print(f"    [分享] 读取失败(不影响上传): {type(e).__name__}: {str(e)[:100]}")
    return None


# ----------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="蓝奏云一键上传（带版本号）")
    ap.add_argument("--file", default=None, help="要上传的 exe（默认取最新带版本号产物）")
    ap.add_argument("--folder", default="wow-assist", help="目标文件夹名")
    ap.add_argument("--prune", action="store_true", help="删除同目录其它旧版本号文件")
    ap.add_argument("--share", action="store_true", help="尝试读取分享链接")
    ap.add_argument("--skip-upload", action="store_true", help="只做分享链接/清理，不重复上传")
    ap.add_argument("--state", default=DEFAULT_STATE, help="登录态缓存文件")
    ap.add_argument("--no-state", action="store_true", help="不用/不保存登录态")
    ap.add_argument("--dry-run", action="store_true", help="只做本地检查")
    args = ap.parse_args()

    print("=" * 62)
    print("  WowAssist —— 蓝奏云一键上传")
    print("=" * 62)

    # 铁律（2026-10-26 用户定）：wow-resources 永远只放资源包 zip，绝不传生成物（exe 等）
    FORBIDDEN_GEN_FOLDERS = {"wow-resources"}
    if args.folder.strip().lower() in FORBIDDEN_GEN_FOLDERS:
        print(f"[禁止] 「{args.folder}」是资源包专用文件夹，永远不传生成物（exe 等）。")
        print("       exe 请上传到「wow-assist」文件夹：--folder wow-assist")
        return 3

    ver = read_app_version()
    exe = find_exe(args.file)
    if not exe:
        print("[错误] 找不到要上传的 exe（先打包，或用 --file 指定）")
        return 2
    size = os.path.getsize(exe)
    print(f"版本号(代码内 APP_VERSION): {ver or '(未读到)'}")
    print(f"待上传文件: {os.path.basename(exe)}  ({human(size)} / {size} 字节)")
    print(f"目标文件夹: {args.folder}")
    if args.dry_run:
        print("[dry-run] 本地检查通过，未联网。")
        return 0

    edge = find_edge()
    if not edge:
        print("[错误] 找不到 Edge/Chrome 浏览器")
        return 2
    user, pwd = get_creds()

    from playwright.sync_api import sync_playwright

    state = None if args.no_state else args.state
    ok = False
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=edge, headless=True,
                              args=["--no-sandbox", "--disable-gpu"])
        ctx = br.new_context(user_agent=UA)
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        try:
            # 1) 复用登录态
            if state and os.path.isfile(state):
                print("[1/5] 尝试复用登录态 ...")
                try:
                    ctx2 = br.new_context(storage_state=state, user_agent=UA)
                    page2 = ctx2.new_page()
                    fr = logged_in(page2)
                    if fr:
                        page, ctx, ok = page2, ctx2, True
                        print("      登录态有效，跳过登录")
                except Exception as e:
                    print(f"      登录态失效: {str(e)[:80]}")
            # 2) 登录
            if not ok:
                print("[2/5] 登录蓝奏云 ...")
                for attempt in range(3):
                    if do_login(page, user, pwd):
                        fr = logged_in(page)
                        if fr:
                            ok = True
                            print(f"      登录成功（第 {attempt+1} 次尝试）")
                            break
                    print("      登录未通过，重试 ...")
                    time.sleep(3)
            if not ok:
                print("\n[失败] 无法登录蓝奏云。")
                print("       常见原因：")
                print("         · 密码不正确（改过密码请用新密码）")
                print("         · 账号触发风控，需要短信/验证码验证")
                print("         · 网络不通（蓝奏云偶尔抽风，可重试）")
                return 3

            # 3) 进入文件夹
            print(f"[3/5] 进入文件夹「{args.folder}」 ...")
            fr = get_files_frame(page)
            if fr is None:
                print("      未找到文件列表 iframe")
                return 4
            if not enter_folder(page, fr, args.folder):
                print(f"      警告：未成功进入「{args.folder}」，仍尝试在当前目录上传")
                page.wait_for_timeout(1000)
                fr = get_files_frame(page) or fr

            # 4) 上传
            if args.skip_upload:
                print("[4/5] 跳过上传 (--skip-upload)")
                upload_ok = True
            else:
                print("[4/5] 上传中 ...")
                upload_ok, fr = upload_file(page, fr, exe, args.folder)
                if not upload_ok:
                    print("      上传未确认成功，请到蓝奏云网页确认。")
                    return 5

            # 5) 校验 + 清理旧版
            print("[5/5] 校验上传结果 ...")
            page.wait_for_timeout(1500)
            fr = get_files_frame(page) or fr
            rows = list_rows(fr)
            base = os.path.basename(exe)
            hit = None
            for r in rows:
                if base in r.get("txt", ""):
                    hit = r
                    break
            if hit:
                print(f"      ✔ 列表中已找到: {hit.get('txt','')[:80]}")
            else:
                print("      ! 列表中未直接匹配到（可能蓝奏云已按同名自动处理）")

            if args.prune:
                print("    [清理] 清理重复副本与旧版本 ...")
                prune_folder(page, fr, base, args.folder)

            # 分享链接提示
            if args.share:
                print("[分享] 提示：蓝奏云的『外链分享地址』需在网页/App 里手动点开分享面板生成，")
                print("       脚本不做自动点击（避免误触删除）。若目标文件夹尚未对外分享，")
                print("       请在蓝奏云 App 里对该文件夹『分享』一次，生成链接与提取码。")
        finally:
            try:
                if state and not args.no_state:
                    os.makedirs(os.path.dirname(state), exist_ok=True)
                    ctx.storage_state(path=state)
                    print(f"\n登录态已保存: {state}")
            except Exception as e:
                print(f"\n登录态保存失败: {str(e)[:80]}")
            br.close()

    print("=" * 62)
    print("  完成：已上传", base)
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())

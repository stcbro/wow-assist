# -*- coding: utf-8 -*-
"""
WowAssist — 简单好用又省心的香草旧世魔兽游戏助手（纯 Python 标准库，零依赖）
作者：Bro.Cui ｜ 定位：简单好用又省心的香草旧世魔兽游戏助手
(C) 2026 Bro.Cui. All rights reserved. 原创自研作品，仅供玩家免费学习交流。

功能：贴蓝奏云链接 → 自动下载 → 自动解压 → 一键安装到游戏 Interface/AddOns
用法：双击 启动插件助手.bat，浏览器自动打开 http://127.0.0.1:8766
"""
import atexit
import ctypes
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanzou_core import LanzouClient, DOMAIN_RE  # noqa: E402

PORT = 8766

# 单一版本来源：发版时只改这一行（同步更新 ui.html 更新日志、以及打包后的文件名版本号）
APP_VERSION = "3.21"
# 打包成 exe 后：APP_DIR 用 exe 所在目录；未打包（脚本运行）时用脚本所在目录。
# ui.html 等资源从 PyInstaller 解压目录 _MEIPASS 读。
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    _RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    _RES_DIR = APP_DIR

# 运行时目录（config/缓存/临时/日志）全部放进系统 AppData，绝不污染游戏根目录。
# 这样 exe 拷到任何电脑放游戏根目录双击即用：游戏根目录里只有 exe 本体。
# 持久化模型（2026-10-26 起）：关闭工具后模组/插件/字体与下载缓存都保留，下次直接复用；
# 配置组件幂等（已装不重复装），安装前对冲突项先备份；缓存长期(默认30天)未用自动清理。
_RUNTIME_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                            "wowassist")
# v3.12 起数据目录更名为 wowassist；旧目录保留在此用于一次性迁移
_LEGACY_RUNTIME_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                                   "魔兽助手")
TEMP_DIR = os.path.join(_RUNTIME_DIR, "temp")
DOWNLOAD_DIR = os.path.join(_RUNTIME_DIR, "downloads")
CONFIG_PATH = os.path.join(_RUNTIME_DIR, "config.json")
RUN_LOG = os.path.join(_RUNTIME_DIR, "run.log")
RESTORE_LOG = os.path.join(_RUNTIME_DIR, "上次会话还原.log")


def _migrate_legacy_runtime():
    """一次性迁移：旧数据目录 AppData\\魔兽助手 -> AppData\\wowassist。

    仅当新目录不存在且旧目录存在时执行；失败不阻断启动（最坏情况=重新下载一次缓存）。
    """
    try:
        if os.path.isdir(_LEGACY_RUNTIME_DIR) and not os.path.isdir(_RUNTIME_DIR):
            os.makedirs(os.path.dirname(_RUNTIME_DIR), exist_ok=True)
            os.rename(_LEGACY_RUNTIME_DIR, _RUNTIME_DIR)
            return True
    except Exception:
        pass
    return False


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        os.makedirs(_RUNTIME_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ================= 内置资源（打包进 exe 尾部的资源 zip，需求一，暂未启用）=================
# 若启用：wowassist.exe = PyInstaller 程序 + resources.zip 追加在尾部。
# 解压目标改为 AppData\wowassist\unpacked（不再放游戏根/ exe 同目录）。
RES_DIR = None            # 解压后的资源根目录（含 模组包/插件包/Fonts）
_RES_STATE = {"busy": False, "done": False, "pct": 0, "msg": ""}


def _resources_base():
    """资源缓存根目录：固定在 AppData\\wowassist（不随 exe 走、不污染游戏根目录）。
    下载缓存（resources/）与内嵌解压（unpacked）都在此之下；绝不落在游戏根目录。"""
    try:
        os.makedirs(_RUNTIME_DIR, exist_ok=True)
        return _RUNTIME_DIR
    except Exception:
        return os.path.join(os.path.expanduser("~"), "wowassist")


def _ensure_resources():
    """确保内置资源已解压；返回资源根目录，无内嵌资源（脚本模式）返回 None。
    首次解压带全局进度（/api/resources 读取）。"""
    global RES_DIR
    if RES_DIR and os.path.isdir(RES_DIR):
        return RES_DIR
    if not getattr(sys, "frozen", False):
        return None
    base = _resources_base()
    if not base:
        return None
    target = os.path.join(base, "unpacked")
    if os.path.isfile(os.path.join(target, ".ok")):
        RES_DIR = target
        return RES_DIR
    try:
        with zipfile.ZipFile(sys.executable) as z:
            names = z.namelist()
            total = max(1, len(names))
            os.makedirs(target, exist_ok=True)
            _RES_STATE.update({"busy": True, "pct": 0,
                               "msg": "正在准备内置资源（首次约1-2分钟，仅一次）…"})
            for i, n in enumerate(names):
                z.extract(n, target)
                if i % 40 == 0 or i == total - 1:
                    _RES_STATE.update({"pct": int((i + 1) * 100 / total),
                                       "msg": "正在准备内置资源（%d/%d）…" % (i + 1, total)})
            with open(os.path.join(target, ".ok"), "w") as f:
                f.write("ok")
        _RES_STATE.update({"busy": False, "done": True, "pct": 100, "msg": ""})
        RES_DIR = target
        return RES_DIR
    except Exception as e:
        _RES_STATE.update({"busy": False, "msg": "资源解压失败：" + str(e)})
        return None


def _portable_detect():
    """启动第一步自检（用户要求）：双击 exe 后最先检查 exe 同级目录有没有 WoW.exe，
    以此判断 exe 是否被放在了魔兽游戏根目录。命中返回游戏根目录，否则返回 ""。
    比旧探测宽松：只看有没有魔兽主程序，不要求 Interface 已存在（全新客户端也认）。"""
    if not getattr(sys, "frozen", False):
        return ""
    try:
        root = os.path.dirname(sys.executable)
        names = {n.lower() for n in os.listdir(root)}
    except Exception:
        return ""
    for n in ("wow.exe", "wowclassic.exe", "vanillafixes.exe"):
        if n in names:
            return root
    return ""


def _guess_target_from_exe():
    """便携模式：exe 放在魔兽客户端根目录时自动推导游戏路径。
    判定：exe 同目录有魔兽主程序（WoW.exe 等）+ Interface 目录。
    AddOns 不存在也返回（后续 normalize_addons_path 会创建）。"""
    if not getattr(sys, "frozen", False):
        return ""
    root = os.path.dirname(sys.executable)
    wow_exes = ("WoW.exe", "WoWClassic.exe", "Wow.exe", "wow.exe.bak", "VanillaFixes.exe")
    lower = {e.lower(): e for e in (os.listdir(root) if os.path.isdir(root) else [])}
    has_wow = any(lower.get(n.lower()) and os.path.isfile(os.path.join(root, lower[n.lower()]))
                  for n in wow_exes)
    if has_wow and lower.get("interface") and os.path.isdir(os.path.join(root, lower["interface"])):
        return os.path.join(root, "Interface", "AddOns")
    return ""


# ================= 蓝奏云资源下载（需求二：云端分发）=================
# 资源不在 exe 里，改为从蓝奏云分卷下载到缓存目录后安装：
#   resources/模组包/  resources/插件包/AddOns/  resources/Fonts/ + 各自 .ok 标记
# 换电脑：拷贝 exe → 重新下载一次即可（config.json 里的 lanzou 链接配置随 exe 走）。
_LANZOU_KINDS = ("mods", "addons", "fonts")
_DL_STATE = {"busy": False, "kind": "", "file_idx": 0, "file_total": 0,
             "pct": 0, "speed": "", "msg": "", "error": ""}

# ---------- 文件夹分享模式（推荐）----------
# 作者把一个蓝奏云文件夹分享出来（链接+提取码），程序自动列出里面全部文件，
# 按文件名匹配各类资源分卷。换资源只需在文件夹里增删文件，程序零配置。
# 手动分卷链接（config.lanzou.*）保留为兜底：未配置 folder 或 folder 解析失败时生效。
_FOLDER_CACHE = {"ts": 0.0, "files": None, "err": ""}
_KIND_PATTERNS = {
    "mods": [r"^wowassist_模组包\.zip$"],
    "addons": [r"^wowassist_插件包_part\d+\.zip$"],
    "fonts": [r"^wowassist_字体\.zip$"],
}


# ---------- 自定义直链源（蓝奏云抽风时的通用兜底）----------
# 用户在「下载」页直接粘贴一组文件直链（COS/OSS/GitHub/任意可下载 URL 均可），
# 程序按【文件名】用上面同一套 _KIND_PATTERNS 自动归类到 mods/addons/fonts。
# 有了它，以后换任何托管都只是换 URL，工具本身不用再改。
def _direct_cfg():
    """config.direct.urls：直链列表（兼容字符串/换行/逗号分隔）。"""
    d = load_config().get("direct", {}) or {}
    urls = d.get("urls") or []
    if isinstance(urls, str):
        urls = re.split(r"[\r\n,]+", urls)
    return [str(u).strip() for u in urls if str(u).strip()]


def _url_filename(u):
    """从 URL 路径取文件名（自动 URL 解码，兼容中文名）。"""
    try:
        p = urllib.parse.urlsplit(u).path
        return urllib.parse.unquote(p.rsplit("/", 1)[-1])
    except Exception:
        return ""


def _norm_url(u):
    """直链归一化：路径/查询里的中文或特殊字符做百分号编码。
    必需：urllib 底层 http.client 只接受 ASCII，含中文的直链原样下载会直接
    抛 UnicodeEncodeError（实测）。已编码的 %xx 不会被二次编码（safe='%'）。"""
    try:
        p = urllib.parse.urlsplit(u)
        return urllib.parse.urlunsplit((
            p.scheme, p.netloc,
            urllib.parse.quote(p.path, safe="/%"),
            urllib.parse.quote(p.query, safe="=&%"),
            p.fragment))
    except Exception:
        return u


def _direct_links():
    """按文件名把直链归类。返回 {kind:[{url,name,direct}], '_unmatched':[名称]}。"""
    out = {k: [] for k in _LANZOU_KINDS}
    out["_unmatched"] = []
    for u in _direct_cfg():
        name = _url_filename(u)
        hit = None
        for k, pats in _KIND_PATTERNS.items():
            if any(re.match(p, name, re.I) for p in pats):
                hit = k
                break
        if hit:
            # url 用归一化后的（可安全下载）；name 保留可读中文名（给界面显示）
            out[hit].append({"url": _norm_url(u), "pwd": "", "name": name or u,
                             "size": "", "direct": True})
        else:
            out["_unmatched"].append(name or u)

    def _key(x):
        m = re.search(r"part(\d+)", x.get("name", ""), re.I)
        return int(m.group(1)) if m else 0
    for k in _LANZOU_KINDS:
        out[k].sort(key=_key)
    return out


def _folder_cfg():
    return load_config().get("folder", {}) or {}


def _folder_files(force=False):
    """解析 folder 分享页拿文件列表（5 分钟缓存）。
    返回 [{name,size,url,is_dir,...}] 或 None（未配置/解析失败，原因见 _FOLDER_CACHE['err']）。"""
    cfg = _folder_cfg()
    url = (cfg.get("url") or "").strip()
    if not url:
        return None
    now = time.time()
    if (not force and _FOLDER_CACHE["files"] is not None
            and now - _FOLDER_CACHE["ts"] < 300):
        return _FOLDER_CACHE["files"]
    try:
        from lanzou_core import LanzouClient
        c = LanzouClient(timeout=30)
        st, files = c.get_folder_files(url, (cfg.get("pwd") or "").strip())
        if st == "Success" and files:
            _FOLDER_CACHE.update({"ts": now, "files": files, "err": ""})
            return files
        if st == "Success":  # 空文件夹 / 提取码不对时蓝奏也返回 Success
            _FOLDER_CACHE.update({"ts": now, "files": None,
                                  "err": "文件夹为空或提取码不正确，请检查"})
        else:
            # 真实失败原因落 run.log（网络异常/反爬/代理 502 都能直接看到）
            detail = "; ".join((c.log_lines or [])[-3:]) or (c.last_error or "-")
            _log_wv("[蓝奏云] 文件夹解析失败 state=%s 原因: %s" % (st, detail))
            _FOLDER_CACHE.update({"ts": now, "files": None,
                                  "err": "解析失败（%s）：网络波动或链接/提取码问题，请重试" % (st or "无响应")})
    except Exception as e:
        _log_wv("[蓝奏云] 文件夹解析异常：" + repr(e))
        _FOLDER_CACHE.update({"ts": now, "files": None, "err": "文件夹解析异常：" + str(e)})
    return None


def _match_kind_files(kind, files):
    """从文件夹文件列表中按文件名匹配某类资源的分卷（part 按序号排序）。"""
    pats = _KIND_PATTERNS.get(kind, [])
    out = []
    for f in files:
        if f.get("is_dir"):
            continue
        name = f.get("name", "")
        if any(re.match(p, name, re.I) for p in pats):
            out.append({"url": f.get("url", ""), "pwd": "",
                        "name": name, "size": f.get("size", "")})

    def _key(x):
        m = re.search(r"part(\d+)", x.get("name", ""), re.I)
        return int(m.group(1)) if m else 0
    out.sort(key=_key)
    return out


def _resources_root():
    """下载缓存根目录（AppData\\wowassist\\resources，与 exe/游戏根目录完全分离）。"""
    b = _resources_base()
    return os.path.join(b, "resources") if b else None


def _kind_dst(kind):
    """某类资源解压目标目录（zip 内前缀即这些目录名）。"""
    root = _resources_root()
    if not root:
        return None
    return os.path.join(root, {"mods": "模组包", "addons": os.path.join("插件包", "AddOns"),
                               "fonts": "Fonts"}[kind])


def _kind_links(kind):
    """某类资源的分卷链接列表 [{"url","pwd","name","direct"?}]。
    优先级：自定义直链 → 蓝奏云文件夹（按文件名匹配）→ 手动分卷链接。
    配了直链就用直链（配了说明用户想用它），没配才回落到蓝奏云。"""
    d = _direct_links().get(kind) or []
    if d:
        return d
    files = _folder_files()
    if files:
        return _match_kind_files(kind, files)
    lz = load_config().get("lanzou", {}) or {}
    return [x for x in (lz.get(kind) or []) if x.get("url")]


def _kind_source(kind):
    """某类资源当前实际来源：直链 / 蓝奏云 / 手动 / ''（未配置）。"""
    if _direct_links().get(kind):
        return "直链"
    if _folder_cfg().get("url") and _folder_files():
        return "蓝奏云"
    lz = load_config().get("lanzou", {}) or {}
    if any(x.get("url") for x in (lz.get(kind) or [])):
        return "手动"
    return ""


def _kind_ready(kind):
    """该类资源是否已下载解压就绪。"""
    d = _kind_dst(kind)
    return bool(d) and os.path.isfile(os.path.join(d, ".ok"))


_KIND_LABEL = {"mods": "模组包", "addons": "插件包", "fonts": "字体包"}


def _ensure_kind_downloaded(kind, log_lines=None):
    """确保某类资源缓存就绪；未就绪则自动开始下载并阻塞等待完成。
    返回 None=就绪，否则返回错误信息字符串（供接口直接返回给前端）。"""
    if _kind_ready(kind):
        return None
    label = _KIND_LABEL.get(kind, kind)
    if log_lines is None:
        log_lines = []
    log_lines.append("[下载] " + label + "未下载，自动开始下载")
    _set_progress(2, msg=label + "未下载，开始自动下载…", stage="下载", log="[下载] " + label + "未下载，自动开始下载")
    threading.Thread(target=lambda: _download_kind(kind), daemon=True).start()
    deadline = time.time() + 1800
    while time.time() < deadline:
        if _DL_STATE.get("error"):
            break
        if _kind_ready(kind):
            break
        st = dict(_DL_STATE)
        _set_progress(min(60, 2 + int(st.get("pct", 0) * 0.58)),
                      msg="下载%s：%s" % (label, st.get("msg") or ""),
                      stage="下载")
        time.sleep(1.0)
    if _DL_STATE.get("error"):
        _err = _DL_STATE.get("error", "")
        _set_progress(0, done=True, msg=label + "下载失败")
        return label + "下载失败：" + _err
    if not _kind_ready(kind):
        _set_progress(0, done=True, msg=label + "下载超时")
        return label + "下载超时，请到「下载」页查看后重试"
    log_lines.append("[下载] " + label + "就绪，等待安装")
    _set_progress(log="[下载] " + label + "就绪，等待安装")
    return None


def _lanzou_state():
    """三类资源状态 + 下载进度 + 缓存体积。"""
    root = _resources_root()
    size = 0
    if root and os.path.isdir(root):
        for rt, _, fs in os.walk(root):
            for f in fs:
                try:
                    size += os.path.getsize(os.path.join(rt, f))
                except OSError:
                    pass
    kinds = {}
    for k in _LANZOU_KINDS:
        links = _kind_links(k)
        if _kind_ready(k):
            st = "ready"
        elif _DL_STATE.get("busy") and _DL_STATE.get("kind") == k:
            st = "downloading"
        elif not links:
            st = "no_links"
        else:
            st = "need_download"
        kinds[k] = {"state": st, "volumes": len(links), "links": links,
                    "src": _kind_source(k)}
    # folder 分享模式信息（UI 显示文件夹链接/文件数/解析错误）
    folder_cfg = _folder_cfg()
    folder = {"url": (folder_cfg.get("url") or "").strip(),
              "pwd": (folder_cfg.get("pwd") or "").strip(),
              "files": [], "err": _FOLDER_CACHE.get("err", "")}
    if folder["url"]:
        ff = _folder_files()
        if ff:
            folder["files"] = [{"name": f.get("name", ""), "size": f.get("size", "")}
                               for f in ff]
    # manifest 增量对比（配置了 manifest 链接或 folder 里有 manifest.txt 才显示）
    diff = None
    if (load_config().get("manifest", {}) or {}).get("url") or _folder_files():
        try:
            diff = _diff_manifest()
        except Exception:
            diff = None
    # 自定义直链源：已配条数 / 每类识别到几卷 / 无法识别的文件名
    dm = _direct_links()
    direct = {"urls": _direct_cfg(),
              "matched": {k: len(dm.get(k) or []) for k in _LANZOU_KINDS},
              "unmatched": dm.get("_unmatched", [])}
    return {"kinds": kinds, "cache_mb": round(size / 1048576, 1),
            "cache_dir": root or "", "dl": dict(_DL_STATE), "diff": diff,
            "cache_cfg": load_config().get("cache", {"auto_clean": True, "keep_days": 30}),
            "cache_lastused": load_config().get("cache_lastused", {}),
            "manifest": load_config().get("manifest", {}) or {},
            "folder": folder, "direct": direct}


def _download_file(url, dest, idx, total, kind):
    """下载单个文件到 dest，带进度/重试；返回是否成功。"""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                cl = r.headers.get("Content-Length")
                size = int(cl) if cl and cl.isdigit() else 0
                got = 0
                t0 = time.time()
                with open(dest, "wb") as f:
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        el = max(0.1, time.time() - t0)
                        _DL_STATE.update({
                            "file_idx": idx, "file_total": total,
                            "pct": int(got * 100 / size) if size else 0,
                            "speed": "%.0f KB/s" % (got / 1024 / el),
                            "msg": "正在下载第 %d/%d 卷（%s）" % (idx + 1, total, kind),
                        })
            if size and os.path.getsize(dest) != size:
                raise IOError("文件不完整（%d/%d）" % (os.path.getsize(dest), size))
            return True
        except Exception as e:
            last_err = e
            time.sleep(2)
    _DL_STATE["error"] = "第 %d 卷下载失败：%s" % (idx + 1, last_err)
    return False


def _download_kind(kind):
    """后台线程：解析直链→逐卷下载→解压→写 .ok 标记。"""
    global _DL_STATE
    _DL_STATE.update({"busy": True, "kind": kind, "file_idx": 0, "file_total": 0,
                      "pct": 0, "speed": "", "msg": "正在解析链接…", "error": ""})
    try:
        from lanzou_core import LanzouClient
        links = _kind_links(kind)
        if not links:
            if _folder_cfg().get("url"):
                _DL_STATE.update({"busy": False,
                                  "error": "文件夹里没找到该类资源文件（%s），请检查文件夹内容" % kind})
            elif _direct_cfg():
                _DL_STATE.update({"busy": False,
                                  "error": "备用直链里没识别到该类资源（%s），请检查文件名" % kind})
            else:
                _DL_STATE.update({"busy": False, "error": "未配置该类资源的下载链接（蓝奏云文件夹或备用直链）"})
            return
        _DL_STATE["file_total"] = len(links)
        dst = _kind_dst(kind)
        tmp = os.path.join(os.path.dirname(dst), ".dl_tmp_%s" % kind)
        os.makedirs(tmp, exist_ok=True)
        client = LanzouClient(timeout=30)
        zips = []
        for i, lk in enumerate(links):
            _DL_STATE.update({"file_idx": i, "msg": "正在解析第 %d/%d 卷直链…" % (i + 1, len(links))})
            if lk.get("direct"):
                # 自定义直链：URL 本身就是下载地址，不需要（也不能）走蓝奏云解析
                st, link = "Success", lk.get("url", "")
            else:
                st, link = client.get_direct_link(lk.get("url", ""), lk.get("pwd", ""))
            if st != "Success" or not link:
                _DL_STATE.update({"busy": False, "error": "第 %d 卷解析失败：%s" % (i + 1, st)})
                return
            zp = os.path.join(tmp, "part%d.zip" % (i + 1))
            if not _download_file(link, zp, i, len(links), kind):
                _DL_STATE.update({"busy": False})
                return
            zips.append(zp)
        # 全部下完 → 解压（zip 内已带 模组包/ 插件包/AddOns/ Fonts/ 前缀，
        # 所以解压到缓存根目录 resources/，而不是 kind 子目录）
        _DL_STATE.update({"pct": 99, "msg": "正在解压…"})
        base = _resources_root()
        os.makedirs(dst, exist_ok=True)
        for zp in zips:
            try:
                with zipfile.ZipFile(zp) as z:
                    z.extractall(base)
            except Exception as e:
                _DL_STATE.update({"busy": False, "error": "解压失败：" + str(e)})
                return
        with open(os.path.join(dst, ".ok"), "w") as f:
            f.write("volumes=%d\n" % len(zips))
        try:
            shutil.rmtree(tmp)
        except Exception:
            pass
        _touch_cache(kind)   # 记录本次使用，供 30 天未用自动清理判断
        _DL_STATE.update({"busy": False, "pct": 100, "msg": "完成",
                          "kind": "", "error": ""})
    except Exception as e:
        _DL_STATE.update({"busy": False, "error": "下载异常：" + str(e)})


def _builtin_sources_with_cache():
    """源路径解析：内置资源(无) → 下载缓存(有.ok) → config 手动路径。
    返回 (mod_src, addon_src, font_src, 来源说明)。"""
    root = _resources_root()
    if root:
        m, a, fo = (_kind_dst(k) for k in ("mods", "addons", "fonts"))
        if all(os.path.isfile(os.path.join(d, ".ok")) for d in (m, a, fo)):
            return m, a, fo, "蓝奏云缓存"
    cfg = load_config()
    return (cfg.get("mod_src") or "", cfg.get("addon_src") or "",
            cfg.get("font_src") or "", "手动配置")


# ---------- manifest 清单驱动的单插件增量更新 ----------
# manifest.txt（也放蓝奏云，程序启动时拉取对比；蓝奏云拒收 .json 故用 .txt）：
# {"version":"8.8","plugins":{"插件名":{"file":"x.zip","url":"..","pwd":"..","size":n,"md5":".."}}}
# 本地缓存记录每插件已装版本（缓存目录 .versions.json），只下载有变化的。
_MANIFEST_CACHE = {"data": None, "ts": 0.0}


def _versions_file():
    root = _resources_root()
    return os.path.join(root, ".versions.json") if root else None


def _load_versions():
    f = _versions_file()
    if f and os.path.isfile(f):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return {}
    return {}


def _save_versions(v):
    f = _versions_file()
    if f:
        try:
            with open(f, "w", encoding="utf-8") as fp:
                json.dump(v, fp, ensure_ascii=False, indent=1)
        except Exception:
            pass


def _fetch_manifest():
    """拉取并缓存 manifest（10 分钟内不重复拉）。返回 dict 或 None。
    来源：config.manifest.url 优先；否则 folder 里的 manifest.txt（.json 仅作历史兼容）。"""
    now = time.time()
    if _MANIFEST_CACHE["data"] and now - _MANIFEST_CACHE["ts"] < 600:
        return _MANIFEST_CACHE["data"]
    cfg = load_config()
    mf = cfg.get("manifest", {}) or {}
    url = mf.get("url", "")
    pwd = mf.get("pwd", "")
    if not url:
        files = _folder_files()
        if files:
            for f in files:
                nm = f.get("name") or ""
                if nm == "manifest.txt":
                    url, pwd = f.get("url", ""), ""
                    break
            else:
                for f in files:
                    if (f.get("name") or "") == "manifest.json":
                        url, pwd = f.get("url", ""), ""
                        break
    if not url:
        return None
    try:
        from lanzou_core import LanzouClient
        c = LanzouClient(timeout=20)
        st, direct = c.get_direct_link(url, pwd)
        if st != "Success" or not direct:
            return None
        req = urllib.request.Request(direct, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        _MANIFEST_CACHE.update({"data": data, "ts": now})
        return data
    except Exception:
        return None


def _diff_manifest():
    """对比 manifest 与本地缓存：返回 {待下载:[名字], 可更新:[名字], 缺失:[名字], 总计, 版本}。"""
    mf = _fetch_manifest() or {}
    plugins = mf.get("plugins", {}) or {}
    vers = _load_versions()
    local_dst = _kind_dst("addons")
    todo, update, missing = [], [], []
    for name, info in plugins.items():
        have = vers.get(name)
        dst = os.path.join(local_dst, name) if local_dst else ""
        if not (dst and os.path.isdir(dst)):
            missing.append(name)
        elif have != (info.get("md5") or info.get("size") or ""):
            update.append(name)
        else:
            continue
        todo.append(name)
    return {"todo": todo, "update": update, "missing": missing,
            "total": len(plugins), "version": mf.get("version", "")}


def _download_one_plugin(name, info, idx, total):
    """下载并解压单个插件到缓存；成功更新本地版本记录。"""
    from lanzou_core import LanzouClient
    c = LanzouClient(timeout=30)
    st, link = c.get_direct_link(info.get("url", ""), info.get("pwd", ""))
    if st != "Success" or not link:
        _DL_STATE["error"] = "插件 %s 链接解析失败：%s" % (name, st)
        return False
    root = _resources_root()
    tmp = os.path.join(root, ".dl_tmp_plugin.zip")
    if not _download_file(link, tmp, idx, total, "插件 " + name):
        return False
    dst = os.path.join(_kind_dst("addons"), name)
    try:
        os.makedirs(dst, exist_ok=True)
        with zipfile.ZipFile(tmp) as z:
            z.extractall(dst)
        os.remove(tmp)
    except Exception as e:
        _DL_STATE["error"] = "插件 %s 解压失败：%s" % (name, e)
        return False
    vers = _load_versions()
    vers[name] = info.get("md5") or info.get("size") or ""
    _save_versions(vers)
    return True


def _sync_plugins():
    """后台线程：按 manifest 增量下载/更新所有变化插件。"""
    _DL_STATE.update({"busy": True, "kind": "plugins", "pct": 0, "error": "",
                      "msg": "正在对比清单…"})
    try:
        diff = _diff_manifest()
        todo = diff["todo"]
        if not todo:
            _DL_STATE.update({"busy": False, "pct": 100, "msg": "已是最新",
                              "kind": ""})
            return
        mf = _fetch_manifest() or {}
        plugins = mf.get("plugins", {}) or {}
        _DL_STATE["file_total"] = len(todo)
        for i, name in enumerate(todo):
            _DL_STATE.update({"file_idx": i, "pct": 0,
                              "msg": "正在更新插件 %s（%d/%d）" % (name, i + 1, len(todo))})
            if not _download_one_plugin(name, plugins.get(name, {}), i, len(todo)):
                _DL_STATE.update({"busy": False})
                return
        with open(os.path.join(_kind_dst("addons"), ".ok"), "w") as f:
            f.write("manifest-synced\n")
        _DL_STATE.update({"busy": False, "pct": 100, "msg": "更新完成", "kind": ""})
    except Exception as e:
        _DL_STATE.update({"busy": False, "error": "同步异常：" + str(e)})


def get_mod_selection():
    """模组页勾选状态：{模组名(小写): bool}。未记录过的模组默认勾选(True)。"""
    cfg = load_config()
    sel = cfg.get("mods_selected")
    return sel if isinstance(sel, dict) else {}


def set_mod_selection(name, selected):
    """持久化单个模组的勾选状态。"""
    if not name:
        return
    cfg = load_config()
    sel = cfg.get("mods_selected")
    if not isinstance(sel, dict):
        sel = {}
    sel[name.lower()] = bool(selected)
    cfg["mods_selected"] = sel
    save_config(cfg)


def _get_selection(kind):
    """插件/字体页勾选状态：{名(小写): bool}，未记录过的默认勾选(True)。
    kind: 'addons' | 'fonts'（配置键 addons_selected / fonts_selected）。"""
    cfg = load_config()
    sel = cfg.get(kind + "_selected")
    return sel if isinstance(sel, dict) else {}


def _set_selection(kind, name, selected):
    """持久化单个插件/字体的勾选状态。"""
    if not name:
        return
    cfg = load_config()
    key = kind + "_selected"
    sel = cfg.get(key)
    if not isinstance(sel, dict):
        sel = {}
    sel[name.lower()] = bool(selected)
    cfg[key] = sel
    save_config(cfg)


def _addon_locked(name):
    """库插件 / 客户端前置，锁定必选、不允许取消勾选：
    - ! 开头：库插件（如 !Libs），被大量插件依赖
    - Blizzard_ 开头：客户端自带 UI 模块（插件包内同套 12 个）
    - Turtle_ 开头：乌龟服服务端 UI（.pub 结构）"""
    n = (name or "").strip().lower()
    return n.startswith(("!", "blizzard_", "turtle_"))


def normalize_addons_path(path, create=False):
    """用户随手输入的路径自动纠正为 AddOns 目录：
    - 已是 AddOns → 原样
    - Interface 目录 → 补 AddOns
    - 客户端根（有 Wow.exe 等）或任意目录 → 补 Interface/AddOns
    create=True 时若 Interface/AddOns 不存在则自动新建两级目录"""
    p = os.path.abspath(path.strip().strip('"'))
    if not os.path.isdir(p):
        # AddOns 目录本身不存在（清理还原后/全新客户端）→ create 时连同 Interface 一起新建
        if create and p.lower().endswith("addons"):
            try:
                os.makedirs(p, exist_ok=True)
                return p
            except Exception:
                return None
        return None
    low = os.path.basename(p).lower()
    if low == "addons":
        return p
    if low == "interface":
        sub = os.path.join(p, "AddOns")
        if os.path.isdir(sub):
            return sub
        if create:
            os.makedirs(sub, exist_ok=True)
            return sub
        return p
    exes = ("wow.exe", "vanillafixes.exe", "wowclassic.exe")
    try:
        entries = os.listdir(p)
    except Exception:
        return None
    sub = os.path.join(p, "Interface", "AddOns")
    if os.path.isdir(sub):
        return sub
    if create:
        os.makedirs(sub, exist_ok=True)
        return sub
    if any(e.lower() in exes for e in entries) \
            or "realmlist.wtf" in (e.lower() for e in entries):
        return p
    return p


def _to_root(p):
    """任意层路径 → 游戏根目录（含 WoW.exe 的那一层）。
    接受：根目录 / Interface / Interface/AddOns / WoW.exe 本身（文件路径自动取其所在文件夹），
    统一归一到根目录。config.target 与 UI 展示、打开目录一律用根目录。"""
    if not p:
        return ""
    p = os.path.normpath(str(p).strip().strip('"'))
    if not p:
        return ""
    low = p.lower().rstrip("\\")
    if low.endswith("\\interface\\addons"):
        return os.path.dirname(os.path.dirname(p))
    if low.endswith("\\interface"):
        return os.path.dirname(p)
    if os.path.basename(p).lower() == "addons":
        return os.path.dirname(os.path.dirname(p))
    # 选中的是 WoW.exe 等主程序文件 → 游戏根目录就是它所在的文件夹
    if os.path.isfile(p) or low.endswith(".exe"):
        return os.path.dirname(p)
    return p


def _to_addons(p):
    """任意层路径 → AddOns 目录（内部装卸链路统一契约）。
    客户端还没有 Interface 时也返回推导路径，由调用方负责创建/判错。"""
    root = _to_root(p)
    if not root:
        return ""
    return os.path.join(root, "Interface", "AddOns")


def _find_game_exe(root):
    """在游戏根目录里找主程序，返回完整路径（找不到返回空串）。"""
    if not root or not os.path.isdir(root):
        return ""
    root = os.path.normpath(root)
    for e in ("WoW.exe", "Wow.exe", "wow.exe", "WoWClassic.exe", "VanillaFixes.exe"):
        fp = os.path.join(root, e)
        if os.path.isfile(fp):
            return fp
    return ""


def _game_version(root):
    """读取客户端版本号（首页「当前客户端」显示用）。
    读主程序 exe 的文件版本；乌龟服系客户端（1.12 核心 + twloader.dll/patch-O.mpq
    特征文件）社区版本号是 1.18，按 1.18 显示；其余直接显示 exe 版本（如 3.3.5）。"""
    try:
        if sys.platform != "win32":
            return ""
        exe = _find_game_exe(root)
        if not exe:
            return ""
        import ctypes
        from ctypes import wintypes as wt
        size = ctypes.windll.version.GetFileVersionInfoSizeW(exe, None)
        if not size:
            return ""
        data = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(exe, 0, size, data):
            return ""
        val = ctypes.c_void_p()
        ln = wt.UINT()
        if not ctypes.windll.version.VerQueryValueW(
                data, "\\", ctypes.byref(val), ctypes.byref(ln)):
            return ""

        class _VFI(ctypes.Structure):
            _fields_ = [(n, wt.DWORD) for n in (
                "dwSignature", "dwStrucVersion", "dwFileVersionMS", "dwFileVersionLS",
                "dwProductVersionMS", "dwProductVersionLS", "dwFileFlagsMask",
                "dwFileFlags", "dwFileOS", "dwFileType", "dwFileSubtype",
                "dwFileDateMS", "dwFileDateLS")]

        f = ctypes.cast(val, ctypes.POINTER(_VFI)).contents
        ver = "%d.%d.%d" % (f.dwFileVersionMS >> 16, f.dwFileVersionMS & 0xFFFF,
                            f.dwFileVersionLS >> 16)
        root_n = os.path.normpath(root)
        has_mark = any(
            os.path.isfile(os.path.join(root_n, m))
            or os.path.isfile(os.path.join(root_n, "Data", m))
            for m in ("twloader.dll", "patch-O.mpq", "patch-O.MPQ"))
        if ver.startswith("1.12") and has_mark:
            return "1.18"
        return ver
    except Exception:
        return ""

import threading as _t
_local = _t.local()


def get_client():
    if not hasattr(_local, "client"):
        _local.client = LanzouClient()
    return _local.client


# ================= 游戏插件目录自动探测 =================

_TARGETS_CACHE = {"ts": 0.0, "list": []}


def find_addons_dirs():
    """扫描常见位置，找出所有 Interface/AddOns 目录（必须是魔兽客户端里的）。
    便携化：用户主目录用 expanduser（不写死用户名）；exe 所在目录/父目录优先扫
    （exe 放游戏根目录时秒级命中）。结果缓存 30 秒，避免 UI 反复打开重复全盘扫。"""
    global _TARGETS_CACHE
    now = time.time()
    if _TARGETS_CACHE["list"] and now - _TARGETS_CACHE["ts"] < 30:
        return list(_TARGETS_CACHE["list"])
    found = []
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else APP_DIR
    roots = [exe_dir, os.path.dirname(exe_dir),          # 便携：exe 在游戏根目录
             "D:/", "E:/", os.path.expanduser("~"), "C:/Games"]
    seen_roots, roots2 = set(), []
    for r in roots:
        r = os.path.normpath(r)
        if r not in seen_roots and os.path.isdir(r):
            seen_roots.add(r)
            roots2.append(r)
    roots = roots2
    wow_exes = ("wow.exe", "wowclassic.exe", "vanillafixes.exe", "wow.exe.bak")

    def walk(path, depth):
        if depth > 5 or len(found) > 12:
            return
        try:
            entries = os.listdir(path)
        except Exception:
            return
        lower = {e.lower(): e for e in entries}
        if "interface" in lower:
            iface = os.path.join(path, lower["interface"])
            if os.path.isdir(iface):
                try:
                    subs = os.listdir(iface)
                except Exception:
                    subs = []
                for s in subs:
                    if s.lower() == "addons":
                        addons = os.path.join(iface, s)
                        if os.path.isdir(addons) and addons not in found:
                            found.append(addons)
        if "addons" in lower and os.path.basename(path).lower() == "interface":
            addons = os.path.join(path, lower["addons"])
            if os.path.isdir(addons) and addons not in found:
                found.append(addons)
        # 客户端判定标志（有 WoW.exe 之类，或 Data/realmlist.wtf）
        client_marker = any(e.lower() in wow_exes for e in entries) \
            or "realmlist.wtf" in lower \
            or ("data" in lower and os.path.isdir(os.path.join(path, lower["data"])))
        has_iface = "interface" in lower
        if client_marker and has_iface:
            iface = os.path.join(path, "Interface", "AddOns")
            if os.path.isdir(iface) and iface not in found:
                found.append(iface)
            return  # 客户端目录下不必再深入
        # 有 Data 但没 Interface（如战网根目录）→ 继续深入子目录找 _classic_ 等
        for e in entries:
            p = os.path.join(path, e)
            if os.path.isdir(p) and not e.startswith(".") and e.lower() not in (
                    "windows", "appdata", "$recycle.bin", "system volume information"):
                walk(p, depth + 1)

    for r in roots:
        if os.path.isdir(r):
            walk(r, 1)

    # 按优先级排序：已知乌龟服路径优先
    def rank(p):
        low = p.lower().replace("\\", "/")
        if "twmoa" in low or "turtle" in low:
            return 0
        if "wow" in low or "魔兽" in low:
            return 1
        return 2
    found.sort(key=rank)
    _TARGETS_CACHE.update({"ts": time.time(), "list": list(found)})
    return found


# ================= 解压 =================

def _fix_zip_name(name):
    """处理 zip 中文文件名乱码（cp437 → gbk/utf-8）"""
    try:
        name.encode("cp437")
        # 能用 cp437 编码说明是未标注 UTF-8 标志的压缩包
        for enc in ("gbk", "utf-8"):
            try:
                fixed = name.encode("cp437").decode(enc)
                if fixed:
                    return fixed
            except Exception:
                continue
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return name


def find_extractor(archive_path):
    """rar/7z 优先用本机的 7-Zip 或 WinRAR"""
    ext = os.path.splitext(archive_path)[1].lower()
    if ext in (".rar", ".7z", ".cab", ".arj"):
        cands = [
            r"C:/Program Files/7-Zip/7z.exe",
            r"C:/Program Files (x86)/7-Zip/7z.exe",
            r"C:/Program Files/WinRAR/WinRAR.exe",
            r"C:/Program Files (x86)/WinRAR/WinRAR.exe",
        ]
        for c in cands:
            if os.path.isfile(c):
                return c
    return None


def extract_archive(archive_path, dest_dir, log):
    """解压到 dest_dir。返回 (成功, 消息)"""
    ext = os.path.splitext(archive_path)[1].lower()
    os.makedirs(dest_dir, exist_ok=True)

    tool = find_extractor(archive_path)
    if tool:
        log(f"[解压] 使用外部工具 {os.path.basename(tool)}")
        if "winrar" in tool.lower():
            cmd = [tool, "x", "-o+", archive_path, dest_dir + os.sep]
        else:
            cmd = [tool, "x", "-y", f"-o{dest_dir}", archive_path]
        r = _run_hidden(cmd, capture_output=True, timeout=600)
        if r.returncode == 0:
            return True, "ok"
        log(f"[解压] 外部工具失败 code={r.returncode}: {r.stderr.decode(errors='replace')[:200]}")
        return False, f"解压失败（{os.path.basename(tool)} 返回 {r.returncode}）"

    if ext == ".zip" or ext == "":
        try:
            log("[解压] 使用内置 zipfile")
            with zipfile.ZipFile(archive_path) as z:
                for info in z.infolist():
                    fixed = _fix_zip_name(info.filename)
                    target = os.path.join(dest_dir, *fixed.replace("\\", "/").split("/"))
                    # 防路径穿越
                    if not os.path.abspath(target).startswith(os.path.abspath(dest_dir)):
                        continue
                    if info.is_dir() or fixed.endswith("/"):
                        os.makedirs(target, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with z.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
            return True, "ok"
        except zipfile.BadZipFile:
            return False, "不是有效的 zip 文件（rar/7z 需要安装 7-Zip 或 WinRAR）"
        except Exception as e:
            return False, f"解压出错: {e}"

    return False, f"暂不支持的格式 {ext}（请安装 7-Zip 后重试）"


# ================= 插件安装 =================

def find_addon_roots(extract_dir):
    """在解压目录里找插件根目录（直接包含 .toc 文件的目录）"""
    roots = []
    for dirpath, dirnames, filenames in os.walk(extract_dir):
        tocs = [f for f in filenames if f.lower().endswith(".toc")]
        if tocs:
            if os.path.abspath(dirpath) == os.path.abspath(extract_dir):
                # .toc 直接在压缩包根 → 用压缩包名建目录（由调用方处理）
                roots.append(".")
            else:
                roots.append(dirpath)
    return roots


def install_from_extracted(extract_dir, addons_dir, log):
    """把解压出来的插件装进 AddOns。返回 (安装数, 详情列表)"""
    roots = find_addon_roots(extract_dir)
    details = []
    if not roots:
        return 0, details

    # 压缩包根就是插件根（.toc 在顶层）→ 打包整个目录
    wrap_name = None
    if roots == ["."]:
        wrap_name = os.path.basename(extract_dir).replace("_extract", "_addon") or "AddonPack"
        roots = [extract_dir]

    backup_dir = os.path.join(backups_base(addons_dir), "_备份_" + time.strftime("%Y%m%d_%H%M%S"))
    n = 0
    for src in roots:
        name = os.path.basename(src)
        if wrap_name:
            name = wrap_name
        if name.lower() == "addons":
            continue
        dst = os.path.join(addons_dir, name)
        try:
            if os.path.exists(dst):
                os.makedirs(backup_dir, exist_ok=True)
                bak = os.path.join(backup_dir, name)
                if os.path.exists(bak):
                    _to_trash(bak)
                shutil.move(dst, bak)
                log(f"[备份] 旧版 {name} → _备份_{os.path.basename(backup_dir)[3:]}")
            if wrap_name or True:
                shutil.copytree(src, dst, dirs_exist_ok=True)
                if not wrap_name:
                    discard_dir(src)
            details.append(name)
            n += 1
            log(f"[安装] {name} ✓")
        except Exception as e:
            log(f"[安装失败] {name}: {e}")
    return n, details


def list_installed_addons(addons_dir):
    """列出已安装插件（AddOns 下全部目录条目）。
    乌龟服的 Blizzard_*/Turtle_* 用 .pub 而非 .toc，同样是有效插件，一并收录。"""
    result = []
    if not addons_dir or not os.path.isdir(addons_dir):
        return result
    for e in sorted(os.listdir(addons_dir)):
        p = os.path.join(addons_dir, e)
        if not os.path.isdir(p) or e.startswith("_"):
            continue
        # .toc 和 .pub 都算插件标识（乌龟服 Blizzard/Turtle 系用 .pub）
        tocs = [f[:-4] for f in os.listdir(p) if f.lower().endswith(".toc")]
        pubs = [f[:-4] for f in os.listdir(p) if f.lower().endswith(".pub")]
        ids = tocs or pubs
        if not ids:
            continue
        # 读主 toc 的 ## Title / ## Version
        title, ver = "", ""
        try:
            with open(os.path.join(p, ids[0] + (".toc" if tocs else ".pub")), "r", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    m = re.match(r"##\s*Title\s*:\s*(.*)", line, re.I)
                    if m and not title:
                        title = m.group(1)
                    m = re.match(r"##\s*Version\s*:\s*(.*)", line, re.I)
                    if m and not ver:
                        ver = m.group(1)
                    if title and ver:
                        break
        except Exception:
            pass
        result.append({"dir": e, "tocs": tocs, "pubs": pubs, "title": title, "version": ver})
    return result


# ================= 下载 =================

def download_file(link, dest_dir, log, progress_cb=None):
    """下载直链，返回本地路径或 None"""
    os.makedirs(dest_dir, exist_ok=True)
    name = urllib.parse.urlsplit(link).path.split("/")[-1] or "download.bin"
    name = urllib.parse.unquote(name)
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    path = os.path.join(dest_dir, name)
    base, ext = os.path.splitext(path)
    if ext.lower() not in (".zip", ".rar", ".7z"):
        path = base + ext
    try:
        req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(done, total)
        log(f"[下载完成] {os.path.basename(path)} ({done/1048576:.1f} MB)")
        return path
    except Exception as e:
        log(f"[下载失败] {e}")
        if os.path.exists(path):
            os.remove(path)
        return None


# ================= 游戏启动器 =================

GITEE_ADDONS_URL = "https://gitee.com/apple-music/addons/repository/archive/master.zip"
TEXTURE_DIRS = ("CastingBar", "TargetingFrame")  # 包内的贴图美化目录


def install_textures(pkg_root, addons_dir, backup_dir, log):
    """把包里的贴图美化（.blp）装到客户端根目录，被覆盖的原版贴图先备份"""
    client_root = client_root_of(addons_dir)
    n, new_files = 0, []
    for d in TEXTURE_DIRS:
        src = os.path.join(pkg_root, d)
        if not os.path.isdir(src):
            continue
        for dirpath, dirnames, filenames in os.walk(src):
            rel = os.path.relpath(dirpath, src)
            dst_dir = os.path.join(client_root, d) if rel == "." else os.path.join(client_root, d, rel)
            os.makedirs(dst_dir, exist_ok=True)
            for f in filenames:
                dst = os.path.join(dst_dir, f)
                src_f = os.path.join(dirpath, f)
                if os.path.exists(dst):
                    # 先备份原版贴图（保留相对路径），卸载时还原
                    bdir = os.path.join(backup_dir, d, rel)
                    os.makedirs(bdir, exist_ok=True)
                    bak = os.path.join(bdir, f)
                    if not os.path.exists(bak):
                        shutil.copy2(dst, bak)
                else:
                    new_files.append(os.path.join(d, rel, f).replace("\\", "/"))
                shutil.copy2(src_f, dst)
                n += 1
    if n:
        # 记录"原版没有、由本包新增"的贴图，卸载时删除
        os.makedirs(backup_dir, exist_ok=True)
        with open(os.path.join(backup_dir, "_安装清单.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(new_files))
        log(f"[贴图] 安装 {n} 个美化贴图到客户端（原版已备份到本次备份文件夹的 _贴图 里）")
    return n


def client_root_of(addons_dir):
    """AddOns → Interface → 客户端根目录"""
    return os.path.dirname(os.path.dirname(os.path.abspath(addons_dir)))


def backups_base(addons_dir):
    """备份基目录：游戏目录下的 WowAbak 文件夹（总备份夹，模组/插件/字体各一个子文件夹，
    与游戏文件分开，不混进 AddOns）"""
    return os.path.join(client_root_of(addons_dir), "WowAbak")


# ---------- 内置模组注入器：彻底取代 VanillaFixes.exe（游戏根目录零释放）----------
# 结论来自 2026-10-26 的逆向 + 隔离实测：
#   * VanillaFixes.exe 用【自己所在目录】找 WoW.exe（放别处直接弹 "WoW.exe not
#     found. Extract VanillaFixes into the same directory as the game."），
#     所以"把它挪到别的目录运行"这条路走不通。
#   * 但它真正不可替代的活儿只有一件：在游戏进程里加载 VfPatcher.dll +
#     nampower.dll。Logs\twloader.log 是铁证——其余 7 个模组 DLL 由【游戏客户端
#     自带的 twloader.dll】读 dlls.txt 加载（"Loaded: xxx"），只有 VfPatcher 与
#     nampower 显示 "Already loaded"，即必须在游戏初始化极早期由外部注入。
#   * 因此：我们启动 WoW.exe 后立刻注入这两个 DLL，VanillaFixes.exe 就完全没有
#     存在必要，游戏根目录再也不需要出现它 —— 这正是最终目标。
# 三个实测踩过的坑（改动前务必读）：
#   1) 挂起态（CREATE_SUSPENDED）【注入必失败】：此时进程用户态未初始化，模块
#      列表为空，LoadLibraryW 返回 0 且 GetLastError 也是 0。已用带 magic 标记的
#      shellcode 验证过——代码确实执行了，是 Windows loader 拒绝加载。所以必须
#      【正常启动、等 kernel32 出现后】再注入。
#   2) LoadLibraryW 地址 = 目标进程内 32 位 kernel32 基址 + RVA。RVA 通过解析
#      SysWOW64\kernel32.dll 的导出表获得。系统 DLL 基址在同一台机器上全局一致
#      （实测多个 32 位进程都是 0x76370000），这里仍以目标进程枚举值为准。
#   3) 【不要用线程退出码判断注入成败】——实测退出码读到 0，DLL 其实已加载。
#      必须查目标进程的模块列表。
# 容错：即便注入失败也不致命，游戏已正常启动，twloader 会按 dlls.txt 兜底加载
#       其余模组（仅计时器修复可能偏晚），所以这里只记日志、不阻断启动。
INJECT_DLLS = ("VfPatcher.dll", "nampower.dll")


_WIN32 = {}


def _win32():
    """惰性取 kernel32 / psapi，并固定指针类型。
    必须显式声明：VirtualAllocEx 返回的地址可能 >= 0x80000000，默认会被解释成
    负数，再传给 CreateRemoteThread 会被符号扩展成无效地址。"""
    if "k" not in _WIN32:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                     ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
        k.VirtualAllocEx.restype = ctypes.c_void_p
        k.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                         ctypes.c_void_p, ctypes.c_size_t,
                                         ctypes.POINTER(ctypes.c_size_t)]
        k.WriteProcessMemory.restype = wintypes.BOOL
        k.CreateRemoteThread.restype = wintypes.HANDLE
        k.OpenProcess.restype = wintypes.HANDLE
        _WIN32["k"] = k
        _WIN32["ps"] = ctypes.WinDLL("psapi", use_last_error=True)
    return _WIN32["k"], _WIN32["ps"]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


def _pe_export_rva(dll, func):
    """解析 PE 导出表取指定函数的 RVA（失败返回 None）。"""
    try:
        with open(dll, "rb") as f:
            b = f.read()
        pe = struct.unpack_from("<I", b, 0x3C)[0]
        if b[pe:pe + 4] != b"PE\0\0":
            return None
        nsec = struct.unpack_from("<H", b, pe + 6)[0]
        szopt = struct.unpack_from("<H", b, pe + 20)[0]
        opt = pe + 24
        is64 = struct.unpack_from("<H", b, opt)[0] == 0x20B
        secs, so = [], opt + szopt
        for i in range(nsec):
            o = so + i * 40
            vs, va, rs, ra = struct.unpack_from("<IIII", b, o + 8)
            secs.append((va, max(vs, rs), ra))

        def r2o(rva):
            for va, sz, ra in secs:
                if va <= rva < va + sz:
                    return ra + (rva - va)
            return None

        dd = opt + (112 if is64 else 96)
        exp_rva, _ = struct.unpack_from("<II", b, dd)
        o = r2o(exp_rva) if exp_rva else None
        if not o:
            return None
        nfun, nnam = struct.unpack_from("<II", b, o + 20)
        add_rva, nam_rva, ord_rva = struct.unpack_from("<III", b, o + 28)
        base_ord = struct.unpack_from("<I", b, o + 16)[0]
        no, ao, oo = r2o(nam_rva), r2o(add_rva), r2o(ord_rva)
        if not (no and ao and oo):
            return None
        for i in range(min(nnam, 4096)):
            nr = struct.unpack_from("<I", b, no + i * 4)[0]
            fo = r2o(nr)
            if fo is None:
                continue
            end = b.find(b"\x00", fo)
            if end > 0 and b[fo:end].decode("latin1", "ignore") == func:
                idx = struct.unpack_from("<H", b, oo + i * 2)[0] - base_ord
                return struct.unpack_from("<I", b, ao + idx * 4)[0]
    except Exception:
        return None
    return None


def _proc_alive(hproc):
    """目标进程是否还活着（WaitForSingleObject 超时=0 表示已结束）。"""
    try:
        k, ps = _win32()
        return k.WaitForSingleObject(hproc, 0) != 0
    except Exception:
        return False


def _syswow_kernel32():
    """32 位 kernel32.dll 的文件路径（用来解析 LoadLibraryW 的 RVA）。"""
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    p = os.path.join(root, "SysWOW64", "kernel32.dll")
    if os.path.isfile(p):
        return p
    p2 = os.path.join(root, "System32", "kernel32.dll")
    return p2 if os.path.isfile(p2) else None


def _modules32(hproc):
    """目标进程的 32 位模块表 {小写名: 基址}；空 dict = 尚未初始化或读取失败。"""
    k, ps = _win32()
    mods = (wintypes.HMODULE * 2048)()
    need = wintypes.DWORD(0)
    if not ps.EnumProcessModulesEx(hproc, ctypes.byref(mods), ctypes.sizeof(mods),
                                   ctypes.byref(need), 0x01):
        return {}
    out = {}
    n = min(need.value // ctypes.sizeof(wintypes.HMODULE), 2048)
    for i in range(n):
        nm = ctypes.create_unicode_buffer(260)
        ps.GetModuleBaseNameW(hproc, mods[i], nm, 260)
        if nm.value:
            out[nm.value.lower()] = (mods[i] or 0) & 0xFFFFFFFF
    return out


def _inject_dll(hproc, dll_path, llw_addr, timeout=15.0):
    """把单个 DLL 注入目标进程，返回 (ok, msg)。
    成功判据是【模块列表里出现该 DLL】——线程退出码实测不可靠（读到 0 却已加载）。"""
    k, ps = _win32()
    name = os.path.basename(dll_path).lower()
    try:
        if name in _modules32(hproc):
            return True, "已加载"
        data = dll_path.encode("utf-16-le") + b"\x00\x00"
    except Exception as e:
        return False, "预处理失败：" + str(e)
    ra = k.VirtualAllocEx(hproc, None, len(data), 0x3000, 0x04)
    if not ra:
        return False, "VirtualAllocEx 失败(%d)" % ctypes.get_last_error()
    wn = ctypes.c_size_t(0)
    if not k.WriteProcessMemory(hproc, ctypes.c_void_p(ra), data,
                                len(data), ctypes.byref(wn)):
        return False, "WriteProcessMemory 失败(%d)" % ctypes.get_last_error()
    tid = wintypes.DWORD(0)
    th = k.CreateRemoteThread(hproc, None, 0, ctypes.c_void_p(llw_addr),
                              ctypes.c_void_p(ra), 0, ctypes.byref(tid))
    if not th:
        return False, "CreateRemoteThread 失败(%d)" % ctypes.get_last_error()
    k.WaitForSingleObject(th, int(timeout * 1000))
    k.CloseHandle(th)
    t0 = time.time()
    while time.time() - t0 < 3.0:      # LoadLibrary 返回后模块表才刷新
        if name in _modules32(hproc):
            return True, "注入成功"
        time.sleep(0.05)
    return False, "未出现在游戏进程中"


def _inject_after_launch(pid, dlls, log=None, wait_sec=20.0):
    """游戏进程已启动：等它初始化完成后注入模组加载器 DLL（在后台线程里跑）。
    用 pid 重新打开进程句柄。最坏持续 wait_sec 秒，绝不阻塞界面。"""
    def _say(msg):
        try:
            (log or _log_wv)("[模组] " + msg)
        except Exception:
            pass
    if sys.platform != "win32":
        return
    k, ps = _win32()
    h = k.OpenProcess(0x1F0FFF, False, pid)
    if not h:
        _say("⚠ 打不开游戏进程，跳过注入；模组由客户端自行加载")
        return
    try:
        # ① 等游戏进程完成用户态初始化（kernel32 出现 = loader 就绪）
        base, t0 = None, time.time()
        while time.time() - t0 < wait_sec:
            base = _modules32(h).get("kernel32.dll")
            if base:
                break
            if not _proc_alive(h):       # 游戏已经退出了，别再白等
                _say("游戏进程已退出，跳过注入")
                return
            time.sleep(0.03)
        if not base:
            _say("⚠ 未等到 kernel32 就位，跳过注入（模组由客户端自行加载）")
            return
        # ② 算出 LoadLibraryW 在目标进程里的地址
        rva = _pe_export_rva(_syswow_kernel32(), "LoadLibraryW")
        if not rva:
            _say("⚠ 解析 LoadLibraryW 失败，跳过注入（模组由客户端自行加载）")
            return
        llw = base + rva
        # ③ 持续重试：早期失败常因游戏还没初始化到位；也可能随后被客户端自己的
        #    twloader.dll 加载（_inject_dll 会识别"已加载"，同样算达成目标）
        deadline = time.time() + wait_sec
        pending = list(dlls)
        while pending and time.time() < deadline:
            still = []
            for d in pending:
                okd, msg = _inject_dll(h, d, llw, timeout=8.0)
                if okd:
                    _say("%s 已载入（%s）✓" % (os.path.basename(d), msg))
                else:
                    still.append(d)
            pending = still
            if not pending:
                break
            if not _proc_alive(h):       # 游戏已退出，停止重试
                _say("游戏进程已退出，停止注入重试")
                break
            time.sleep(0.8)
        if pending:
            _say("⚠ 未注入成功：" + "、".join(os.path.basename(d) for d in pending)
                 + " —— 游戏正常运行，其余模组仍由客户端按 dlls.txt 加载")
        else:
            _say("内置注入器已就绪（游戏目录无需 VanillaFixes.exe）")
    finally:
        try:
            k.CloseHandle(h)
        except Exception:
            pass


def launch_game(addons_dir):
    """启动游戏。
    装了模组 → 内置注入器把 VfPatcher.dll / nampower.dll 注入游戏进程，游戏
    根目录因此【不再需要 VanillaFixes.exe】；没装模组 → 直接启动 WoW.exe。
    必须 cwd=客户端根目录（等同资源管理器双击）：twloader 与其余模组 DLL 都按
    相对路径 LoadLibrary，工作目录不对会解析不到文件。"""
    root = client_root_of(addons_dir)
    exe = None
    for n in ("WoW.exe", "Wow.exe", "wow.exe", "WowClassic.exe"):
        p = os.path.join(root, n)
        if os.path.isfile(p):
            exe = p
            break
    if not exe:
        return False, root

    # —— 3.20 加密账号落地：把账号/密码注入本次启动 ——
    # ① 命令行 -account/-password（标准 1.12/乌龟服客户端支持，直接自动登录）；
    # ② 若客户端自带 Imports 账号记忆功能（参考水豚/参考客户端的“账号密码记忆”，
    #    格式 "账号 密码;"，写 Imports/accountName.txt），两栏都会填上。
    # 明文密码只在内存里解密，用完即丢；仅当客户端已有 Imports 目录才写该文件，
    # 避免在无此功能的客户端游戏目录里留下明文密码文件。
    cred_args = []
    try:
        acc = _load_account()
        if acc.get("has") and acc.get("user"):
            u = acc["user"]
            pw = acc.get("pwd") or ""
            cred_args = ["-account", u]
            if pw:
                cred_args += ["-password", pw]
                try:
                    imp_dir = os.path.join(root, "Imports")
                    if os.path.isdir(imp_dir):
                        with open(os.path.join(imp_dir, "accountName.txt"),
                                  "w", encoding="utf-8") as _f:
                            _f.write(f"{u} {pw};")
                except Exception:
                    pass
        else:
            # 未记住账号 → 清掉客户端里可能残留的记忆文件
            try:
                _stale = os.path.join(root, "Imports", "accountName.txt")
                if os.path.isfile(_stale):
                    os.remove(_stale)
            except Exception:
                pass
    except Exception:
        cred_args = []

    inject = [os.path.join(root, n) for n in INJECT_DLLS]
    inject = [p for p in inject if os.path.isfile(p)]
    if not inject or sys.platform != "win32":
        try:
            _popen_hidden([exe] + cred_args, cwd=root)
        except Exception:
            try:
                _popen_hidden([exe] + cred_args)
            except Exception:
                pass
        return True, exe
    # 同步把游戏拉起来（很快），注入交给后台线程：界面立刻响应，而后台线程从
    # 进程创建那一刻就开始等初始化，注入时机依然足够早。
    k, ps = _win32()
    si = _STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = _PROCESS_INFORMATION()
    # CREATE_NO_WINDOW：对 WoW.exe 这类 GUI 程序无影响，只防控制台类程序弹黑窗。
    # 命令行需含 exe 路径作首 token；账号/密码可能含空格，统一加引号。
    cmdline = '"' + exe + '"'
    for _a in cred_args:
        cmdline += ' "' + _a + '"'
    if k.CreateProcessW(None, cmdline, None, None, False, 0x08000000, None, root,
                        ctypes.byref(si), ctypes.byref(pi)):
        pid = pi.dwProcessId
        try:
            k.CloseHandle(pi.hThread)
            k.CloseHandle(pi.hProcess)
        except Exception:
            pass
        threading.Thread(target=_inject_after_launch, daemon=True,
                         args=(pid, inject)).start()
        return True, exe
    # 兜底：CreateProcess 失败就退回子进程封装，保证游戏一定能开
    try:
        _popen_hidden([exe] + cred_args, cwd=root)
    except Exception:
        try:
            _popen_hidden([exe] + cred_args)
        except Exception:
            pass
    return True, exe


def read_realmlist(addons_dir):
    """读取 realmlist.wtf，让用户知道当前连的服务器"""
    p = os.path.join(client_root_of(addons_dir), "realmlist.wtf")
    if os.path.isfile(p):
        try:
            with open(p, "r", errors="replace") as f:
                return f.read().strip()
        except Exception:
            return ""
    return ""


def _to_trash(path):
    """把目录/文件瞬间挪进回收区（单次改名），不阻塞；由后台线程慢慢删"""
    trash = os.path.join(TEMP_DIR, "trash")
    os.makedirs(trash, exist_ok=True)
    dst = os.path.join(trash, time.strftime("%H%M%S") + f"_{os.getpid() % 10000}"
                      + os.path.basename(path).replace(" ", "_")[:30])
    try:
        os.rename(path, dst)
    except OSError:
        try:
            shutil.move(path, dst)
        except OSError:
            return False
    _bg_rmtree(dst)
    return True


def _bg_rmtree(path):
    """后台线程慢速删除（不阻塞主流程）"""
    def _worker():
        shutil.rmtree(path, ignore_errors=True)
    threading.Thread(target=_worker, daemon=True).start()


def discard_dir(path):
    """瞬间"删除"：先把目录改名挪进回收区（单次 rename），再由后台线程慢慢删"""
    if not os.path.isdir(path):
        return
    if not _to_trash(path):
        _bg_rmtree(path)


def safe_rmtree(path):
    """兼容旧调用：丢弃目录（改入回收区+后台删除，不阻塞）"""
    discard_dir(path)


class TempDir:
    """临时目录（退出时挪进回收区，由后台线程清理，不阻塞请求）"""

    def __init__(self, base=None):
        self.base = base or TEMP_DIR
        self.path = None

    def __enter__(self):
        os.makedirs(self.base, exist_ok=True)
        self.path = tempfile.mkdtemp(prefix="tmp_", dir=self.base)
        return self.path

    def __exit__(self, *exc):
        discard_dir(self.path)
        return False


def install_from_gitee_zip(zip_path, addons_dir, log):
    """安装 Gitee 黑猫插件包（包内结构: xxx-master/AddOns/<插件目录>...）"""
    with TempDir() as td:
        ok, msg = extract_archive(zip_path, td, log)
        if not ok:
            log(f"[失败] {msg}")
            return 0, []
        # 找包内的 AddOns 目录
        src = None
        for dirpath, dirnames, filenames in os.walk(td):
            if os.path.basename(dirpath).lower() == "addons":
                src = dirpath
                break
        if not src:
            log("[失败] 插件包里没找到 AddOns 目录")
            return 0, []

        backup_dir = os.path.join(backups_base(addons_dir), "_备份_" + time.strftime("%Y%m%d_%H%M%S"))
        n, details = 0, []
        for e in sorted(os.listdir(src)):
            p = os.path.join(src, e)
            if not os.path.isdir(p):
                continue
            tocs = [f for f in os.listdir(p) if f.lower().endswith(".toc")]
            if not tocs:
                continue
            dst = os.path.join(addons_dir, e)
            try:
                if os.path.exists(dst):
                    os.makedirs(backup_dir, exist_ok=True)
                    bak = os.path.join(backup_dir, e)
                    if os.path.exists(bak):
                        _to_trash(bak)
                    shutil.move(dst, bak)
                shutil.copytree(p, dst, dirs_exist_ok=True)
                details.append(e)
                n += 1
            except Exception as ex:
                log(f"[安装失败] {e}: {ex}")
        if n:
            log(f"[安装] 共装好 {n} 个插件")
        # 贴图美化（备份放在插件目录的本次备份文件夹里，卸载时用于还原）
        tex_backup = os.path.join(backup_dir, "_贴图")
        install_textures(os.path.dirname(src), addons_dir, tex_backup, log)
        return n, details


def uninstall_all_addons(addons_dir, log):
    """一键清空插件：全部直接删除（不备份，与「移除字体」同规则），
    并还原被贴图美化覆盖的原版贴图。返回 (移除数)"""
    client_root = client_root_of(addons_dir)
    removed = 0
    # 只删资源包里的（本程序装入的）；非资源包内容（用户自装）保留
    pack_names = set()
    try:
        _psrc = _kind_dst("addons")
        if _psrc and os.path.isdir(_psrc):
            pack_names = {e.lower() for e in os.listdir(_psrc)
                          if os.path.isdir(os.path.join(_psrc, e))}
    except Exception:
        pass
    for e in os.listdir(addons_dir):
        if e.startswith("_备份_") or e.startswith("_贴图备份_"):
            continue
        if pack_names and e.lower() not in pack_names:
            log(f"[跳过] {e}（非资源包内容，保留）")
            continue
        src = os.path.join(addons_dir, e)
        if _fast_delete(src):
            removed += 1
            log(f"[移除] {e}（直接删除）")
        else:
            log(f"[移除失败] {e}")
    if removed:
        log(f"[清空] {removed} 项已直接删除（不备份）")

    # 还原原版贴图（取最新一次含贴图备份的备份文件夹），并删除本包新增的贴图
    tex_baks = []
    bbase = backups_base(addons_dir)
    if os.path.isdir(bbase):
        for d in os.listdir(bbase):
            if d.startswith("_备份_") and os.path.isdir(os.path.join(bbase, d, "_贴图")):
                tex_baks.append(os.path.join(bbase, d, "_贴图"))
    # 兼容旧版：贴图备份在客户端根目录
    for d in os.listdir(client_root):
        if d.startswith("_贴图备份_"):
            tex_baks.append(os.path.join(client_root, d))
    tex_baks.sort()
    restored = 0
    if tex_baks:
        latest = tex_baks[-1]
        bak_root = os.path.dirname(latest)
        # 1) 删除安装清单里"新增"的贴图
        manifest = os.path.join(latest, "_安装清单.txt")
        if os.path.isfile(manifest):
            with open(manifest, "r", encoding="utf-8") as f:
                for rel in f.read().splitlines():
                    rel = rel.strip()
                    if not rel:
                        continue
                    p = os.path.join(client_root, *rel.split("/"))
                    if os.path.isfile(p):
                        os.remove(p)
                        restored += 1
        # 2) 还原被覆盖的原版贴图
        for dirpath, dirnames, filenames in os.walk(latest):
            rel = os.path.relpath(dirpath, latest)
            if rel.startswith("_安装清单"):
                continue
            for f in filenames:
                if f == "_安装清单.txt":
                    continue
                dst = os.path.join(client_root, rel, f) if rel != "." else os.path.join(client_root, f)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(dirpath, f), dst)
                restored += 1
        # 删除已还原的贴图备份（_贴图 子文件夹）；若所在备份文件夹已空，也一并清掉
        safe_rmtree(latest)
        parent = os.path.dirname(latest)
        if os.path.basename(parent).startswith("_备份_") and os.path.isdir(parent) \
                and not os.listdir(parent):
            os.rmdir(parent)
    if restored:
        log(f"[贴图] 已还原 {restored} 个原版贴图")
    # 恢复客户端原有（非资源包）插件，然后删除该备份
    _restore_original_backup(addons_dir, "插件备份", addons_dir, log)
    # 空目录收尾：AddOns 清空后，连同 Interface 空目录一并删除（客户端原本没有该目录的场景）
    if os.path.isdir(addons_dir) and not os.listdir(addons_dir):
        _fast_delete(addons_dir)
        log("[清空] 插件目录已空，AddOns 一并移除")
        iface = os.path.dirname(addons_dir)
        if os.path.isdir(iface) and not os.listdir(iface):
            _fast_delete(iface)
            log("[清空] 空目录 Interface 一并移除")
    return removed


def uninstall_one(addons_dir, name, log):
    """移除单个插件（直接删除，不备份）"""
    safe = os.path.basename(name)  # 防路径穿越
    src = os.path.join(addons_dir, safe)
    if not os.path.isdir(src):
        return False, "插件不存在"
    try:
        if _fast_delete(src):
            log(f"[移除] {safe}（直接删除）")
            return True, "已移除"
        return False, "删除失败"
    except Exception as ex:
        return False, str(ex)


def find_local_packages():
    """找本机已有的插件包压缩包（游戏目录 + 下载目录）"""
    found = []
    import glob
    for pat in (os.path.join(DOWNLOAD_DIR, "*.zip"),
                os.path.join(DOWNLOAD_DIR, "*.rar"),
                os.path.join(DOWNLOAD_DIR, "*.7z")):
        for p in glob.glob(pat):
            if not os.path.isfile(p):
                continue
            # zip 必须校验文件头，防止把残缺下载文件当好包
            if p.lower().endswith(".zip") and not _is_valid_zip(p):
                continue
            if not p.lower().endswith(".zip") and os.path.getsize(p) < 1024 * 1024:
                continue
            found.append(p)
    # 按修改时间新→旧
    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return found


def backup_and_clear(addons_dir, log):
    """安装前：把现有全部插件备份并清空 AddOns。
    备份存到游戏目录的 WowAbak/_备份_时间_安装前（与游戏文件分开，可捞回）"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(backups_base(addons_dir), "_备份_" + ts + "_安装前")
    os.makedirs(backup_dir, exist_ok=True)
    moved = 0
    for e in os.listdir(addons_dir):
        if e.startswith("_备份_") or e.startswith("_贴图备份_"):
            continue
        src = os.path.join(addons_dir, e)
        try:
            shutil.move(src, os.path.join(backup_dir, e))
            moved += 1
        except Exception as ex:
            log(f"[备份失败] {e}: {ex}")
    if moved:
        log(f"[备份] 原有 {moved} 项插件已备份到 WowAbak\\_备份_{ts}_安装前 并从插件目录清空")
    return moved


def _is_valid_zip(path):
    try:
        if os.path.getsize(path) < 1024 * 1024:
            return False
        with open(path, "rb") as f:
            return f.read(2) == b"PK"
    except OSError:
        return False


def _curl_download(url, dest, timeout, log):
    """用系统自带的 curl 下载（绕过码云对 Python 请求的反爬页面）"""
    import subprocess
    exe = "curl" if sys.platform != "win32" else r"C:\Windows\System32\curl.exe"
    if not os.path.isfile(exe):
        exe = "curl"
    r = _run_hidden(
        [exe, "-sL", "--max-time", str(timeout), "--retry", "2",
         "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
         url, "-o", dest],
        capture_output=True)
    return r.returncode == 0 and os.path.isfile(dest) and _is_valid_zip(dest)


def download_gitee_zip(log, timeout=300, retries=2):
    """从 Gitee 下载最新插件包，带重试；成功返回本地路径。
    下载先写临时文件，校验通过（PK 头 + 大于 1MB）才转正，避免残缺包覆盖好包。"""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    dest = os.path.join(DOWNLOAD_DIR, "wowassist_插件包_Gitee最新.zip")
    part = dest + ".part"
    if os.path.exists(dest) and not _is_valid_zip(dest):
        log("[清理] 发现上次残留的损坏包，已删除")
        try:
            os.remove(dest)
        except OSError:
            pass
    for attempt in range(1, retries + 1):
        log(f"[下载] 第 {attempt}/{retries} 次尝试，从码云官方镜像下载（约 32MB，最长等 {timeout} 秒）...")
        try:
            req = urllib.request.Request(GITEE_ADDONS_URL, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "*/*",
                "Referer": "https://gitee.com/apple-music/addons"})
            with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
                while True:
                    chunk = r.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
            if not _is_valid_zip(part):
                raise IOError(f"下载内容不是有效的插件包（{os.path.getsize(part)} 字节，疑似反爬页面）")
            os.replace(part, dest)
            log(f"[下载完成] {os.path.getsize(dest)/1048576:.1f} MB")
            return dest
        except Exception as e:
            log(f"[下载失败] 直连方式: {e}")
            if _curl_download(GITEE_ADDONS_URL, part, timeout, log):
                os.replace(part, dest)
                log(f"[下载完成] （curl 方式）{os.path.getsize(dest)/1048576:.1f} MB")
                return dest
            log("[下载失败] curl 方式也未成功")
            try:
                if os.path.exists(part):
                    os.remove(part)
            except OSError:
                pass
            time.sleep(1)
    return None


def _restore_backup(addons_dir, backup_dir):
    """安装失败时把备份的原插件放回 AddOns"""
    n = 0
    for e in os.listdir(backup_dir):
        if e == "_贴图" or e.startswith("_安装清单"):
            continue
        src = os.path.join(backup_dir, e)
        if os.path.isdir(src) and not os.path.exists(os.path.join(addons_dir, e)):
            shutil.move(src, os.path.join(addons_dir, e))
            n += 1
    return n


def install_local_pkg(addons_dir, log):
    """从本机已有的插件包安装：备份清空现有插件 → 找本地包 → 安装（不联网）。
    本地没有包时自动还原备份，不把插件目录留空。"""
    n_moved = backup_and_clear(addons_dir, log)
    backup_dir = None
    if n_moved:
        cands = sorted(d for d in os.listdir(backups_base(addons_dir)) if d.startswith("_备份_"))
        if cands:
            backup_dir = os.path.join(addons_dir, cands[-1])
    local = find_local_packages()
    if not local:
        log("[提示] 本机没有插件包（已查 D:/game 和 downloads 目录），未做任何改动")
        if backup_dir:
            _restore_backup(addons_dir, backup_dir)
            log(f"[还原] 已把 {n_moved} 项原插件放回，目录恢复原样")
        return 0, []
    log(f"[发现] {len(local)} 个本地插件包，使用最新的: {os.path.basename(local[0])}")
    n, details = install_from_gitee_zip(local[0], addons_dir, log)
    return n, details


def install_addons_from_interface(src_iface, addons_dir, log):
    """按插件包作者方式整体替换：备份清空现有插件 → 把 src_iface/AddOns 全部拷入。
    src_iface 可指向插件包的 Interface 目录（推荐）、其下 AddOns、或客户端根。
    author 明确要求：必须整体替换，不要覆盖混装（避免旧版残留文件冲突）。"""
    if not src_iface or not os.path.isdir(src_iface):
        log("[失败] 插件包目录不存在：" + str(src_iface))
        return 0, []
    base = os.path.basename(src_iface.rstrip("\\/")).lower()
    if base == "addons":
        addons_src = src_iface
    elif os.path.isdir(os.path.join(src_iface, "AddOns")):
        addons_src = os.path.join(src_iface, "AddOns")
    elif os.path.isdir(os.path.join(src_iface, "Interface", "AddOns")):
        addons_src = os.path.join(src_iface, "Interface", "AddOns")
    else:
        log("[失败] 该目录下没找到 AddOns，请指向插件包的 Interface 文件夹")
        return 0, []
    # 1) 备份并清空现有插件（作者要求整体替换）
    n_moved = backup_and_clear(addons_dir, log)
    backup_dir = None
    if n_moved:
        cands = sorted(d for d in os.listdir(backups_base(addons_dir)) if d.startswith("_备份_"))
        if cands:
            backup_dir = os.path.join(backups_base(addons_dir), cands[-1])
    # 2) 拷入新插件（跳过 _ 开头的内部目录；按插件页勾选过滤，库/客户端前置锁定必装）
    sel = _get_selection("addons")
    names = [e for e in sorted(os.listdir(addons_src))
             if os.path.isdir(os.path.join(addons_src, e)) and not e.startswith("_")]
    installable = [n for n in names if _addon_locked(n) or sel.get(n.lower(), True)]
    n_skip = len(names) - len(installable)
    if n_skip:
        log("[插件] 按勾选跳过 " + str(n_skip) + " 个未勾选插件（未丢失，重新勾选可装回）")
    n, details = 0, []
    for name in installable:
        src = os.path.join(addons_src, name)
        dst = os.path.join(addons_dir, name)
        try:
            shutil.copytree(src, dst, dirs_exist_ok=True)
            details.append(name)
            n += 1
        except Exception as e:
            log("[安装失败] " + name + ": " + str(e))
    if n == 0 and backup_dir:
        _restore_backup(addons_dir, backup_dir)
        log("[还原] 新包为空，已放回原插件")
        return 0, []
    log("[完成] 已整体替换：装入 " + str(n) + " 个插件（原有 " + str(n_moved) + " 项已备份，可去 WowAbak 捞回）")
    return n, details


def install_online(addons_dir, log):
    """联网安装：备份清空现有插件 → 从码云下载最新包 → 安装。
    下载失败自动改用本机已有的包；再不行还原备份。"""
    n_moved = backup_and_clear(addons_dir, log)
    backup_dir = None
    if n_moved:
        cands = sorted(d for d in os.listdir(backups_base(addons_dir)) if d.startswith("_备份_"))
        if cands:
            backup_dir = os.path.join(addons_dir, cands[-1])

    zip_path = download_gitee_zip(log)
    if not zip_path:
        local = find_local_packages()
        if local:
            zip_path = local[0]
            log(f"[降级] 联网下载失败，改用本机已有的包: {os.path.basename(zip_path)}")
        else:
            log("[失败] 联网下载失败且本机没有插件包")
            if backup_dir:
                _restore_backup(addons_dir, backup_dir)
                log(f"[还原] 已把 {n_moved} 项原插件放回，目录恢复原样")
            return 0, []
    n, details = install_from_gitee_zip(zip_path, addons_dir, log)
    return n, details


# ================= 网页界面 =================

_UI_PATH = os.path.join(_RES_DIR, "ui.html")
try:
    with open(_UI_PATH, "r", encoding="utf-8") as _f:
        PAGE = _f.read()
except Exception:
    PAGE = '<!DOCTYPE html><meta charset=utf-8><body style="background:#111;color:#fff"><h2>ui.html 丢失</h2><p>请确认 ui.html 与程序在同一目录。</p></body>'



class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if self.path.startswith("/api/targets"):
            # 统一返回游戏根目录（含 WoW.exe 的那一层）
            roots = []
            for d in find_addons_dirs():
                r = _to_root(d)
                if r and r not in roots:
                    roots.append(r)
            saved = _to_root(load_config().get("target", ""))
            if saved and os.path.isdir(saved) and saved not in roots:
                roots.insert(0, saved)  # 自己设置的路径也要出现在下拉框里
            current = saved if saved and os.path.isdir(saved) else (roots[0] if roots else "")
            return self._send(200, json.dumps(
                {"targets": roots, "current": current, "exe": _find_game_exe(current),
                 "ver": _game_version(current), "app_ver": APP_VERSION}, ensure_ascii=False))
        if self.path == "/api/app_update_status":
            return self._send(200, json.dumps(dict(_APP_UPDATE), ensure_ascii=False))
        if self.path == "/api/account_get":
            return self._send(200, json.dumps(_load_account(), ensure_ascii=False))
        if self.path.startswith("/api/addons_catalog"):
            # 插件目录（来自蓝奏云缓存包）：下载了但未装入的插件也列出来，标"未安装"
            d = _kind_dst("addons")
            names = []
            if d and os.path.isdir(d):
                for e in sorted(os.listdir(d), key=str.lower):
                    p = os.path.join(d, e)
                    if os.path.isdir(p) and not e.startswith("_"):
                        names.append(e)
            return self._send(200, json.dumps(
                {"ready": _kind_ready("addons"), "plugins": names}, ensure_ascii=False))
        if self.path.startswith("/api/addons_pack"):
            q = urllib.parse.urlsplit(self.path).query
            target = urllib.parse.parse_qs(q).get("target", [""])[0]
            return self._send(200, json.dumps(list_package_addons(target), ensure_ascii=False))
        if self.path.startswith("/api/fonts_pack"):
            q = urllib.parse.urlsplit(self.path).query
            target = urllib.parse.parse_qs(q).get("target", [""])[0]
            return self._send(200, json.dumps(list_package_fonts(target), ensure_ascii=False))
        if self.path.startswith("/api/addons"):
            q = urllib.parse.urlsplit(self.path).query
            target = urllib.parse.parse_qs(q).get("target", [""])[0]
            return self._send(200, json.dumps(
                {"addons": list_installed_addons(_to_addons(target))}, ensure_ascii=False))
        if self.path.startswith("/api/realmlist"):
            q = urllib.parse.urlsplit(self.path).query
            target = urllib.parse.parse_qs(q).get("target", [""])[0]
            return self._send(200, json.dumps(
                {"realm": read_realmlist(_to_addons(target))}, ensure_ascii=False))
        if self.path.startswith("/api/mods"):
            q = urllib.parse.urlsplit(self.path).query
            params = urllib.parse.parse_qs(q)
            target = params.get("target", [""])[0]
            src = params.get("src", [""])[0]
            if not src:
                src = load_config().get("mod_src", "")
            if not (src and os.path.isdir(src)) and _kind_ready("mods"):
                src = _kind_dst("mods")  # 本地源无效 → 用蓝奏云缓存
            return self._send(200, json.dumps(
                list_package_mods(_to_addons(target), src), ensure_ascii=False))
        if self.path.startswith("/api/fonts"):
            q = urllib.parse.urlsplit(self.path).query
            target = urllib.parse.parse_qs(q).get("target", [""])[0]
            cfg = load_config()
            src = cfg.get("font_src") or DEFAULT_FONT_SRC
            if not (src and os.path.isdir(src)) and _kind_ready("fonts"):
                src = _kind_dst("fonts")  # 本地源无效 → 用蓝奏云缓存
            ta = _to_addons(target)
            dst = fonts_dst(ta) if ta else ""
            installed = bool(ta) and os.path.isdir(dst) and not cfg.get("fonts_backup")
            # 字体明细：先扫字体包（参与勾选），再扫游戏 Fonts 补充"已装入但不在包里"的
            fsel = _get_selection("fonts")
            files, seen = [], {}
            for base, flag, inpack in ((src, False, True), (dst, True, False)):
                if not (base and os.path.isdir(base)):
                    continue
                for fn in sorted(os.listdir(base)):
                    if not fn.lower().endswith((".ttf", ".otf", ".ttc")):
                        continue
                    key = fn.lower()
                    if key in seen:
                        if flag and not seen[key]["installed"]:
                            seen[key]["installed"] = True
                        continue
                    rec = {"name": fn,
                           "desc": FONT_INFO.get(key, "美化字体文件，覆盖客户端对应位置的默认字体"),
                           "installed": flag, "in_pack": inpack,
                           "selected": bool(fsel.get(key, True))}
                    files.append(rec)
                    seen[key] = rec
            files.sort(key=lambda f: (not f["installed"], f["name"].lower()))
            return self._send(200, json.dumps({
                "ok": True, "src": src, "src_exists": os.path.isdir(src),
                "file_count": _count_files(src) if os.path.isdir(src) else 0,
                "dst": dst, "installed": installed, "files": files,
            }, ensure_ascii=False))
        if self.path.startswith("/api/progress"):
            return self._send(200, json.dumps(get_progress(), ensure_ascii=False))
        if self.path.startswith("/api/lanzou_state"):
            return self._send(200, json.dumps(_lanzou_state(), ensure_ascii=False))
        if self.path.startswith("/api/session_state"):
            cfg = load_config()
            # 目标客户端路径：优先用前端传来的当前路径（query），其次配置里的 target。
            # 便携模式下 config.target 常为 None（程序靠 exe 同目录自动识别），必须接收前端传入，
            # 否则 _install_flags 拿到空 target 会误报「未装」，与「配置组件」进度清单（✓完毕）不一致。
            _q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            tgt = (_q.get("target", [""])[0] or cfg.get("target") or "")
            t = _to_addons(tgt)
            mi, ai, fi = _install_flags(t)
            res = all(_kind_ready(k) for k in _LANZOU_KINDS)
            return self._send(200, json.dumps({"applied": bool(mi and ai and fi),
                                               "mods": mi, "addons": ai, "fonts": fi,
                                               "res": res},
                                              ensure_ascii=False))
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return self._send(400, {"error": "bad json"})

        if self.path == "/api/parse":
            return self._api_parse(payload)
        if self.path == "/api/install":
            return self._api_install(payload)
        if self.path == "/api/update_gitee":
            return self._api_update_gitee(payload)
        if self.path == "/api/install_local":
            return self._api_install_local(payload)
        if self.path == "/api/addons_install":
            # 装入插件：缓存未就绪自动下载 → 把缓存插件包整体装入客户端（附加式，同启动游戏）
            _hist("装入插件（缓存未就绪会先自动下载）")
            t = _to_addons(payload.get("target", ""))
            if not t:
                return self._send(200, {"ok": False,
                                        "summary": "未设置游戏路径，请先在「首页」设置"})
            log_lines = []

            def _log(m):
                log_lines.append(m)
            _err = _ensure_kind_downloaded("addons", log_lines)
            if _err:
                return self._send(200, {"ok": False, "log": log_lines,
                                        "summary": _err})
            src_addons = _kind_dst("addons")
            if not (src_addons and os.path.isdir(src_addons)):
                _set_progress(0, done=True, msg="插件资源不可用")
                return self._send(200, {"ok": False, "log": log_lines,
                                        "summary": "插件资源不可用，请到「下载」页检查"})
            addons = normalize_addons_path(t, create=True)
            dirs = [e for e in sorted(os.listdir(src_addons))
                    if os.path.isdir(os.path.join(src_addons, e)) and not e.startswith("_")]
            n = 0
            _set_progress(5, "插件", "插件安装中…", step="插件")
            for i, e in enumerate(dirs):
                try:
                    shutil.copytree(os.path.join(src_addons, e),
                                    os.path.join(addons, e), dirs_exist_ok=True)
                    n += 1
                except Exception as ex:
                    _log("[插件] 装入 " + e + " 失败：" + str(ex))
                _set_progress(5 + 85 * (i + 1) // max(1, len(dirs)), step="插件")
            _log("[插件] 从缓存插件包装入 " + str(n) + " 个")
            _set_progress(100, "插件", "插件安装完毕", step="插件")
            if n > 0:
                cfg = load_config()
                cfg["session_applied"] = True
                save_config(cfg)
            return self._send(200, {"ok": n > 0, "log": log_lines,
                                    "summary": ("已装入插件 " + str(n) + " 个") if n
                                    else "未装入任何插件，请看日志"})
        if self.path == "/api/precheck":
            # 配置组件 = 启动游戏的前置工作：资源下载(缺则自动下载) → 模组 → 插件 → 字体，
            # 全部完成才返回 ok=True；「启动游戏」只在配置通过后可用（只负责启动）。
            t = _to_addons(payload.get("target", ""))
            if not t:
                return self._send(200, {"ok": False,
                                        "summary": "未设置游戏路径，请先在「首页」设置"})
            log_lines = []
            _reset_progress()
            _hist("开始配置组件（资源下载→模组→插件→字体）")

            def _log(m):
                log_lines.append(m)
                _set_progress(log=m)   # 日志随进度流式推给前端，不等结束一次性显示
            for kind in ("mods", "addons", "fonts"):
                _set_progress(3, "下载", "检查资源：" + _KIND_LABEL.get(kind, kind) + "…")
                _err = _ensure_kind_downloaded(kind, log_lines)
                if _err:
                    return self._send(200, {"ok": False, "log": log_lines,
                                            "summary": _err})
            # 资源全部就绪：标记"下载"阶段完成，分步列表显示 ✓资源下载：完毕
            _set_progress(60, "下载", "资源全部就绪", step="下载")
            _set_progress(62, "模组", "资源就绪，开始安装：模组→插件→字体…")
            ok, summary, status = apply_overlay(t, _kind_dst("mods"),
                                        _kind_dst("addons"), _log, _kind_dst("fonts"))
            flags = _install_flags(t)          # (mods, addons, fonts) 在盘状态
            res = {k: _kind_ready(k) for k in ("mods", "addons", "fonts")}
            all_ok = bool(ok and all(flags) and all(res.values()))
            _set_progress(100, "完成",
                          "配置组件完成，可以启动游戏" if all_ok else "配置未通过：" + str(summary),
                          done=True)
            _hist("配置组件" + ("完成，可以启动游戏" if all_ok else "未通过：" + str(summary)))
            return self._send(200, {"ok": all_ok, "flags": {"mods": flags[0],
                                                            "addons": flags[1],
                                                            "fonts": flags[2]},
                                    "resources": res, "status": status, "log": log_lines,
                                    "summary": ("配置组件完成，可以启动游戏" if all_ok
                                                else "配置未通过：" + str(summary))})
        if self.path == "/api/cleanup":
            # 清理还原：结束游戏 + 移除本次装入的模组/插件/字体(先备份) + 恢复 dlls.txt。
            # 不删下载缓存（持久化模型，缓存留盘复用）；不退出程序，倒计时后回初始界面。
            _reset_progress()
            _set_progress(8, "还原", "正在清理还原：结束游戏、移除本次装入的组件、恢复 dlls.txt…")
            _hist("开始清理还原（结束游戏并恢复客户端初始状态）")

            def _go():
                try:
                    def _l(m):
                        _set_progress(log=m)
                    t = payload.get("target", "")
                    if not (t and os.path.isdir(_to_root(t))):
                        t = load_config().get("target", "")
                    _cleanup_restore(_to_addons(t), _l)
                    _set_progress(100, "完成", "清理还原完成：已装组件已移除、客户端原有内容已还原、WowAbak 已清空", done=True)
                except Exception:
                    pass
            threading.Thread(target=_go, daemon=True).start()
            return self._send(200, {"ok": True, "msg": "正在清理还原…"})
        if self.path == "/api/uninstall_all":
            _hist("全部移除插件（挪到备份文件夹）")
            return self._api_uninstall_all(payload)
        if self.path == "/api/uninstall_one":
            _hist("移除单个插件：" + str(payload.get("name", "")))
            return self._api_uninstall_one(payload)
        if self.path == "/api/set_target":
            return self._api_set_target(payload)
        if self.path == "/api/launch":
            return self._api_launch(payload)
        if self.path == "/api/open":
            return self._api_open(payload)
        if self.path == "/api/choose_exe":
            return self._api_choose_exe(payload)
        if self.path == "/api/mod_toggle":
            t = _to_addons(payload.get("target", ""))
            n = payload.get("name", "")
            en = bool(payload.get("enable", False))
            ok, msg = mod_toggle(t, n, en)
            return self._send(200, {"ok": ok, "msg": msg})
        if self.path == "/api/mod_import":
            t = _to_addons(payload.get("target", ""))
            src = payload.get("src", "")
            ok, log_lines, summary = mod_import_package(t, src)
            if ok and src and os.path.isdir(src):
                # 记录本次导入的 DLL 文件名，供「移除模组」/「清理还原」清理
                _dlls = [f for f in os.listdir(src) if f.lower().endswith(".dll")]
                if _dlls:
                    _record_custom("mods", _dlls)
            return self._send(200, {"ok": ok, "log": log_lines, "summary": summary})
        if self.path == "/api/addons_select":
            n = payload.get("name", "")
            en = bool(payload.get("selected", False))
            if _addon_locked(n) and not en:
                return self._send(200, {"ok": False,
                                        "msg": "该插件是库插件/客户端前置，不能取消勾选"})
            _set_selection("addons", n, en)
            return self._send(200, {"ok": True})
        if self.path == "/api/addons_apply":
            # 按插件页勾选立即同步：装入勾选未装的；移除已装但取消勾选的（直接删除）
            _hist("应用插件勾选（缓存未就绪会先自动下载）")
            t = _to_addons(payload.get("target", ""))
            if not t:
                return self._send(200, {"ok": False,
                                        "summary": "未设置游戏路径，请先在「首页」设置"})
            log_lines = []

            def _log(m):
                log_lines.append(m)
            _err = _ensure_kind_downloaded("addons", log_lines)
            if _err:
                return self._send(200, {"ok": False, "log": log_lines, "summary": _err})
            src_addons = _kind_dst("addons")
            if not (src_addons and os.path.isdir(src_addons)):
                return self._send(200, {"ok": False, "log": log_lines,
                                        "summary": "插件资源不可用，请到「下载」页检查"})
            addons = normalize_addons_path(t, create=True)
            sel = _get_selection("addons")
            names = [e for e in sorted(os.listdir(src_addons))
                     if os.path.isdir(os.path.join(src_addons, e)) and not e.startswith("_")]
            chosen = [e for e in names if _addon_locked(e) or sel.get(e.lower(), True)]
            chosen_l = {e.lower() for e in chosen}
            # 1) 移除已装但取消勾选的 → 直接删除（不备份）
            n_rem = 0
            if os.path.isdir(addons):
                for e in sorted(os.listdir(addons), key=str.lower):
                    if e.startswith("_") or e.lower() in chosen_l:
                        continue
                    p = os.path.join(addons, e)
                    if os.path.isdir(p):
                        try:
                            shutil.rmtree(p)
                            n_rem += 1
                            _log("[插件] 已移除（直接删除）：" + e)
                        except Exception as ex:
                            _log("[插件] 移除 " + e + " 失败：" + str(ex))
            # 2) 装入勾选但未装的
            n_inst = 0
            for e in chosen:
                dstp = os.path.join(addons, e)
                if os.path.isdir(dstp):
                    continue
                try:
                    shutil.copytree(os.path.join(src_addons, e), dstp)
                    n_inst += 1
                    _log("[插件] 装入 " + e)
                except Exception as ex:
                    _log("[插件] 装入 " + e + " 失败：" + str(ex))
            if n_inst or n_rem:
                _mark_installed("addons", _log)
            cfg = load_config()
            cfg["session_applied"] = _overlay_present(t)
            save_config(cfg)
            summary = "插件勾选已应用：装入 %d 个、移除 %d 个，共勾选 %d 个" % (n_inst, n_rem, len(chosen))
            _set_progress(0, done=True, msg=summary)
            return self._send(200, {"ok": True, "log": log_lines, "summary": summary})
        if self.path == "/api/fonts_select":
            _set_selection("fonts", payload.get("name", ""),
                           bool(payload.get("selected", False)))
            return self._send(200, {"ok": True})
        if self.path == "/api/fonts_apply":
            # 按字体页勾选立即同步：装入勾选未装的；未勾选已装的会被安装前处理移除（=直接删除）
            _hist("应用字体勾选（缓存未就绪会先自动下载）")
            t = _to_addons(payload.get("target", ""))
            if not t:
                return self._send(200, {"ok": False,
                                        "summary": "未设置游戏路径，请先在「首页」设置"})
            log_lines = []

            def _log(m):
                log_lines.append(m)
            _err = _ensure_kind_downloaded("fonts", log_lines)
            if _err:
                return self._send(200, {"ok": False, "log": log_lines, "summary": _err})
            src = _kind_dst("fonts")
            if not (src and os.path.isdir(src)):
                return self._send(200, {"ok": False, "log": log_lines,
                                        "summary": "字体资源不可用，请到「下载」页检查"})
            n = install_fonts(t, src, _log)
            _mark_installed("fonts", _log)
            cfg = load_config()
            cfg["session_applied"] = _overlay_present(t)
            save_config(cfg)
            summary = "字体勾选已应用：装入/更新 %d 个文件（未勾选的已移除）" % n
            _set_progress(0, done=True, msg=summary)
            return self._send(200, {"ok": True, "log": log_lines, "summary": summary})
        if self.path == "/api/mod_select":
            n = payload.get("name", "")
            en = bool(payload.get("selected", False))
            set_mod_selection(n, en)
            return self._send(200, {"ok": True, "selected": get_mod_selection()})
        if self.path == "/api/mods_apply":
            _hist("装入模组（按勾选，缓存未就绪会先自动下载）")
            t = _to_addons(payload.get("target", ""))
            src = payload.get("src", "")
            if not src:
                src = load_config().get("mod_src", "")
            if not (src and os.path.isdir(src)) and _kind_ready("mods"):
                src = _kind_dst("mods")  # 本地源无效 → 用蓝奏云缓存
            log_lines = []

            def _log(m):
                log_lines.append(m)
            # 缓存未就绪（退出时会清缓存）→ 自动先下载模组包再安装，按钮不再"没反应"
            if not (src and os.path.isdir(src)):
                _err = _ensure_kind_downloaded("mods", log_lines)
                if _err:
                    return self._send(200, {"ok": False, "log": log_lines,
                                            "summary": _err})
                src = _kind_dst("mods")
            if not (src and os.path.isdir(src)):
                _set_progress(0, done=True, msg="模组资源不可用")
                return self._send(200, {"ok": False, "log": log_lines,
                                        "summary": "模组资源不可用，请到「下载」页检查"})
            ok, summary = apply_mod_selection(t, src, _log)
            _set_progress(0, done=True, msg=summary or ("完成" if ok else "失败"))
            return self._send(200, {"ok": ok, "log": log_lines, "summary": summary})
        if self.path == "/api/mods_sync":
            t = _to_addons(payload.get("target", ""))
            log_lines = []

            def _log(m):
                log_lines.append(m)
            ok, msg = ensure_mods_loaded(t, _log)
            return self._send(200, {"ok": ok, "log": log_lines, "summary": msg})
        if self.path == "/api/addons_import":
            t = _to_addons(payload.get("target", ""))
            src = payload.get("src", "")
            log_lines = []

            def _log(m):
                log_lines.append(m)
            if not t or not os.path.isdir(t):
                return self._send(200, {"ok": False, "log": ["[错误] 安装位置无效，请先设置游戏路径"],
                                        "summary": "安装位置无效"})
            n, details = install_addons_from_interface(src, t, _log)
            if n and details:
                # 记录本次整体替换装入的插件文件夹，供「移除」/「清理还原」清理
                _record_custom("addons", details)
            return self._send(200, {"ok": n > 0, "count": n, "log": log_lines,
                                    "summary": ("已整体替换，装入 " + str(n) + " 个插件") if n else "未装入任何插件，请看日志"})
        if self.path == "/api/quick_play":
            # 首页「启动游戏」合并流程：装模组→装插件→装字体→启动游戏（带进度）
            t_root = _to_root(payload.get("target", ""))
            if not t_root or not os.path.isdir(t_root):
                _set_progress(0, done=True, msg="游戏路径无效，请先设置")
                return self._send(200, {"ok": False, "log": ["[错误] 游戏路径无效"],
                                        "summary": "游戏路径无效，请先设置"})
            t = _to_addons(t_root)
            os.makedirs(t, exist_ok=True)
            _bm, _ba, _bf, _from = _builtin_sources_with_cache()

            def _vs(p, fb):
                """UI 传来的源路径仅在真实存在时才采用，否则一律回退缓存源。"""
                return p if (p and os.path.isdir(p)) else fb
            mod_src = _vs(payload.get("mod_src", ""), _bm)
            addon_src = _vs(payload.get("addon_src", ""), _ba)
            font_src = _vs(payload.get("font_src", ""), _bf)
            log_lines = []

            def _log(m):
                log_lines.append(m)
            # 资源未就绪 → 自动先下载（缺哪类下哪类），进度实时映射到首页进度条，
            # 下载完自动继续安装+启动（用户点一下就全自动，不再要求先去下载页）
            _has_mod = bool(mod_src) and os.path.isdir(mod_src)
            _has_add = bool(addon_src) and os.path.isdir(addon_src)
            if not _has_mod or not _has_add:
                _set_progress(2, msg="本地没有资源，开始自动下载（首次约几分钟）…", stage="下载")
                log_lines.append("[下载] 本地没有资源，自动开始下载（来自蓝奏云资源文件夹）")
                kinds = []
                if not _has_mod:
                    kinds.append("mods")
                if not _has_add:
                    kinds.append("addons")
                if not (bool(font_src) and os.path.isdir(font_src)):
                    kinds.append("fonts")
                kinds = [k for k in kinds if not _kind_ready(k)]
                if not kinds and (_kind_ready("mods") and _kind_ready("addons")):
                    # 缓存其实已就绪（UI 无效源路径干扰）→ 强制用缓存源，忽略 UI 传值
                    _bm, _ba, _bf, _from = _builtin_sources_with_cache()
                    mod_src, addon_src, font_src = _bm, _ba, _bf
                    _has_mod = bool(mod_src) and os.path.isdir(mod_src)
                    _has_add = bool(addon_src) and os.path.isdir(addon_src)
                if kinds:
                    def _queue():
                        try:
                            for k in kinds:
                                if not _kind_ready(k):
                                    _download_kind(k)
                        except Exception as ex:
                            _DL_STATE["error"] = "下载线程异常：" + repr(ex)
                            _DL_STATE["busy"] = False
                    threading.Thread(target=_queue, daemon=True).start()
                    deadline = time.time() + 1800  # 保险：最长等 30 分钟
                    while time.time() < deadline:
                        if _DL_STATE.get("error"):
                            break
                        if all(_kind_ready(k) for k in kinds):
                            break
                        st = dict(_DL_STATE)
                        _set_progress(min(60, 2 + int(st.get("pct", 0) * 0.58)),
                                      msg="下载资源：%s" % (st.get("msg", "") or ""),
                                      stage="下载")
                        time.sleep(1.0)
                    if _DL_STATE.get("error"):
                        _err = _DL_STATE.get("error", "")
                        _set_progress(0, done=True, msg="资源下载失败：" + _err)
                        return self._send(200, {"ok": False,
                                                "log": log_lines + ["[错误] 下载失败：" + _err],
                                                "summary": "资源下载失败：" + _err + "（详情见「下载」页）"})
                    if not all(_kind_ready(k) for k in ("mods", "addons")):
                        _set_progress(0, done=True, msg="资源下载超时/未就绪，请到「下载」页查看")
                        return self._send(200, {"ok": False, "log": log_lines,
                                                "summary": "资源下载未完成，请稍后重试或到「下载」页查看"})
                    # 重新解析缓存源（下载完成 → 强制用缓存，忽略 UI 传来的无效路径）
                    _bm, _ba, _bf, _from = _builtin_sources_with_cache()
                    mod_src, addon_src, font_src = _bm, _ba, _bf
                    _has_mod = bool(mod_src) and os.path.isdir(mod_src)
                    _has_add = bool(addon_src) and os.path.isdir(addon_src)
                    log_lines.append("[下载] 资源就绪（%s），等待安装" % _from)
                if not _has_mod and not _has_add:
                    _set_progress(0, done=True, msg="资源仍不可用，请到「下载」页检查")
                    return self._send(200, {"ok": False, "log": log_lines,
                                            "summary": "资源仍不可用，请到「下载」页检查配置"})
            _reset_progress()
            # 每次都完整执行安装（apply_overlay 幂等，已装的部分重拷很快）：
            # 保证模组+插件+字体全部就绪，缺一项都不允许启动游戏。
            try:
                ok, summary, _st = apply_overlay(t, mod_src, addon_src, _log, font_src)
            except Exception as ex:
                ok, summary = False, "安装流程异常：" + repr(ex)
                _log("[错误] " + summary)
                _set_progress(0, done=True, msg=summary)
            if ok:
                _persist_target(t)
            if not ok:
                _set_progress(0, done=True, msg="安装失败：" + str(summary))
                return self._send(200, {"ok": False, "log": log_lines,
                                        "summary": "安装失败：" + str(summary)})
            # 启动前自检：模组/插件/字体全部真实在盘上才启动
            mi, ai, fi = _install_flags(t)
            _missing = [lbl for f, lbl in ((mi, "模组"), (ai, "插件"), (fi, "字体")) if not f]
            if _missing:
                _set_progress(0, done=True,
                              msg="安装未完成（缺" + "、".join(_missing) + "），本次不启动游戏")
                return self._send(200, {"ok": False, "log": log_lines,
                                        "summary": "自检未通过：缺" + "、".join(_missing) +
                                                   "，本次不启动游戏。请到「下载」页确认资源就绪后重试"})
            _set_progress(98, "启动", "正在启动游戏…")
            ok, exe = launch_game(t)
            if ok:
                _set_progress(100, done=True, msg="游戏已启动，尽情玩耍吧", step="启动")
                summary = "游戏已启动（退出工具时不会自动还原，已装组件与缓存都会保留）"
            else:
                _set_progress(100, done=True, msg="启动失败，请检查客户端路径")
                summary = "启动失败：" + str(exe)
            return self._send(200, {"ok": ok, "log": log_lines, "summary": summary})
        if self.path == "/api/lanzou_config":
            kind = payload.get("kind", "")
            links = payload.get("links", [])
            # folder 分享模式：{"kind":"folder","url":"..","pwd":".."}
            if kind == "folder":
                cfg = load_config()
                cfg["folder"] = {"url": str(payload.get("url", "")).strip(),
                                 "pwd": str(payload.get("pwd", "")).strip()}
                save_config(cfg)
                _FOLDER_CACHE.update({"ts": 0.0, "files": None, "err": ""})
                files = _folder_files(force=True)
                return self._send(200, {"ok": True, "state": _lanzou_state(),
                                        "files": files or [],
                                        "err": _FOLDER_CACHE.get("err", "")})
            # manifest 单独配置：{"kind":"manifest","url":"..","pwd":".."}
            if kind == "manifest":
                cfg = load_config()
                cfg["manifest"] = {"url": str(payload.get("url", "")).strip(),
                                   "pwd": str(payload.get("pwd", "")).strip()}
                save_config(cfg)
                return self._send(200, {"ok": True, "state": _lanzou_state()})
            # 自定义直链源：{"kind":"direct","text":"url1\nurl2\n..."}
            if kind == "direct":
                cfg = load_config()
                raw = str(payload.get("text", "") or "")
                urls = [x.strip() for x in re.split(r"[\r\n,]+", raw) if x.strip()]
                cfg["direct"] = {"urls": urls}
                save_config(cfg)
                return self._send(200, {"ok": True, "state": _lanzou_state()})
            if kind not in _LANZOU_KINDS:
                return self._send(200, {"ok": False, "msg": "未知资源类型"})
            cfg = load_config()
            lz = cfg.get("lanzou", {}) or {}
            lz[kind] = [{"url": str(x.get("url", "")).strip(),
                         "pwd": str(x.get("pwd", "")).strip()}
                        for x in links if str(x.get("url", "")).strip()]
            cfg["lanzou"] = lz
            save_config(cfg)
            return self._send(200, {"ok": True, "state": _lanzou_state()})
        if self.path == "/api/cache_config":
            # 下载缓存自动清理设置：{"auto_clean": true/false, "keep_days": 30}
            cfg = load_config()
            ac = bool(payload.get("auto_clean", True))
            kd = int(payload.get("keep_days", 30))
            if kd < 1:
                kd = 1
            cfg["cache"] = {"auto_clean": ac, "keep_days": kd}
            save_config(cfg)
            return self._send(200, {"ok": True, "state": _lanzou_state()})
        if self.path == "/api/lanzou_download":
            kind = payload.get("kind", "all")
            if _DL_STATE.get("busy"):
                return self._send(200, {"ok": False, "msg": "正在下载中，请稍候"})
            if kind == "sync":
                has_mf = (load_config().get("manifest", {}) or {}).get("url")
                if not has_mf and not _folder_files():
                    return self._send(200, {"ok": False, "msg": "未配置 manifest 清单链接"})
                threading.Thread(target=_sync_plugins, daemon=True).start()
                return self._send(200, {"ok": True, "msg": "已开始按清单增量更新"})
            kinds = list(_LANZOU_KINDS) if kind == "all" else [kind]

            def _queue():
                for k in kinds:
                    if _kind_ready(k):
                        continue
                    _download_kind(k)
            threading.Thread(target=_queue, daemon=True).start()
            return self._send(200, {"ok": True, "msg": "下载已开始"})
        if self.path == "/api/fonts_src":
            src = (payload.get("src", "") or "").strip()
            if not src:
                return self._send(200, {"ok": False, "msg": "请填写字体文件夹路径"})
            cfg = load_config()
            cfg["font_src"] = src
            save_config(cfg)
            return self._send(200, {"ok": True, "msg": "已保存字体路径"})
        if self.path == "/api/fonts_install":
            _hist("装入字体（缓存未就绪会先自动下载）")
            t = _to_addons(payload.get("target", ""))
            log_lines = []

            def _log(m):
                log_lines.append(m)
            # 字体缓存未就绪（退出时会清缓存）→ 自动先下载字体包再安装
            _err = _ensure_kind_downloaded("fonts", log_lines)
            if _err:
                return self._send(200, {"ok": False, "log": log_lines,
                                        "summary": _err})
            src = (payload.get("src", "") or "").strip() or load_config().get("font_src") or DEFAULT_FONT_SRC
            if not (src and os.path.isdir(src)) and _kind_ready("fonts"):
                src = _kind_dst("fonts")  # 本地源无效 → 用蓝奏云缓存
            n = install_fonts(t, src, _log)
            if n > 0:
                cfg = load_config()
                cfg["session_applied"] = True
                save_config(cfg)
            return self._send(200, {"ok": n > 0, "log": log_lines,
                                    "summary": ("已装入字体 " + str(n) + " 个文件") if n else "未装入任何字体，请看日志"})
        if self.path == "/api/fonts_remove":
            t = _to_addons(payload.get("target", ""))
            log_lines = []

            def _log(m):
                log_lines.append(m)
            ok = remove_fonts(t, _log)
            cfg = load_config()
            cfg["session_applied"] = _overlay_present(t)
            save_config(cfg)
            return self._send(200, {"ok": ok, "log": log_lines,
                                    "summary": "字体已移除，客户端恢复原样" if ok else "没有已装入的字体"})
        if self.path == "/api/mods_remove":
            # 移除模组：删游戏根里的模组 DLL（内置注入器的 VfPatcher/nampower 一并），
            # dlls.txt 恢复初始基线；与字体页「移除字体」同形式
            t_root = _to_root(payload.get("target", ""))
            log_lines = []

            def _log(m):
                log_lines.append(m)
            if not t_root or not os.path.isdir(t_root):
                return self._send(200, {"ok": False, "log": log_lines,
                                        "summary": "未设置游戏路径，请先在「首页」设置"})
            names = list(MOD_DLL_ORDER)
            try:
                src = _kind_dst("mods")
                if src and os.path.isdir(src):
                    names += [e for e in os.listdir(src)
                              if os.path.isfile(os.path.join(src, e))
                              and e.lower().endswith(".dll")]
            except Exception:
                pass
            n = 0
            for nm in dict.fromkeys(names):
                p = os.path.join(t_root, nm)
                if os.path.isfile(p):
                    try:
                        os.remove(p)
                        n += 1
                        _log("[模组] 已移除：" + nm)
                    except Exception as ex:
                        _log("[模组] 移除 " + nm + " 失败：" + str(ex))
            cfg = load_config()
            base = cfg.get("baseline_dllstxt")
            if base is not None:
                try:
                    with open(os.path.join(t_root, "dlls.txt"), "w",
                              encoding="utf-8") as f:
                        f.write(base)
                    _log("[模组] dlls.txt 已恢复初始内容")
                except Exception as ex:
                    _log("[模组] dlls.txt 恢复失败：" + str(ex))
            # 恢复客户端原有（非资源包）模组文件，然后删除该备份
            _restore_original_backup(t_root, "模组备份", t_root, _log)
            # 移除自定义导入的模组 DLL（install_state.custom.mods）
            for _nm in _custom_imports().get("mods", []):
                _p = os.path.join(t_root, _nm)
                if os.path.isfile(_p):
                    try:
                        os.remove(_p)
                        n += 1
                        _log("[模组] 已移除自定义：" + _nm)
                    except Exception as _ex:
                        _log("[模组] 移除 " + _nm + " 失败：" + str(_ex))
            _clear_custom("mods")
            ist = cfg.get("install_state", {})
            if "mods" in ist:
                ist.pop("mods", None)
                cfg["install_state"] = ist
            cfg["session_applied"] = _overlay_present(t_root)
            save_config(cfg)
            return self._send(200, {"ok": True, "log": log_lines,
                                    "summary": ("已移除 %d 个模组文件" % n) if n
                                    else "没有已装入的模组"})
        if self.path == "/api/exit":
            self._send(200, {"ok": True, "msg": "正在退出…（已安装的组件与缓存都会保留）"})

            def _go():
                time.sleep(0.4)
                _teardown()
                _flush_stdio()
                os._exit(0)
            threading.Thread(target=_go, daemon=True).start()
            return
        if self.path == "/api/app_update_config":
            au = _app_update_cfg()
            au["enabled"] = bool(payload.get("enabled", au.get("enabled", True)))
            au["folder_url"] = str(payload.get("folder_url", au.get("folder_url", ""))).strip()
            au["folder_pwd"] = str(payload.get("folder_pwd", au.get("folder_pwd", ""))).strip()
            if "skipped" in payload:
                au["skipped"] = str(payload.get("skipped", "")).strip()
            _save_app_update_cfg(au)
            return self._send(200, {"ok": True})
        if self.path == "/api/app_update_check":
            return self._send(200, json.dumps(_check_app_update(), ensure_ascii=False))
        if self.path == "/api/app_update_apply":
            threading.Thread(target=_apply_app_update, daemon=True).start()
            return self._send(200, {"ok": True, "msg": "已开始下载更新，完成后自动重启"})
        if self.path == "/api/choose_dir":
            _flt = str(payload.get("filter", "*.dll") or "*.dll")
            _picked = choose_dir_dialog(load_config().get("target", ""), _flt)
            if _picked:
                return self._send(200, {"ok": True, "path": _picked})
            return self._send(200, {"ok": False, "msg": "未选择文件夹"})
        if self.path == "/api/fonts_import_local":
            t = _to_addons(payload.get("target", ""))
            src = payload.get("src", "")
            log_lines = []

            def _log(m):
                log_lines.append(m)
            if not t or not os.path.isdir(t):
                return self._send(200, {"ok": False, "log": ["[错误] 安装位置无效，请先设置游戏路径"],
                                        "summary": "安装位置无效"})
            n = import_fonts_local(src, t, _log)
            return self._send(200, {"ok": n > 0, "log": log_lines,
                                    "summary": ("已从本地导入 %d 个字体" % n) if n else "未导入任何字体，请看日志"})
        if self.path == "/api/account_save":
            _save_account(str(payload.get("user", "")), str(payload.get("pwd", "")),
                         bool(payload.get("remember", False)))
            return self._send(200, {"ok": True})
        if self.path == "/api/account_clear":
            _save_account("", "", False)
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def _api_open(self, payload):
        # select=文件完整路径 → 资源管理器打开其所在文件夹并选中该文件（首页「打开」定位 WoW.exe）
        sel = payload.get("select", "")
        if sel and os.path.isfile(sel):
            if sys.platform == "win32":
                # 不用 shell=True（否则 cmd 会闪一下黑窗）；explorer 是 GUI 程序，
                # 以列表形式直启即无控制台窗口。/select, 后面紧跟完整路径可选中该文件。
                subprocess.Popen(["explorer", "/select," + sel])
            return self._send(200, {"ok": True})
        path = payload.get("path", "")
        if path and os.path.isdir(path):
            if sys.platform == "win32":
                os.startfile(path)  # noqa
            return self._send(200, {"ok": True})
        self._send(400, {"ok": False, "error": "目录不存在"})

    def _api_choose_exe(self, payload):
        """弹出原生"选择 WoW.exe"文件对话框（comdlg32 GetOpenFileNameW），
        返回选中的完整路径；取消/失败返回 ok=False。"""
        picked = choose_wow_exe_dialog(load_config().get("target", ""))
        if picked:
            _hist("手动选择游戏主程序：" + picked)
            return self._send(200, {"ok": True, "path": picked})
        return self._send(200, {"ok": False, "msg": "未选择文件"})

    def _parse_tasks(self, payload):
        raw = payload.get("input", "")
        tasks = []
        for line in re.split(r"[\n;]+", raw):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"(\S+)(?:\s+(.+))?", line)
            if m and DOMAIN_RE.match(m.group(1)):
                tasks.append((m.group(1), (m.group(2) or "").strip()))
        return tasks

    def _api_parse(self, payload):
        results, all_log = [], []
        for url, pwd in self._parse_tasks(payload):
            client = get_client()
            client.log_lines = []
            state, link = client.get_direct_link(url, password=pwd, retries=3)
            name = ""
            if state == "Success":
                st, fi = client.get_file_info(url, pwd)
                if st == "Success" and fi:
                    name = fi.get("文件名") or ""
            results.append({"url": url, "state": state, "link": link or "", "name": name})
            all_log.append(f"== {url} ==")
            all_log.extend(client.log_lines or [])
        self._send(200, json.dumps({"results": results, "log": all_log}, ensure_ascii=False))

    def _api_install(self, payload):
        target = _to_addons(payload.get("target", ""))
        log_lines = []

        def log(msg):
            log_lines.append(msg)
            print(msg)

        if not target or not os.path.isdir(target):
            return self._send(200, json.dumps(
                {"log": ["[错误] 安装位置无效"], "summary": "安装位置无效"}, ensure_ascii=False))

        tasks = self._parse_tasks(payload)
        if not tasks:
            return self._send(200, json.dumps(
                {"log": ["[错误] 没有识别到有效的蓝奏云链接"],
                 "summary": "没有识别到有效的蓝奏云链接"}, ensure_ascii=False))

        ok_files, ok_addons, fail = [], [], []
        for url, pwd in tasks:
            log(f"== 开始处理 {url} ==")
            client = get_client()
            client.log_lines = []
            state, link = client.get_direct_link(url, password=pwd, retries=3)
            log_lines.extend(client.log_lines or [])
            if state != "Success" or not link:
                fail.append(url)
                log(f"[失败] 直链解析失败（{state}），跳过")
                continue
            path = download_file(link, DOWNLOAD_DIR, log)
            if not path:
                fail.append(url)
                continue
            ok_files.append(os.path.basename(path))

            with TempDir() as td:
                ok, msg = extract_archive(path, td, log)
                if not ok:
                    fail.append(url)
                    log(f"[失败] {msg}")
                    continue
                n, details = install_from_extracted(td, target, log)
                if n == 0:
                    fail.append(url)
                    log("[失败] 压缩包里没找到插件（没有 .toc 文件），可能不是插件包")
                else:
                    ok_addons.extend(details)

        summary = ""
        if ok_addons:
            summary = f"成功安装 {len(ok_addons)} 个插件：{'、'.join(ok_addons)}。重启游戏生效。"
        elif ok_files:
            summary = "下载成功但未识别出插件，请看日志。"
        else:
            summary = "全部失败，请把日志发给助手分析。"
        if fail:
            summary += f"（{len(fail)} 个链接处理失败）"
        log(f"== 完成: {summary} ==")
        self._send(200, json.dumps(
            {"log": log_lines, "summary": summary,
             "installed": ok_addons, "failed": fail}, ensure_ascii=False))

    def _api_set_target(self, payload):
        raw = payload.get("path", "")
        # 统一定位到游戏根目录（含 WoW.exe 的那一层）：粘 Interface 或 AddOns、
        # 甚至直接选中 WoW.exe 文件本身，都能自动归一到根目录
        root = _to_root(raw)
        if not root or not os.path.isdir(root):
            return self._send(200, json.dumps(
                {"ok": False, "msg": f"目录不存在: {raw}"}, ensure_ascii=False))
        cfg = load_config()
        cfg["target"] = root
        save_config(cfg)
        # 校验这层是不是真的游戏根：应能找到魔兽主程序
        exe = _find_game_exe(root)
        if exe:
            msg = "已设置游戏客户端：" + exe
        else:
            msg = "已设置游戏根目录: " + root + "（注意：该目录下没找到 WoW.exe，请确认选择正确）"
        return self._send(200, json.dumps(
            {"ok": True, "path": root, "exe": exe, "msg": msg}, ensure_ascii=False))

    def _api_launch(self, payload):
        target = _to_addons(payload.get("target", ""))
        if not target or not os.path.isdir(target):
            return self._send(400, {"ok": False, "dir": target})
        _reset_progress()
        _set_progress(20, "启动", "正在启动游戏…")
        ok, p = launch_game(target)
        _set_progress(100, "完成", "游戏已启动" if ok else "启动失败", done=True)
        _hist("启动游戏：" + p if ok else "启动游戏失败（" + str(p) + "）")
        return self._send(200, json.dumps(
            {"ok": ok, "exe": p, "dir": client_root_of(target)}, ensure_ascii=False))

    def _api_update_gitee(self, payload):
        target = _to_addons(payload.get("target", ""))
        log_lines = []

        def log(msg):
            log_lines.append(msg)

        if not target or not os.path.isdir(target):
            return self._send(200, json.dumps(
                {"log": ["[错误] 安装位置无效"], "summary": "安装位置无效"}, ensure_ascii=False))
        n, details = install_online(target, log)
        summary = f"成功安装 {n} 个插件，重启游戏生效。" if n else "更新失败，请看日志。"
        if details:
            summary += f"（{('、'.join(details[:8]))}{'...' if len(details) > 8 else ''}）"
        return self._send(200, json.dumps(
            {"log": log_lines, "summary": summary, "installed": details}, ensure_ascii=False))

    def _api_install_local(self, payload):
        target = _to_addons(payload.get("target", ""))
        log_lines = []

        def log(msg):
            log_lines.append(msg)

        if not target or not os.path.isdir(target):
            return self._send(200, json.dumps(
                {"log": ["[错误] 安装位置无效"], "summary": "安装位置无效"}, ensure_ascii=False))
        pkgs = find_local_packages()
        if not pkgs:
            return self._send(200, json.dumps(
                {"log": ["[提示] 本机没找到插件包（已查 D:/game 和 downloads 目录）"],
                 "summary": "本机没有插件包，请用「联网下载安装」"}, ensure_ascii=False))
        n, details = install_local_pkg(target, log)
        summary = f"成功安装 {n} 个插件，重启游戏生效。" if n else "安装失败，请看日志。"
        return self._send(200, json.dumps(
            {"log": log_lines, "summary": summary, "installed": details}, ensure_ascii=False))

    def _api_uninstall_all(self, payload):
        target = _to_addons(payload.get("target", ""))
        log_lines = []

        def log(msg):
            log_lines.append(msg)

        if not target or not os.path.isdir(target):
            return self._send(200, json.dumps(
                {"log": ["[错误] 安装位置无效"], "summary": "安装位置无效"}, ensure_ascii=False))
        moved = uninstall_all_addons(target, log)
        _clear_custom("addons")
        summary = f"已直接移除 {moved} 项插件（不备份）。重启游戏生效。" if moved \
            else "目录本来就是空的，没有可移除的插件。"
        return self._send(200, json.dumps(
            {"log": log_lines, "summary": summary}, ensure_ascii=False))

    def _api_uninstall_one(self, payload):
        target = _to_addons(payload.get("target", ""))
        name = payload.get("name", "")
        ok, msg = uninstall_one(target, name, print)
        return self._send(200, json.dumps({"ok": ok, "msg": msg}, ensure_ascii=False))

    def log_message(self, *a):
        pass



# 核心引擎 DLL：禁用会导致游戏无法启动，模组页锁定不可改
CORE_DLLS = {
    "sdl.dll", "fmod.dll", "fmod_event.dll", "dbghelp.dll", "ijl15.dll",
    "unicows.dll", "divxdecoder.dll", "scan.dll", "binkw32.dll", "mss32.dll",
    "twloader.dll",
}

# SUNI 模组组：S=SuperWoWhook, U=UnitXP_SP3, N=nampower, I=Interact（用户自定义简称）
SUNI_MODS = {"superwowhook.dll", "unitxp_sp3.dll", "nampower.dll", "interact.dll"}

# 增强模组加载顺序（写入 dlls.txt 用；客户端 twloader.dll 与内置注入器按此载入）。
# 顺序与「模组包原版 dlls.txt」完全一致——这是本机实测可用的顺序：
# 同一 VanillaFixes.exe + 同一组 DLL，用原版清单全部加载成功（2026-10-24 验证）。
MOD_DLL_ORDER = ["no1600x1200.dll", "UnitXP_SP3.dll", "VfPatcher.dll", "Interact.dll",
                 "SuperWoWhook.dll", "transmogfix.dll", "nampower.dll",
                 "WoWTranslate.dll", "wsloot.dll"]


def _write_dlls_txt(path, lines):
    """写 dlls.txt：**二进制模式 + LF 换行**，与模组包原版逐字节一致。
    Windows 文本模式会把 \n 转成 \r\n；VanillaFixes 用 LoadLibraryW 注入
    dlls.txt 里的 DLL，文件名一旦带上 \r 就可能加载失败(no module handle)。
    实测：模组包原版 dlls.txt(LF) + 本机 VanillaFixes.exe 全部模组正常加载。"""
    data = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
    with open(path, "wb") as f:
        f.write(data)


# ================= 字体模块 =================
# 字体源目录：整个文件夹会复制到游戏根目录的 Fonts（WoW 客户端字体目录）。
# 默认空 = 不预设开发机路径；新电脑从蓝奏云下载缓存取（_builtin_sources_with_cache），
# 用户也可在字体页/配置里手动指定。
DEFAULT_FONT_SRC = ""
FONTS_DIRNAME = "Fonts"

# 常见客户端字体文件用途说明（小写文件名 → 用途；未列出的给通用说明）
FONT_INFO = {
    "arialn.ttf":   "全局基础字体：聊天、物品提示、目标框体等大部分界面文字",
    "frizqt__.ttf": "客户端主字体：任务文本、菜单、对话框等核心界面文字",
    "morpheus.ttf": "信件与书本字体：邮件、书页、卷轴上的文字",
    "skurri.ttf":   "伤害数字字体：战斗中飘出的伤害/治疗数值",
    "blei00d.ttf":  "补充字体：背包、徽记等部分界面元素文字",
    "ariblk.ttf":   "粗体标题字体：面板标题、等级数字等加粗文字",
    "babsaml__.ttf":"备用正文字体：部分旧界面文字",
    "bbsimsun.ttf": "中文宋体：繁中界面备用字体",
    "fzbwjw.ttf":   "思源黑体（Noto Sans SC）：任务书卷、信件类文字（美化）",
    "fzjzjw.ttf":   "思源黑体（Noto Sans SC）：界面通用中文字体（美化）",
    "fzlbjw.ttf":   "思源黑体（Noto Sans SC）：标题、书卷类文字（美化）",
    "fzxhjw.ttf":   "思源黑体（Noto Sans SC·细黑）：聊天与界面小字（美化）",
    "fzxhlw.ttf":   "思源黑体（Noto Sans SC·等线）：聊天与界面小字（美化）",
}


def fonts_dst(target):
    """客户端根目录下的 Fonts 文件夹（WoW 客户端字体目录）"""
    return os.path.join(client_root_of(target), FONTS_DIRNAME)


def _count_files(path):
    """递归统计文件夹里的文件数"""
    n = 0
    for _r, _d, files in os.walk(path):
        n += len(files)
    return n


def install_fonts(target, font_src, log):
    """把字体文件夹整体装入游戏根目录的 Fonts（覆盖式）。
    首次安装时若客户端已有 Fonts，先整体备份（清理还原时恢复原样）；
    后续安装时，与客户端已有字体冲突的文件先逐个备份，再覆盖，不丢失用户原有字体。
    返回装入/更新的文件数。"""
    if not font_src or not os.path.isdir(font_src):
        log("[字体] ⚠ 字体源目录无效，跳过：" + str(font_src))
        return 0
    dst = fonts_dst(target)
    cfg = load_config()
    n = 0
    try:
        os.makedirs(dst, exist_ok=True)
        sel = _get_selection("fonts")
        srcset = set(os.listdir(font_src))
        # 安装前处理规则：
        #   ① 资源包里有的（本程序装入的）→ 直接删除旧文件，随后按勾选重拷
        #   ② 客户端原有的（不在资源包里）→ 挪入 WowAbak\字体备份_原有（移除字体时恢复并删除备份）
        if os.path.isdir(dst):
            npack = 0
            norig = 0
            bdir = _original_backup_dir(target, "字体备份")
            for e in os.listdir(dst):
                p = os.path.join(dst, e)
                if e in srcset:
                    if _fast_delete(p):
                        npack += 1
                    continue
                if _move_to_backup(p, bdir, log, "字体"):
                    norig += 1
            if npack:
                log("[字体] 已删除旧包字体 " + str(npack) + " 项（随后按勾选重装）")
            if norig:
                log("[备份] 客户端原有（非资源包）字体 " + str(norig)
                    + " 项已备份到 WowAbak\\字体备份_原有（移除字体时恢复）")
        n_skip = 0
        for e in sorted(os.listdir(font_src)):
            sp = os.path.join(font_src, e)
            dp = os.path.join(dst, e)
            if os.path.isdir(sp):
                if not sel.get(e.lower(), True):
                    n_skip += 1
                    continue
                shutil.copytree(sp, dp, dirs_exist_ok=True)
                n += _count_files(sp)
            elif os.path.isfile(sp):
                if not e.lower().endswith(_FONT_EXTS):
                    continue
                if not sel.get(e.lower(), True):
                    n_skip += 1
                    continue
                shutil.copy2(sp, dp)
                n += 1
        if n_skip:
            log("[字体] 按勾选跳过 " + str(n_skip) + " 个未勾选字体（未丢失，重新勾选可装回）")
        if n:
            log("[字体] 已装入/更新 " + str(n) + " 个字体文件 → 游戏目录\\Fonts")
        else:
            log("[字体] 没有需要装入的字体（勾选为空或均已是最新）")
    except Exception as ex:
        log("[字体] 装入失败：" + str(ex))
    return n


def remove_fonts(target, log):
    """移除字体：删掉资源包装入的字体 → 恢复客户端原有（WowAbak\字体备份_原有）→ 删除该备份。
    Fonts 清空后连同目录一并移除。返回是否有变化。"""
    dst = fonts_dst(target)
    src = _kind_dst("fonts")
    pack_names = set(os.listdir(src)) if src and os.path.isdir(src) else set()
    n = 0
    if os.path.isdir(dst):
        for e in os.listdir(dst):
            if e in pack_names and _fast_delete(os.path.join(dst, e)):
                n += 1
    if n:
        log("[还原] 已移除资源包装入的字体 " + str(n) + " 项")
    n2 = _restore_original_backup(target, "字体备份", dst, log)
    if os.path.isdir(dst) and not os.listdir(dst):
        _fast_delete(dst)
        log("[还原] 字体已移除，空目录 Fonts 一并删除")
    # 移除自定义导入的字体（install_state.custom.fonts）
    if os.path.isabs(dst) and os.path.isdir(dst):
        for _nm in _custom_imports().get("fonts", []):
            _p = os.path.join(dst, _nm)
            if os.path.isfile(_p) or os.path.isdir(_p):
                if _fast_delete(_p):
                    n += 1
                    log("[还原] 已移除自定义字体 " + _nm)
        _clear_custom("fonts")
    if n == 0 and n2 == 0 and not os.path.isdir(dst):
        return False
    return True


def ensure_mods_loaded(target, log):
    """把客户端根已存在的增强模组写进 dlls.txt（客户端 twloader.dll 据此载入），
    保留原有条目(如 twdiscord.dll)，写前备份原 dlls.txt。返回 (ok, msg)。"""
    root = client_root_of(target) if target else ""
    if not root or not os.path.isdir(root):
        return False, "客户端路径无效"
    path = os.path.join(root, "dlls.txt")
    existing = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            existing = [l.strip() for l in f if l.strip()]
    # 只收客户端里真实存在、未被禁用的模组 DLL（按推荐顺序）
    present = [n for n in MOD_DLL_ORDER if os.path.isfile(os.path.join(root, n))]
    if not present:
        return False, "客户端根目录没有可载入的增强模组（先导入模组包）"
    keep = [e for e in existing if e not in MOD_DLL_ORDER]  # 保留 twdiscord.dll 等
    merged = keep + [n for n in present if n not in keep]
    if merged == existing:
        return True, "dlls.txt 已包含全部模组，无需改动"
    if os.path.isfile(path):
        # dlls.txt 备份取消：初始基线已存 config.baseline_dllstxt（还原时据此恢复），
        # 不再额外生成带时间戳的模组备份夹。
        pass
    _write_dlls_txt(path, merged)
    log("[模组] 已写入 dlls.txt：" + ", ".join(present))
    return True, "ok"

# ================= 持久化安装：一键安装 / 手动清理还原 =================
# 设计（2026-10-26 起）：用工具配置组件 → 把模组+插件+字体装入客户端并保留；
#       关闭工具不会卸载/删除，下次打开显示「已安装」直接复用；缓存同样留盘。
#       仅「清理还原」按钮会手动移除本次装入的内容（先备份再移除），恢复干净客户端。
SESSION_BASELINE_PREFIX = "Blizzard_"  # 客户端自带插件目录名前缀（还原时保留）


def _original_backup_dir(target, tag):
    """客户端原有内容的固定备份目录：WowAbak\\<tag>_原有。
    仅返回路径、不预建目录——只有实际挪入客户端原有内容时才由 _move_to_backup 创建，
    避免没有原有内容时生成空备份夹。移除时恢复并把目录删掉。"""
    return os.path.join(backups_base(target), tag + "_原有")


def _restore_original_backup(target, tag, dst, log):
    """把 WowAbak 下 <tag>_原有 及旧模型遗留的时间戳备份夹（<tag>_YYYYMMDD_HHMMSS，
    如 模组备份_20261031_005524）里的客户端原有内容恢复到 dst，然后删除这些备份夹
    （不留空备份夹）。返回恢复的项数。"""
    bb = backups_base(target)
    # 待恢复夹顺序：新模型 <tag>_原有 优先，旧模型时间戳夹随后
    restore_dirs = []
    ts_dirs = []
    if os.path.isdir(bb):
        for name in os.listdir(bb):
            full = os.path.join(bb, name)
            if not os.path.isdir(full):
                continue
            if name == tag + "_原有":
                restore_dirs.append(full)
            elif re.match(r"^" + re.escape(tag) + r"_\d{8}_\d{6}$", name):
                ts_dirs.append(full)
    restore_dirs = restore_dirs + ts_dirs
    n = 0
    for bdir in restore_dirs:
        for e in os.listdir(bdir):
            s = os.path.join(bdir, e)
            d2 = os.path.join(dst, e)
            try:
                # 恢复若与 dst 已有同名项冲突：原 dst 先丢回收站再覆盖（不丢数据）
                if os.path.exists(d2):
                    _to_trash(d2)
                os.makedirs(os.path.dirname(d2) or dst, exist_ok=True)
                shutil.move(s, d2)
                n += 1
            except Exception as ex:
                log("[恢复失败] " + e + "：" + str(ex))
        # 用完即删这些备份夹（空夹直接删；有残留项说明上面 move 失败，整夹清掉避免遗留空/脏备份夹）
        try:
            if os.path.isdir(bdir):
                if not os.listdir(bdir):
                    os.rmdir(bdir)
                else:
                    safe_rmtree(bdir)
                log("[备份] 客户端原有内容已恢复，WowAbak\\" + os.path.basename(bdir) + " 已删除")
        except Exception:
            pass
    return n


def _fast_delete(path):
    """会话还原路径专用：彻底删除（永久删除，不挪回收区——用户要求）。
    调用方都在后台线程（关窗后台/清理还原线程）里，同步删除不阻塞界面。"""
    try:
        if os.path.isfile(path) or os.path.islink(path):
            os.remove(path)
            return True
        if os.path.isdir(path):
            shutil.rmtree(path)
            return True
    except Exception:
        return False
    return False


def kill_game(log):
    """结束游戏进程（WoW.exe / VanillaFixes.exe）"""
    killed = []
    for img in ("WoW.exe", "VanillaFixes.exe"):
        try:
            r = _run_hidden(["taskkill", "/F", "/IM", img],
                            capture_output=True, timeout=10,
                            encoding="utf-8", errors="replace")
            if r.returncode == 0:
                killed.append(img)
                log("[游戏] 已结束进程 " + img)
        except Exception as ex:
            log("[游戏] 结束 " + img + " 异常：" + str(ex))
    if not killed:
        log("[游戏] 没有在运行的游戏进程")
    return killed


def revert_overlay(target, log, kill=True, backup=True):
    """还原到干净客户端：结束游戏 → 移除会话装入的插件/模组 → 恢复 dlls.txt。
    backup=True（默认，遗留接口用）：被移除项先挪进 WowAbak 备份再移除；
    backup=False（「清理还原」专用）：本程序装入的组件直接移除，不再备份。"""
    if not target:
        return False, "未设置游戏路径"
    root = client_root_of(target)
    addons = normalize_addons_path(target, create=False)
    if kill:
        kill_game(log)
    _remove_custom_all(target, log)   # 先移除自定义导入的模组/插件/字体
    backup_dir = _backup_dir_for(target, "清理还原") if backup else None

    def _remove(item, label, name_for_log=None):
        """backup 模式=挪进 WowAbak；直删模式=彻底移除。返回是否移除成功。"""
        if not os.path.exists(item):
            return False
        if backup:
            return _move_to_backup(item, backup_dir, log, label)
        try:
            if not _fast_delete(item):
                raise OSError("delete failed")
            log("[移除] " + label + " " + (name_for_log or os.path.basename(item)) + "（已彻底移除）")
            return True
        except Exception as ex:
            log("[移除失败] " + (name_for_log or os.path.basename(item)) + "：" + str(ex))
            return False

    # 1) 移除本程序装入的插件：资源包里的全部移除（含 Blizzard_ 系修复插件）；
    #    客户端自带（不在资源包里）的 Blizzard_* 保留；跳过 _ 内部目录
    removed = 0
    pack_names = set()
    try:
        _psrc = _kind_dst("addons")
        if _psrc and os.path.isdir(_psrc):
            pack_names = {e.lower() for e in os.listdir(_psrc)
                          if os.path.isdir(os.path.join(_psrc, e))}
    except Exception:
        pass
    if addons and os.path.isdir(addons):
        for e in os.listdir(addons):
            if e.startswith("_"):
                continue
            if e.startswith(SESSION_BASELINE_PREFIX) and e.lower() not in pack_names:
                continue  # 客户端自带插件（不在资源包内）保留
            if _remove(os.path.join(addons, e), "插件"):
                removed += 1
        # 客户端原本没有 Interface/AddOns 时不留空目录：清空后连目录一起移除
        try:
            if not os.listdir(addons):
                _fast_delete(addons)
                log("[还原] 插件目录已空，AddOns 一并移除（客户端原本没有该目录）")
                iface = os.path.dirname(addons)
                if iface and os.path.isdir(iface) and not os.listdir(iface):
                    _fast_delete(iface)
                    log("[还原] 空目录 Interface 一并移除")
        except Exception:
            pass
    if backup:
        log("[还原] 移除会话插件 " + str(removed) + " 个（已备份到 WowAbak，可捞回；保留客户端自带且不在资源包内的插件）")
    else:
        log("[还原] 移除已装插件 " + str(removed) + " 个（彻底移除，不备份；保留客户端自带且不在资源包内的插件）")
    # 恢复客户端原有（非资源包）插件，然后删除该备份
    _addons_dst = addons or os.path.join(root, "Interface", "AddOns")
    _restore_original_backup(target, "插件备份", _addons_dst, log)
    # 恢复客户端原有（非资源包）模组文件，然后删除该备份
    _restore_original_backup(target, "模组备份", root, log)
    # 2) 移除本程序装入的模组 DLL + 老版 VanillaFixes.exe 残留
    mod_removed = 0
    for name in MOD_DLL_ORDER + ["VanillaFixes.exe"]:
        p = os.path.join(root, name)
        if os.path.isfile(p):
            if _remove(p, "模组"):
                mod_removed += 1
    log("[还原] 移除模组文件 " + str(mod_removed) + " 个"
        + ("（已备份到 WowAbak）" if backup else "（彻底移除，不备份）"))
    # 2.5) 移除会话装入的字体文件夹（客户端原有 Fonts 有备份则恢复原样）
    remove_fonts(target, log)
    # 3) 恢复 dlls.txt 到干净基线
    cfg = load_config()
    base = cfg.get("baseline_dllstxt")
    if base is not None:
        try:
            _write_dlls_txt(os.path.join(root, "dlls.txt"), base.splitlines())
            log("[还原] dlls.txt 已恢复初始内容")
        except Exception as ex:
            log("[还原] dlls.txt 恢复失败：" + str(ex))
    if cfg.get("session_applied"):
        cfg["session_applied"] = False
        save_config(cfg)
    return True, "已恢复到初始（干净）状态"


def _game_running():
    """游戏是否在跑（WoW.exe）"""
    try:
        r = _run_hidden(["tasklist", "/FI", "IMAGENAME eq WoW.exe"],
                        capture_output=True, timeout=10,
                        encoding="utf-8", errors="replace")
        return "WoW.exe" in r.stdout
    except Exception:
        return False


# ================= 启动进度（首页「启动游戏」进度条 + 分步提示用） =================
_progress_lock = threading.Lock()
_progress = {"pct": 0, "stage": "", "msg": "空闲", "done": False, "steps": [], "log": []}

# 操作历史（跨操作持久，带时间戳）：记录环境检测/启动游戏/清理还原/装入/移除等关键操作，
# 前端日志区先显示历史再追加当次日志，用户能看到之前做过什么
_HIST_LOCK = threading.Lock()
_HIST = []


def _hist(msg):
    with _HIST_LOCK:
        _HIST.append(time.strftime("[%H:%M:%S] ") + str(msg))
        if len(_HIST) > 2000:
            del _HIST[:len(_HIST) - 2000]


def _reset_progress():
    with _progress_lock:
        _progress.update({"pct": 0, "stage": "", "msg": "正在准备…",
                          "done": False, "steps": [], "log": []})


def _set_progress(pct=None, stage=None, msg=None, done=None, step=None, log=None):
    """更新启动进度；step=已完成的阶段名（模组/插件/字体/启动）；
    log=追加一行日志（前端轮询时随进度逐步显示，不等结束一次性吐出）。"""
    with _progress_lock:
        if pct is not None:
            _progress["pct"] = max(0, min(100, int(pct)))
        if stage is not None:
            _progress["stage"] = stage
        if msg is not None:
            _progress["msg"] = msg
        if done is not None:
            _progress["done"] = bool(done)
        if step and step not in _progress["steps"]:
            _progress["steps"].append(step)
        if log:
            _progress["log"].append(time.strftime("[%H:%M:%S] ") + str(log))


def get_progress():
    with _progress_lock:
        snap = {k: (list(v) if isinstance(v, list) else v) for k, v in _progress.items()}
    with _HIST_LOCK:
        snap["hist"] = list(_HIST)
    return snap


# ================= 持久化安装：冲突备份 / 幂等检测 / 缓存管理 =================
# 模型变更（2026-10-26）：从「会话覆盖层（退出即还原删缓存）」改为「持久化安装」。
# 关闭工具后模组/插件/字体与下载缓存都保留；配置组件幂等（已装不重复装）；
# 安装前对冲突项先备份；下载缓存长期(默认30天)未使用自动清理。

def _backup_dir_for(target, tag):
    """生成时间戳备份目录（落在游戏目录的 WowAbak 下）。"""
    bb = backups_base(target)
    d = os.path.join(bb, tag + "_" + time.strftime("%Y%m%d_%H%M%S"))
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def _move_to_backup(item_path, backup_dir, log, label=""):
    """把已存在的目标项（文件或目录）挪到备份目录，避免被覆盖/删除时丢失。
    返回是否发生了备份。"""
    if not os.path.exists(item_path):
        return False
    try:
        os.makedirs(backup_dir, exist_ok=True)
        name = os.path.basename(item_path)
        bak = os.path.join(backup_dir, name)
        if os.path.exists(bak):
            _to_trash(bak)
        shutil.move(item_path, bak)
        log("[备份] " + (label and (label + " ") or "") + name
            + " → WowAbak\\" + os.path.basename(backup_dir))
        return True
    except Exception as ex:
        log("[备份失败] " + name + "：" + str(ex))
        return False


def _safe_install_file(src, dst, backup_dir, log, label=""):
    """安全装入单个文件：目标已存在且与源不同 → 先备份再覆盖；相同则跳过。"""
    if not os.path.isfile(src):
        return False
    if os.path.exists(dst):
        try:
            if os.path.getsize(src) == os.path.getsize(dst):
                with open(src, "rb") as a, open(dst, "rb") as b:
                    if a.read() == b.read():
                        return False  # 已相同，跳过
        except Exception:
            pass
        _move_to_backup(dst, backup_dir, log, label)
    try:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except Exception as ex:
        log("[装入失败] " + os.path.basename(dst) + "：" + str(ex))
        return False


def _kind_sig(kind):
    """某类资源的安装签名：缓存 .ok 内容 + 影响安装的关键选择/版本。
    签名变化（重下载/改勾选/插件更新）即视为需重新安装。"""
    d = _kind_dst(kind)
    sig = ""
    if d:
        okf = os.path.join(d, ".ok")
        if os.path.isfile(okf):
            try:
                sig += open(okf, "r", encoding="utf-8", errors="replace").read()
            except Exception:
                pass
    if kind == "mods":
        sig += "|sel=" + json.dumps(get_mod_selection(), sort_keys=True,
                                    ensure_ascii=False)
    elif kind == "addons":
        try:
            vers = _load_versions()
            sig += "|p=" + json.dumps(vers, sort_keys=True, ensure_ascii=False)
        except Exception:
            pass
        sig += "|sel=" + json.dumps(_get_selection("addons"), sort_keys=True,
                                    ensure_ascii=False)
    elif kind == "fonts":
        sig += "|sel=" + json.dumps(_get_selection("fonts"), sort_keys=True,
                                    ensure_ascii=False)
    return sig


def _kind_on_disk(target, kind):
    """粗略校验某类资源是否真的装在盘上（用于幂等跳过判断）。"""
    if not target:
        return False
    if kind == "mods":
        root = client_root_of(target)
        sel = get_mod_selection()
        info = list_package_mods(target, _kind_dst("mods"))
        chosen = [m for m in info["mods"]
                  if sel.get(m["name"].lower(), True) and not m["missing"]]
        if not chosen:
            return True
        return all(os.path.isfile(os.path.join(root, m["name"])) for m in chosen) \
            and os.path.isfile(os.path.join(root, "dlls.txt"))
    if kind == "addons":
        src = _kind_dst("addons")
        addons = normalize_addons_path(target, create=False)
        if not (src and os.path.isdir(src) and addons and os.path.isdir(addons)):
            return False
        sel = _get_selection("addons")
        names = [e for e in os.listdir(src)
                 if os.path.isdir(os.path.join(src, e)) and not e.startswith("_")]
        names = [e for e in names if _addon_locked(e) or sel.get(e.lower(), True)]
        if not names:
            return True
        return all(os.path.isdir(os.path.join(addons, e)) for e in names)
    if kind == "fonts":
        dst = fonts_dst(target)
        if not os.path.isdir(dst):
            return False
        sel = _get_selection("fonts")
        d = _kind_dst("fonts")
        if not (d and os.path.isdir(d)):
            return False
        need = [e for e in os.listdir(d)
                if e.lower().endswith(_FONT_EXTS) and sel.get(e.lower(), True)]
        return all(os.path.isfile(os.path.join(dst, e)) for e in need)
    return False


def _mark_installed(kind, log=None):
    cfg = load_config()
    st = cfg.setdefault("install_state", {})
    st[kind] = {"done": True, "sig": _kind_sig(kind), "ts": time.time()}
    save_config(cfg)
    _touch_cache(kind)


def _touch_cache(kind):
    """记录某类缓存最近使用时间（供 30 天未用自动清理判断）。"""
    try:
        cfg = load_config()
        cu = cfg.setdefault("cache_lastused", {})
        cu[kind] = time.time()
        save_config(cfg)
    except Exception:
        pass


def cache_gc():
    """清理长期未使用的下载缓存（默认 30 天）。后台启动调用，不阻塞。
    只删 resources/ 下某类资源的缓存目录；不碰已装入游戏目录的文件。"""
    try:
        cfg = load_config()
        cset = cfg.get("cache") or {}
        if not cset.get("auto_clean", True):
            return
        keep = int(cset.get("keep_days", 30))
        if keep <= 0:
            return
        now = time.time()
        cu = cfg.get("cache_lastused", {}) or {}
        for kind in _LANZOU_KINDS:
            last = cu.get(kind, 0)
            if not last:
                continue
            if now - last < keep * 86400:
                continue
            d = _kind_dst(kind)
            if d and os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                print("[缓存清理] 已删除 %s 缓存（超过 %d 天未使用）：%s"
                      % (kind, keep, d))
    except Exception as ex:
        print("[缓存清理] 异常：" + str(ex))


def apply_overlay(target, mod_src, addon_src, log, font_src=None):
    """持久化安装：不再先还原，改为幂等 + 冲突备份。
    返回 (ok, summary, status)，status={kind:(是否本次新装, 文案)}。"""
    if not target:
        return False, "未设置游戏路径", {}
    root = client_root_of(target)
    addons = normalize_addons_path(target, create=True)
    # 0) 游戏在跑会占用已装入的 DLL（覆盖/删除都会失败）→ 先结束游戏
    if _game_running():
        kill_game(log)
    # 1) 记录干净基线 dlls.txt（首次，还原时恢复用）
    cfg = load_config()
    dlls_path = os.path.join(root, "dlls.txt")
    if "baseline_dllstxt" not in cfg:
        try:
            base = open(dlls_path, encoding="utf-8", errors="replace").read() if os.path.isfile(dlls_path) else ""
        except Exception:
            base = ""
        cfg["baseline_dllstxt"] = base
        save_config(cfg)
        log("[基线] 已记录初始 dlls.txt")
    status = {}
    istate = cfg.get("install_state", {})
    # 2) 装模组（按模组页勾选；冲突先备份；已装且签名一致则跳过）
    _set_progress(5, "模组", "模组安装中…")
    if mod_src and os.path.isdir(mod_src):
        sel = get_mod_selection()
        info = list_package_mods(target, mod_src)
        chosen = [m for m in info["mods"]
                  if sel.get(m["name"].lower(), True) and not m["missing"]]
        sig = _kind_sig("mods")
        if istate.get("mods", {}).get("done") and istate.get("mods", {}).get("sig") == sig \
                and _kind_on_disk(target, "mods"):
            log("[模组] 已安装，无需重复安装")
            status["mods"] = (False, "已安装(跳过)")
            _touch_cache("mods")
        else:
            # 安装前处理：资源包里的（本程序装的）直接删旧，随后重装；
            # 客户端原有的（不在资源包里）挪入 WowAbak\模组备份_原有（移除模组时恢复并删除备份）
            bdir = _original_backup_dir(target, "模组备份")
            pack_names = {m["name"] for m in info["mods"]}
            pre = [n for n in dict.fromkeys(list(MOD_DLL_ORDER) + [m["name"] for m in chosen])
                   if os.path.exists(os.path.join(root, n))]
            npack = norig = 0
            for n in pre:
                p = os.path.join(root, n)
                if n in pack_names:
                    if _fast_delete(p):
                        npack += 1
                elif _move_to_backup(p, bdir, log, "模组"):
                    norig += 1
            if npack:
                log("[模组] 已删除旧包模组 " + str(npack) + " 个（随后重装）")
            if norig:
                log("[备份] 客户端原有（非资源包）模组文件 " + str(norig)
                    + " 个已备份到 WowAbak\\模组备份_原有（移除模组时恢复）")
            nmod = 0
            for i, m in enumerate(chosen):
                if _safe_install_file(os.path.join(mod_src, m["name"]),
                                     os.path.join(root, m["name"]), bdir, log, "模组"):
                    nmod += 1
                _set_progress(5 + 25 * (i + 1) // max(1, len(chosen)))
            if chosen:
                log("[模组] 模组加载已内置于本程序，将自动注入 VfPatcher.dll、nampower.dll")
            skipped = len(info["mods"]) - len(chosen)
            log("[模组] 从「" + os.path.basename(mod_src.rstrip("\\/")) + "」装入 " + str(nmod)
                + " 个文件（按勾选，跳过 " + str(skipped) + " 个未勾选）")
            _set_progress(32, "模组", "模组安装完毕，正在写入加载配置…")
            _mark_installed("mods", log)
            status["mods"] = (True, "已安装(%d个)" % nmod)
    else:
        log("[模组] ⚠ 源目录无效，跳过：" + str(mod_src))
        _set_progress(32, "模组", "无有效模组源，跳过模组")
        status["mods"] = (False, "源无效")
    # 3) 写 dlls.txt 让模组生效（放在插件之前：模组这一步先完整收尾）
    ensure_mods_loaded(target, log)
    _set_progress(38, "插件", "模组安装完毕，插件安装中…", step="模组")
    # 4) 装插件（冲突先备份；已装且签名一致则跳过）
    nadd = 0
    src_addons = None
    if addon_src:
        b = os.path.basename(addon_src.rstrip("\\/")).lower()
        if b == "addons":
            src_addons = addon_src
        elif os.path.isdir(os.path.join(addon_src, "AddOns")):
            src_addons = os.path.join(addon_src, "AddOns")
    if src_addons and os.path.isdir(src_addons):
        sig = _kind_sig("addons")
        if istate.get("addons", {}).get("done") and istate.get("addons", {}).get("sig") == sig \
                and _kind_on_disk(target, "addons"):
            log("[插件] 已安装，无需重复安装")
            status["addons"] = (False, "已安装(跳过)")
            _touch_cache("addons")
        else:
            # 安装前处理：资源包里的（本程序装的）直接删旧，随后按勾选重装；
            # 客户端原有的（不在资源包里）挪入 WowAbak\插件备份_原有（移除插件时恢复并删除备份）
            bdir = _original_backup_dir(target, "插件备份")
            pack_names = {e.lower() for e in os.listdir(src_addons)
                          if os.path.isdir(os.path.join(src_addons, e))}
            npack = norig = 0
            if os.path.isdir(addons):
                for e in os.listdir(addons):
                    if e.startswith("_"):
                        continue
                    p = os.path.join(addons, e)
                    if e.lower() in pack_names:
                        if _fast_delete(p):
                            npack += 1
                    elif _move_to_backup(p, bdir, log, "插件"):
                        norig += 1
            if npack:
                log("[插件] 已删除旧包插件 " + str(npack) + " 个（随后按勾选重装）")
            if norig:
                log("[备份] 客户端原有（非资源包）插件 " + str(norig)
                    + " 个已备份到 WowAbak\\插件备份_原有（移除插件时恢复）")
            # 按插件页勾选过滤：只装勾选的（库插件/客户端前置锁定必装）；未勾选已装的已在上面备份挪走=卸载
            asel = _get_selection("addons")
            all_dirs = [e for e in sorted(os.listdir(src_addons))
                        if os.path.isdir(os.path.join(src_addons, e)) and not e.startswith("_")]
            dirs = [e for e in all_dirs if _addon_locked(e) or asel.get(e.lower(), True)]
            n_skip = len(all_dirs) - len(dirs)
            nadd = 0
            for i, e in enumerate(dirs):
                try:
                    os.makedirs(os.path.dirname(os.path.join(addons, e)) or ".", exist_ok=True)
                    shutil.copytree(os.path.join(src_addons, e), os.path.join(addons, e),
                                    dirs_exist_ok=True)
                    nadd += 1
                except Exception as ex:
                    log("[装入失败] " + e + "：" + str(ex))
                _set_progress(38 + 42 * (i + 1) // max(1, len(dirs)))
            if n_skip:
                log("[插件] 按勾选跳过 " + str(n_skip) + " 个未勾选插件")
            log("[插件] 从「" + os.path.basename(addon_src.rstrip("\\/")) + "」装入 " + str(nadd)
                + " 个（按勾选）")
            _set_progress(82, "字体", "插件安装完毕，字体安装中…", step="插件")
            _mark_installed("addons", log)
            status["addons"] = (True, "已安装(%d个)" % nadd)
    else:
        log("[插件] ⚠ 源目录无效，跳过：" + str(addon_src))
        _set_progress(82, "字体", "无有效插件源，跳过插件", step="插件")
        status["addons"] = (False, "源无效")
    # 5) 装字体（冲突先备份；已装且签名一致则跳过）
    font_src = font_src or load_config().get("font_src") or DEFAULT_FONT_SRC
    dst_fonts = fonts_dst(target)
    if font_src and os.path.isdir(font_src):
        sig = _kind_sig("fonts")
        if istate.get("fonts", {}).get("done") and istate.get("fonts", {}).get("sig") == sig \
                and _kind_on_disk(target, "fonts"):
            log("[字体] 已安装，无需重复安装")
            status["fonts"] = (False, "已安装(跳过)")
            _touch_cache("fonts")
        else:
            nfont = install_fonts(target, font_src, log)
            _mark_installed("fonts", log)
            status["fonts"] = (True, "已安装(%d文件)" % max(0, nfont))
    else:
        log("[字体] ⚠ 字体源目录无效，跳过：" + str(font_src))
        status["fonts"] = (False, "源无效")
    _set_progress(95, "字体", "字体安装完毕", step="字体")
    cfg = load_config()
    cfg["session_applied"] = True
    save_config(cfg)
    _set_progress(98, "完成", "安装完成，正在启动游戏…")
    return True, "安装完成：模组+插件+字体", status


def _overlay_present(target):
    """检测客户端当前是否装有会话覆盖层（非自带插件目录或模组 DLL）"""
    if not target:
        return False
    root = client_root_of(target)
    addons = normalize_addons_path(target, create=False)
    if addons and os.path.isdir(addons):
        for e in os.listdir(addons):
            if e.startswith(SESSION_BASELINE_PREFIX) or e.startswith("_"):
                continue
            if os.path.isdir(os.path.join(addons, e)):
                return True
    for name in MOD_DLL_ORDER + ["VanillaFixes.exe"]:
        if os.path.isfile(os.path.join(root, name)):
            return True
    # 字体文件夹（会话装入；客户端原有 Fonts 已备份，不算覆盖层）
    if os.path.isdir(fonts_dst(target)) and not load_config().get("fonts_backup"):
        return True
    return False


def _install_flags(target):
    """三项安装状态自检（供首页与启动前检查）：模组/插件/字体是否都真实在盘上。
    返回 (mods, addons, fonts)。全部为 True 才算『已安装』、才允许启动游戏。"""
    if not target:
        return False, False, False
    addons = normalize_addons_path(target, create=False)
    ai = False
    if addons and os.path.isdir(addons):
        for e in os.listdir(addons):
            if e.startswith(SESSION_BASELINE_PREFIX) or e.startswith("_"):
                continue
            if os.path.isdir(os.path.join(addons, e)):
                ai = True
                break
    root = client_root_of(target)
    mi = any(os.path.isfile(os.path.join(root, n))
             for n in MOD_DLL_ORDER + ["VanillaFixes.exe"])
    cfg = load_config()
    # 字体已装：Fonts 文件夹存在即视为可用（含我们装入的 / 客户端原有的）；
    # 另以 install_state.fonts.done 为权威记录（我们装入过即算已装）。
    fi = os.path.isdir(fonts_dst(target)) or \
        bool((cfg.get("install_state", {}) or {}).get("fonts", {}).get("done"))
    return mi, ai, fi


_teardown_done = False


def _flush_stdio():
    """os._exit 会跳过缓冲区刷新；无窗口模式下 stdout 重定向进 run.log，
    退出前必须手动 flush，否则最后的日志会丢在缓冲区里。"""
    for _name in ("stdout", "stderr"):
        try:
            getattr(sys, _name).flush()
        except Exception:
            pass


def _run_hidden(cmd, **kw):
    """跑子进程且不弹控制台窗口（Windows: CREATE_NO_WINDOW）。
    taskkill/curl/7z 等控制台程序从无窗口 exe 启动时会闪一下黑窗，用此彻底消除。"""
    if sys.platform == "win32":
        kw.setdefault("creationflags", 0x08000000)
    return subprocess.run(cmd, **kw)


def _popen_hidden(cmd, **kw):
    """启动子进程且不弹控制台窗口（同上）。"""
    if sys.platform == "win32":
        kw.setdefault("creationflags", 0x08000000)
    return subprocess.Popen(cmd, **kw)


def _persist_target(t):
    """install/quick_play 成功后把用到的游戏路径写回 config，
    作为 _teardown 的兜底（UI 用内存里的路径安装、未必持久化过）。
    config.target 统一存游戏根目录（与 WoW.exe 同级）。"""
    try:
        nt = _to_root(t) if t else ""
        if nt and os.path.isdir(nt):
            cfg = load_config()
            if cfg.get("target") != nt:
                cfg["target"] = nt
                save_config(cfg)
    except Exception:
        pass


def _teardown():
    """工具退出（持久化模型）：【不再】还原客户端、不再杀游戏、不再删缓存/备份。
    已安装的模组/插件/字体与下载缓存都保留，下次打开直接复用。仅写一条退出日志。"""
    global _teardown_done
    if _teardown_done:
        return
    _teardown_done = True
    try:
        with open(RESTORE_LOG, "w", encoding="utf-8") as f:
            f.write("工具退出（持久化模式）@ " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
            f.write("已安装的模组/插件/字体与下载缓存均保留，下次打开直接复用。\n")
            f.write("如需恢复干净客户端，请打开界面点「清理还原」。\n")
    except Exception:
        pass


def _cleanup_restore(target, log):
    """手动清理还原（三步，2026-10-27 用户定稿）：
    ① 结束游戏并彻底移除已装的模组/插件/字体（不备份）；
    ② 从 WowAbak 各类备份中还原客户端原有内容（取每类最早的时间戳备份 = 安装前原始状态）；
    ③ 清空删除整个 WowAbak 备份夹（使命完成）。
    不删下载缓存（持久化模型，缓存留盘复用）。"""
    if not target:
        return False, "未设置游戏路径"
    if _game_running():
        kill_game(log)
    _remove_custom_all(target, log)   # 先移除自定义导入的模组/插件/字体
    revert_overlay(target, log, kill=False, backup=False)  # ① 直删已装组件
    # ② 从 WowAbak 还原客户端原有内容（最早的时间戳备份）
    root = client_root_of(target)
    addons = normalize_addons_path(target, create=False)
    bb = backups_base(target)
    # 同时兼容：新模型固定夹 <tag>_原有 与 旧模型时间戳夹 <tag>_YYYYMMDD_HHMMSS
    pat = re.compile(r"^(模组备份|插件备份|字体备份)(_\d{8}_\d{6}|_原有)$")
    dst_of = {"模组备份": root, "插件备份": addons, "字体备份": fonts_dst(target)}
    label_of = {"模组备份": "模组", "插件备份": "插件", "字体备份": "字体"}
    if os.path.isdir(bb):
        for tag in ("模组备份", "插件备份", "字体备份"):
            src_dirs = [os.path.join(bb, d) for d in sorted(os.listdir(bb))
                        if pat.match(d) and d.startswith(tag)]
            if not src_dirs:
                continue
            dst = dst_of[tag]
            if not dst:
                continue
            n = 0
            for src_dir in src_dirs:
                for e in os.listdir(src_dir):
                    if tag == "模组备份" and re.match(r"^dlls\.\d{8}_\d{6}\.txt$", e):
                        continue   # dlls.txt 走基线恢复机制，不作为散文件回拷进游戏根
                    s, d2 = os.path.join(src_dir, e), os.path.join(dst, e)
                    try:
                        os.makedirs(os.path.dirname(d2) or dst, exist_ok=True)
                        if os.path.exists(d2):
                            _to_trash(d2)   # 恢复冲突不丢数据
                        if os.path.isdir(s):
                            shutil.copytree(s, d2, dirs_exist_ok=True)
                        else:
                            shutil.copy2(s, d2)
                        n += 1
                    except Exception as ex:
                        log("[还原失败] " + e + "：" + str(ex))
            if n:
                log("[还原] 从 WowAbak 还原客户端原有" + label_of[tag] + " " + str(n) + " 项")
        # ③ 备份已完成使命：清空删除整个 WowAbak
        try:
            shutil.rmtree(bb, ignore_errors=True)
            log("[备份] WowAbak 备份夹已清空删除")
        except Exception:
            pass
    cfg = load_config()
    cfg["install_state"] = {}
    cfg["session_applied"] = False
    cfg.pop("fonts_backup", None)   # WowAbak 已删，原 Fonts 备份引用一并作废
    save_config(cfg)
    return True, "已清理还原：已装组件已移除、客户端原有内容已还原、WowAbak 已清空"


# 控制台事件回调必须全程持有引用：ctypes 不会自动保活，回调对象一旦被回收，
# SetConsoleCtrlHandler 注册的就是野指针——点控制台 X 关窗时根本没人处理，还原就不会执行。
_CONSOLE_CB = None


def _install_console_handler():
    """Windows：捕获关闭控制台窗口(X)/关机/注销/Ctrl+C/Ctrl+Break；持久化模型下退出不再还原客户端。"""
    global _CONSOLE_CB
    if sys.platform != "win32":
        return
    try:
        import ctypes
        CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT = 0, 1, 2
        CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT = 5, 6

        def _handler(dwCtrlType):
            try:
                if dwCtrlType in (CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT,
                                  CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
                    print("\n[会话] 收到退出事件，正在退出（已安装内容与缓存均保留）…", flush=True)
                    _teardown()
                    _flush_stdio()
                    # 还原已完成，主动退掉，不等系统默认处理
                    os._exit(0)
            except Exception:
                pass
            return False
        _CONSOLE_CB = ctypes.WINFUNCTYPE(ctypes.c_uint, ctypes.c_uint)(_handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_CONSOLE_CB, True)
    except Exception:
        pass


_FONT_EXTS = (".ttf", ".otf", ".ttc")


def list_package_addons(target):
    """插件包内插件清单（含勾选/锁定/安装状态）。返回 {ok, addons, src, msg}。"""
    d = _kind_dst("addons")
    ta = _to_addons(target)
    sel = _get_selection("addons")
    out = []
    if d and os.path.isdir(d):
        for e in sorted(os.listdir(d), key=str.lower):
            p = os.path.join(d, e)
            if os.path.isdir(p) and not e.startswith("_"):
                locked = _addon_locked(e)
                out.append({"name": e, "locked": locked,
                            "selected": True if locked else bool(sel.get(e.lower(), True)),
                            "installed": bool(ta) and os.path.isdir(os.path.join(ta, e))})
    return {"ok": bool(out), "addons": out, "src": d or "",
            "msg": "" if out else "插件包还没下载（点「应用勾选」会自动下载）"}


def list_package_fonts(target):
    """字体包内字体清单（含勾选/安装状态）。返回 {ok, fonts, src, msg}。"""
    d = _kind_dst("fonts")
    ta = _to_addons(target)
    root = client_root_of(ta) if ta else ""
    fdst = os.path.join(root, "Fonts") if root else ""
    sel = _get_selection("fonts")
    out = []
    if d and os.path.isdir(d):
        for e in sorted(os.listdir(d), key=str.lower):
            p = os.path.join(d, e)
            if os.path.isfile(p) and e.lower().endswith(_FONT_EXTS):
                out.append({"name": e, "locked": False,
                            "selected": bool(sel.get(e.lower(), True)),
                            "installed": bool(fdst) and os.path.isfile(os.path.join(fdst, e))})
    return {"ok": bool(out), "fonts": out, "src": d or "",
            "msg": "" if out else "字体包还没下载（点「装入字体」会自动下载）"}


def list_package_mods(target, src):
    """列出模组包内【可选】模组（游戏自带的核心引擎 DLL 不在此显示）。
    返回 {mods:[{name,group,selected,installed,missing}], loader:{...}, src, ok, msg}。"""
    root = client_root_of(target) if target else ""
    sel = get_mod_selection()
    if not src or not os.path.isdir(src):
        return {"mods": [], "loader": None, "src": src or "", "ok": False,
                "msg": "模组包文件夹不存在：" + str(src)}
    # 包内 dlls.txt 列名（作者推荐的载入清单）
    listed = []
    dlls_txt = os.path.join(src, "dlls.txt")
    if os.path.isfile(dlls_txt):
        try:
            with open(dlls_txt, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    s = line.strip().strip("/")
                    if s:
                        listed.append(s if s.lower().endswith(".dll") else s + ".dll")
        except Exception:
            listed = []
    on_disk = [f for f in os.listdir(src) if f.lower().endswith(".dll")]
    out, seen = [], set()
    for f in sorted(on_disk) + [n for n in listed if n not in on_disk]:
        fl = f.lower()
        if fl in seen:
            continue
        seen.add(fl)
        out.append({
            "name": f,
            "group": "SUNI" if fl in SUNI_MODS else "",
            "selected": sel.get(fl, True),          # 默认勾选
            "installed": bool(root) and os.path.isfile(os.path.join(root, f)),
            "missing": f not in on_disk,            # dlls.txt 列了但包里没有
        })
    # SUNI 优先，其余按名字
    out.sort(key=lambda m: (0 if m["group"] else 1, m["name"].lower()))
    loader = {
        "name": "内置注入器（已取代 VanillaFixes.exe）",
        "installed": True,      # 能力内置在本程序中，恒可用
        "desc": "模组加载已内置进本程序：点「启动游戏」时直接把 VfPatcher.dll / nampower.dll "
                "注入游戏进程，游戏根目录不会再出现 VanillaFixes.exe；其余模组由客户端自带的 "
                "twloader.dll 按 dlls.txt 加载。",
    }
    return {"mods": out, "loader": loader, "src": src, "ok": True, "msg": ""}


def apply_mod_selection(target, src, log):
    """按模组页勾选状态，把模组装进/移出客户端根目录，并同步 dlls.txt。
    返回 (ok, summary)。"""
    if not target:
        return False, "未设置游戏路径"
    root = client_root_of(target)
    info = list_package_mods(target, src)
    if not info["ok"]:
        return False, info["msg"]
    sel = get_mod_selection()
    chosen = [m for m in info["mods"]
              if sel.get(m["name"].lower(), True) and not m["missing"]]
    chosen_names = {m["name"].lower() for m in chosen}
    n_inst = n_rem = 0
    for m in chosen:
        s, d = os.path.join(src, m["name"]), os.path.join(root, m["name"])
        if os.path.isfile(d):
            continue
        try:
            shutil.copy2(s, d)
            n_inst += 1
            log("[模组] 装入 " + m["name"])
        except Exception as ex:
            log("[模组] 装入 " + m["name"] + " 失败：" + str(ex))
    for m in info["mods"]:
        if m["name"].lower() in chosen_names:
            continue
        d = os.path.join(root, m["name"])
        if os.path.isfile(d):
            if _fast_delete(d):
                n_rem += 1
                log("[模组] 已移除（直接删除）：" + m["name"])
    # 加载器：已由内置注入器取代，装模组【不再】往游戏目录拷贝 VanillaFixes.exe；
    # 顺手清掉老版本可能残留在游戏目录里的那个文件（存在即删，无则跳过）。
    legacy = os.path.join(root, "VanillaFixes.exe")
    if os.path.isfile(legacy) and _fast_delete(legacy):
        log("[模组] 已清理残留 VanillaFixes.exe（现由内置注入器取代）")
    # 同步 dlls.txt
    if chosen:
        ensure_mods_loaded(target, log)
    else:
        path = os.path.join(root, "dlls.txt")
        try:
            existing = []
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    existing = [l.strip() for l in f if l.strip()]
            mods_l = {n.lower() for n in MOD_DLL_ORDER}
            keep = [e for e in existing if e.lower() not in mods_l]
            _write_dlls_txt(path, keep)
            log("[模组] dlls.txt 已清空模组条目（保留：" + (", ".join(keep) if keep else "无") + "）")
        except Exception as ex:
            log("[模组] dlls.txt 清理失败：" + str(ex))
    cfg = load_config()
    cfg["session_applied"] = _overlay_present(target)
    save_config(cfg)
    if not chosen:
        return True, "未勾选任何模组：已装的模组已移除，dlls.txt 已恢复"
    return True, "模组选择已应用：装入 %d 个、移除 %d 个，共勾选 %d 个" % (n_inst, n_rem, len(chosen))


def mod_import_package(target, src):
    """从本地模组包文件夹把 DLL 拷进客户端根目录（覆盖前自动备份）。
    加载器 VanillaFixes.exe 已由内置注入器取代，不再随导入拷进游戏目录。
    返回 (ok, log列表, summary)。"""
    root = client_root_of(target) if target else ""
    log = []
    if not root or not os.path.isdir(root):
        return False, ["[错误] 客户端路径无效"], ""
    if not src or not os.path.isdir(src):
        return False, ["[错误] 模组包文件夹不存在：" + str(src)], ""
    # 决定要导入哪些 DLL：优先读 dlls.txt，否则导入包里全部 .dll
    names = []
    dlls_txt = os.path.join(src, "dlls.txt")
    if os.path.isfile(dlls_txt):
        try:
            with open(dlls_txt, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    s = line.strip().strip("/")
                    if s:
                        names.append(s)
        except Exception:
            names = []
    if not names:
        names = [f for f in os.listdir(src) if f.lower().endswith(".dll")]
    # 加载器已由内置注入器取代：本地导入【不再】带 VanillaFixes.exe
    extra_exes = []
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(backups_base(target), "模组备份_" + ts)
    n = 0
    for base in names + extra_exes:
        if base.lower().endswith((".dll", ".exe")):
            cand = base
        else:
            cand = base + ".dll"
        src_f = os.path.join(src, cand)
        if not os.path.isfile(src_f):
            log.append("[跳过] 包里找不到：" + cand)
            continue
        dst = os.path.join(root, os.path.basename(src_f))
        if os.path.exists(dst):
            os.makedirs(backup_dir, exist_ok=True)
            bak = os.path.join(backup_dir, os.path.basename(src_f))
            if os.path.exists(bak):
                _to_trash(bak)
            shutil.move(dst, bak)
            log.append("[备份] 旧 " + os.path.basename(src_f) + " → 模组备份_" + ts)
        shutil.copy2(src_f, dst)
        log.append("[导入] " + os.path.basename(src_f) + " ✓")
        n += 1
    if n:
        log.append("[完成] 共导入 " + str(n) + " 个文件。重启游戏生效"
                   "（模组加载已内置，游戏目录无需 VanillaFixes.exe）。")
        # 自动把已装入的增强模组写进 dlls.txt（客户端 twloader 与内置注入器据此载入）
        try:
            ensure_mods_loaded(target, log.append)
        except Exception as ex:
            log.append("[提示] 自动写入 dlls.txt 失败：" + str(ex))
    else:
        log.append("[完成] 没有需要导入的文件（可能客户端已是最新版）")
    return True, log, "导入 " + str(n) + " 个模组文件"


def mod_toggle(target, name, enable):
    root = client_root_of(target) if target else ""
    if not root:
        return False, "路径无效"
    src = os.path.join(root, name)
    if not os.path.exists(src):
        return False, "文件不存在"
    if enable:
        if not name.lower().endswith(".disabled"):
            return False, "已经是启用状态"
        dst = os.path.join(root, name[:-len(".disabled")])
        if os.path.exists(dst):
            return False, "启用版已存在，请先处理命名冲突"
        os.rename(src, dst)
        return True, "已启用：" + name[:-len(".disabled")]
    else:
        if name.lower().endswith(".disabled"):
            return False, "已经是禁用状态"
        dst = os.path.join(root, name + ".disabled")
        os.rename(src, dst)
        return True, "已禁用：" + name

def _ensure_hidden_console():
    """（已废弃）曾经用 AllocConsole 给无窗口 exe 挂隐藏控制台，但 AllocConsole
    会先弹出一个【可见黑窗】再隐藏，表现为双击 exe 时一闪而过——反而制造了
    用户看到的黑窗。现已废弃：所有子进程统一用 _run_hidden/_popen_hidden
    （CREATE_NO_WINDOW）启动，根本不分配控制台，从源头消除任何黑窗。"""
    return


def _init_dpi_awareness():
    """进程启动【立即】声明 DPI 感知（system-aware，与 pywebview 稍后调用的
    SetProcessDPIAware 同级）。不声明的进程里，启动早期的 MessageBoxW /
    GetOpenFileNameW 按 96DPI 渲染后被系统整体位图拉伸 → 文字发虚、
    同一个对话框里不同行清晰度不一致。提前声明后按真实 DPI 渲染，全程清晰。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # SYSTEM_DPI_AWARE
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()        # 老系统兜底
    except Exception:
        pass


def _msgbox(title, text):
    """无窗口 exe 下也能弹系统对话框（不依赖控制台）。失败静默。
    MB_TOPMOST|MB_SETFOREGROUND：保证提示框永远在最前——否则会被
    全屏游戏等窗口挡住，用户以为程序『没反应/没提示』。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40000)  # MB_OK|MB_TOPMOST
    except Exception:
        pass


def choose_wow_exe_dialog(initial_dir=""):
    """弹原生「选择 WoW.exe」文件对话框（comdlg32 GetOpenFileNameW），
    返回选中的完整路径；用户取消返回空串。不依赖 pywebview 的 js_api。"""
    try:
        import ctypes
        from ctypes import wintypes

        class OPENFILENAMEW(ctypes.Structure):
            _fields_ = [
                ("lStructSize", wintypes.DWORD),
                ("hwndOwner", wintypes.HWND),
                ("hInstance", wintypes.HINSTANCE),
                ("lpstrFilter", wintypes.LPCWSTR),
                ("lpstrCustomFilter", wintypes.LPWSTR),
                ("nMaxCustFilter", wintypes.DWORD),
                ("nFilterIndex", wintypes.DWORD),
                ("lpstrFile", wintypes.LPWSTR),
                ("nMaxFile", wintypes.DWORD),
                ("lpstrFileTitle", wintypes.LPWSTR),
                ("nMaxFileTitle", wintypes.DWORD),
                ("lpstrInitialDir", wintypes.LPCWSTR),
                ("lpstrTitle", wintypes.LPCWSTR),
                ("Flags", wintypes.DWORD),
                ("nFileOffset", wintypes.WORD),
                ("nFileExtension", wintypes.WORD),
                ("lpstrDefExt", wintypes.LPCWSTR),
                ("lCustData", wintypes.LPARAM),
                ("lpfnHook", wintypes.LPVOID),
                ("lpTemplateName", wintypes.LPCWSTR),
            ]

        buf = ctypes.create_unicode_buffer(260)
        # 过滤器内嵌 \0 分隔：WoW 程序 | WoW.exe;WoWClassic.exe | 所有文件 | *.*
        flt = "WoW 程序（WoW.exe）\0WoW.exe;WoWClassic.exe;*.exe\0所有文件\0*.*\0"
        init = initial_dir if (initial_dir and os.path.isdir(initial_dir)) else None
        OFN = OPENFILENAMEW()
        OFN.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        OFN.hwndOwner = None
        OFN.lpstrFilter = flt
        OFN.nFilterIndex = 1
        OFN.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
        OFN.nMaxFile = 260
        OFN.lpstrInitialDir = init
        OFN.lpstrTitle = "请选择游戏根目录里的 WoW.exe"
        OFN.Flags = 0x1000 | 0x800 | 0x4 | 0x8   # FILEMUSTEXIST|PATHMUSTEXIST|HIDEREADONLY|NOCHANGEDIR
        if ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(OFN)):
            return buf.value
    except Exception:
        pass
    return ""


def _focus_existing_window():
    """把已在运行的助手主窗口调到前台（第二实例双击时的正确引导，
    而不是开一个让人困惑的浏览器标签页）。找到并激活返回 True。"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        hit = []

        @EnumProc
        def _cb(hwnd, lp):
            if user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, buf, 256)
                t = buf.value
                if ("WowAssist" in t or "魔兽助手" in t) and "浏览器" not in t:
                    hit.append(hwnd)
            return True

        user32.EnumWindows(_cb, 0)
        if not hit:
            return False
        hwnd = hit[0]
        SW_RESTORE = 9
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def _webview2_available():
    """检测系统是否装了 WebView2 运行时（pywebview 原生窗口在 Windows 上依赖它）。
    没装 → 原生窗口必失败，应直接回退浏览器模式并提示，而不是静默一闪而过。"""
    if sys.platform != "win32":
        # 非 Windows 走 webview 自身 backend 决策
        return True
    # 1) 注册表：EdgeUpdate 分发的独立 WebView2 Runtime
    try:
        import winreg
        for key in (
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A08C11}",
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A08C11}",
        ):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                    if winreg.QueryValueEx(k, "pv")[0]:
                        return True
            except OSError:
                pass
    except Exception:
        pass
    # 2) 系统目录里的 WebView2Loader.dll（随 Edge/独立 Runtime 安装）
    for p in (r"C:\Windows\System32\WebView2Loader.dll",
              r"C:\Windows\SysWOW64\WebView2Loader.dll"):
        if os.path.exists(p):
            return True
    # 3) Evergreen Runtime 安装目录：注册表可能没有登记，但 Runtime 实际可用
    #    （实测本机即如此：EdgeWebView\Application\155.x 存在，webview 可正常开窗）
    for base in (r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application",
                 r"C:\Program Files\Microsoft\EdgeWebView\Application"):
        try:
            if os.path.isdir(base) and any(
                    e.count(".") >= 2 and os.path.isdir(os.path.join(base, e))
                    for e in os.listdir(base)):
                return True
        except Exception:
            pass
    return False


def _log_wv(msg):
    """webview 相关诊断落盘到 run.log（无窗口 exe 下闪退/无窗口的排查依据）。"""
    try:
        with open(RUN_LOG, "a", encoding="utf-8") as f:
            f.write("[wv " + time.strftime("%Y-%m-%d %H:%M:%S") + "] " + msg + "\n")
    except Exception:
        pass


def _run_window(url):
    """原生桌面窗口模式（pywebview）：把界面装进软件窗口，无浏览器痕迹。
    点窗口 X → 弹确认 → 退出（持久化模型，不还原客户端）；取消则继续使用。
    返回 True=窗口模式正常走完；False=创建失败（调用方回退浏览器模式）。
    任何失败分支都写诊断日志到 run.log，不再静默。"""
    # 缺 WebView2 运行时 → 原生窗口必失败，直接让 main 回退浏览器（并提示）
    if not _webview2_available():
        _log_wv("跳过原生窗口：WebView2 运行时未检测到")
        return False
    try:
        import webview
    except Exception:
        import traceback
        _log_wv("import webview 失败：\n" + traceback.format_exc())
        return False
    try:
        # 居中必须【显式传逻辑像素坐标】：实测 pywebview 的 CenterScreen 分支
        # 在本进程（提前声明 DPI 感知）下不生效，窗口落在 (32,32) 左上角。
        # pywebview 把传入 x/y 当逻辑像素、按 GetDpiForWindow 的缩放（125% 等）
        # 换算成物理像素，所以这里要先除以系统 DPI 缩放，算出「逻辑居中点」。
        _wx = _wy = None
        try:
            import ctypes
            _sw = ctypes.windll.user32.GetSystemMetrics(0)   # SM_CXSCREEN 物理像素
            _sh = ctypes.windll.user32.GetSystemMetrics(1)   # SM_CYSCREEN
            try:
                _dpi = ctypes.windll.user32.GetDpiForSystem()
            except Exception:
                _dpi = 96
            _scale = (_dpi / 96.0) if _dpi > 0 else 1.0
            _lsw = int(_sw / _scale)   # pywebview 期望的逻辑像素屏幕尺寸
            _lsh = int(_sh / _scale)
            if _lsw > 980 and _lsh > 680:
                _wx = (_lsw - 980) // 2
                _wy = (_lsh - 680) // 2
        except Exception:
            _wx = _wy = None
        window = webview.create_window(
            "WowAssist · 简单好用又省心的香草旧世魔兽游戏助手", url,
            width=980, height=680, x=_wx, y=_wy,
            resizable=False, confirm_close=False,
        )
    except Exception:
        import traceback
        _log_wv("create_window 失败：\n" + traceback.format_exc())
        return False

    _td_box = {"thread": None}

    def _bg_teardown_and_exit():
        """后台完成还原（杀游戏+卸模组/插件/字体+清缓存），做完直接结束进程。
        os._exit 跳过 atexit，避免重复 teardown；窗口已关，用户无感知。"""
        try:
            _teardown()
        except Exception:
            pass
        try:
            _flush_stdio()
        except Exception:
            pass
        os._exit(0)

    def _on_closing():
        """点窗口 X：窗口立刻消失（hide+允许关闭），还原工作转后台线程继续，
        界面不卡在"正在退出"，后台做完后进程自动结束。"""
        try:
            window.hide()
        except Exception:
            pass
        if not _td_box["thread"]:
            _td_box["thread"] = threading.Thread(
                target=_bg_teardown_and_exit, daemon=False)
            _td_box["thread"].start()
        return True

    try:
        window.events.closing += _on_closing
    except Exception:
        pass

    # ===== 最小化到托盘（桌面右下角通知区）=====
    # 用 WinForms NotifyIcon（pythonnet，pywebview 在 Windows 上已自带，无需新依赖）：
    # 点「—」最小化时窗口自动藏进托盘；左键点托盘图标恢复主界面；
    # 右键托盘菜单：显示主界面 / 退出（持久化模型，退出不再还原客户端）。
    tray = {"ni": None, "hidden": False, "form": None, "ready": False}

    def _tray_set_visible(visible, why=""):
        """把对托盘图标的任何操作【调度回托盘线程】执行。
        NotifyIcon 只允许其创建线程触碰：从 pywebview 线程直接设 Visible，
        Shell_NotifyIcon 的注册/回调窗口会跨线程错乱——图标悬停即消失。"""
        form = tray.get("form")
        if not tray.get("ready") or form is None:
            _log_wv("托盘未就绪，忽略 Visible=%s（%s）" % (visible, why))
            return

        def _do():
            try:
                ni = tray.get("ni")
                if ni is not None:
                    ni.Visible = visible
                    _log_wv("托盘 Visible=%s %s" % (visible, why))
            except Exception:
                import traceback
                _log_wv("托盘 Visible 设置失败：\n" + traceback.format_exc())
        try:
            from System import Action
            form.BeginInvoke(Action(_do))
        except Exception:
            import traceback
            _log_wv("托盘调度失败：\n" + traceback.format_exc())

    def _tray_show_main(*_a):
        tray["hidden"] = False
        try:
            window.show()
            window.restore()
        except Exception:
            pass
        try:
            ni = tray.get("ni")
            if ni is not None:
                ni.Visible = False   # 本函数只会被托盘线程的点击事件调用
        except Exception:
            pass

    def _tray_exit(*_a):
        try:
            window.hide()
        except Exception:
            pass
        try:
            ni = tray.get("ni")
            if ni is not None:
                ni.Visible = False
                ni.Dispose()
            tray["ni"] = None
            tray["ready"] = False
        except Exception:
            pass
        if not _td_box["thread"]:
            _td_box["thread"] = threading.Thread(
                target=_bg_teardown_and_exit, daemon=False)
            _td_box["thread"].start()

    def _tray_main():
        """专用 STA 线程：隐藏宿主窗体 + 托盘图标 + 自有消息循环。
        NotifyIcon 的一切操作（含 Visible 开关）都必须经 _tray_set_visible
        调度回本线程；跨线程直接改是『图标悬停/出现即消失』的根源。
        STA 必须在线程【启动前】设置（见下方启动处），否则抛异常退化为 MTA。"""
        try:
            import clr
            clr.AddReference("System.Windows.Forms")
            clr.AddReference("System.Drawing")
            from System.Windows.Forms import (Form, FormStartPosition,
                                              FormWindowState, NotifyIcon,
                                              ContextMenuStrip,
                                              ToolStripMenuItem, Application,
                                              MouseButtons)
            from System.Drawing import Icon
            # 隐藏宿主窗体：永不 Show，仅作为托盘 BeginInvoke 的目标窗口
            form = Form()
            form.ShowInTaskbar = False
            form.StartPosition = FormStartPosition.Manual
            form.WindowState = FormWindowState.Minimized
            form.Text = "WowAssist 托盘宿主"
            force_handle = form.Handle   # 在本线程强制创建句柄（BeginInvoke 需要）
            ico_path = os.path.join(_RES_DIR, "capy.ico")
            ni = NotifyIcon()
            capy_icon = None
            if os.path.isfile(ico_path):
                # 强引用保活：pythonnet 的 Icon 代理一旦被 GC，会 Dispose 掉底层
                # HICON，导致托盘图标在鼠标悬停（资源管理器重绘）时消失。必须挂住。
                capy_icon = Icon(ico_path)
                ni.Icon = capy_icon
            else:
                _log_wv("托盘图标文件缺失：" + ico_path)
            ni.Text = "WowAssist"
            ni.Visible = False
            menu = ContextMenuStrip()
            # 右键菜单只留【退出】（用户指定）：显示主界面走左键单击/双击
            mi_exit = ToolStripMenuItem("退出")
            mi_exit.Click += _tray_exit
            menu.Items.Add(mi_exit)
            ni.ContextMenuStrip = menu
            ni.DoubleClick += _tray_show_main

            def _tray_click(sender, e):
                # NotifyIcon.Click 左键右键都会触发（右键会同时弹菜单+恢复界面）；
                # 改用 MouseClick 只认左键：左键单击恢复主界面，右键只弹菜单。
                try:
                    if e.Button == MouseButtons.Left:
                        _tray_show_main(sender, e)
                except Exception:
                    pass
            ni.MouseClick += _tray_click
            # 全部托管对象强引用保活（防 GC 触发 Dispose → 托盘图标消失）
            tray["ni"] = ni
            tray["icon"] = capy_icon
            tray["menu"] = menu
            tray["mi_exit"] = mi_exit
            tray["form"] = form
            tray["ready"] = True
            _log_wv("托盘线程就绪（图标=%s）" % ("OK" if capy_icon is not None else "缺失"))
            Application.Run()   # 托盘消息循环（STA 后台线程，随进程结束）
        except Exception:
            tray["ready"] = False
            import traceback
            _log_wv("托盘初始化失败：\n" + traceback.format_exc())
    # 用 System.Threading.Thread 显式设置 STA 后再启动（关键：WinForms 要求 STA）。
    # 用 python 的 threading.Thread 无法设置 COM 套间，会退化为 MTA 导致悬停消失。
    try:
        import clr
        clr.AddReference("System.Threading")
        from System.Threading import Thread as ClrThread, ThreadStart, ApartmentState
        _tray_th = ClrThread(ThreadStart(_tray_main))
        _tray_th.SetApartmentState(ApartmentState.STA)
        _tray_th.IsBackground = True
        _tray_th.Start()
    except Exception:
        import traceback
        _log_wv("托盘 STA 线程启动失败，退回普通线程：\n" + traceback.format_exc())
        threading.Thread(target=_tray_main, daemon=True).start()

    def _on_minimized():
        # 点「—」最小化 → 藏进托盘（任务栏不占位）；托盘左键单击恢复
        if tray.get("hidden"):
            return
        tray["hidden"] = True
        # 关键：Visible 必须调度回托盘线程改（跨线程直改 → 图标悬停即消失）
        _tray_set_visible(True, "(最小化)")
        try:
            window.hide()
        except Exception:
            pass
    try:
        window.events.minimized += _on_minimized
    except Exception:
        pass

    try:
        webview.start()
        _log_wv("webview.start 已返回（正常关窗或异常提前返回）")
        # 点 X 情形：后台还原线程还在跑 → 等它收尾（它会 os._exit 结束进程）
        _td = _td_box.get("thread")
        if _td is not None:
            _td.join(timeout=900)
        return True
    except Exception:
        import traceback
        _log_wv("webview.start 抛异常：\n" + traceback.format_exc())
        return False


# ================= 3.18 自动更新（app 自更新）=================
# 更新源 = 用户填的蓝奏云「exe 专区」文件夹（wow-assist 文件夹）。该文件夹里放
    # release_manifest.txt（版本/说明/exe 文件名+md5）与最新 wowassist-v*.exe。
# 启动时后台检查一次；用户也可手动「检查更新」。发现新版则下载并替换自身、重启。

_APP_UPDATE = {
    "checked": False, "available": False, "current": APP_VERSION,
    "latest": "", "notes": "", "required": False, "enabled": True,
    "configured": False, "exe_name": "", "exe_md5": "", "exe_size": 0,
    "err": "", "downloading": False, "pct": 0,
}

def _app_update_cfg():
    cfg = load_config()
    au = cfg.get("app_update", {}) or {}
    au.setdefault("enabled", True)
    # 默认更新源：蓝奏云「wow-assist」文件夹（只放 exe + release_manifest.txt）。
    # 用户可在「下载」页自行修改；已显式填过的值不会被覆盖。
    au.setdefault("folder_url", "https://sycc.lanzoum.com/b01i5y8pmf")
    au.setdefault("folder_pwd", "1acw")
    au.setdefault("channel", "stable")
    au.setdefault("skipped", "")
    return au

def _save_app_update_cfg(au):
    cfg = load_config()
    cfg["app_update"] = au
    save_config(cfg)

def _parse_version(v):
    if not v:
        return (0, 0, 0)
    v = str(v).lstrip("vV").strip()
    out = []
    for p in re.split(r"[.\-+]", v)[:3]:
        try:
            out.append(int(re.sub(r"[^0-9].*$", "", p) or 0))
        except Exception:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])

def _version_newer(latest, current):
    return _parse_version(latest) > _parse_version(current)

def _fetch_release_manifest(au):
    """从更新源文件夹取 release_manifest（优先 .txt，蓝奏云拒收 .json）并解析。
    若 manifest 取不到/下载失败，则退回从 wowassist-v*.exe 文件名推断最新版本，
    保证自动更新在 manifest 不可读时仍能工作（仅跳过 md5 校验）。返回 (dict|None, err)。"""
    url = (au.get("folder_url") or "").strip()
    pwd = (au.get("folder_pwd") or "").strip()
    if not url:
        return None, "未配置更新源文件夹"
    try:
        from lanzou_core import LanzouClient
        c = LanzouClient(timeout=30)
        st, files = c.get_folder_files(url, pwd)
        if st != "Success" or not files:
            return None, "更新源文件夹解析失败（链接/提取码或网络）"

        def _pick_exe():
            for f in files:
                nm = (f.get("name") or "")
                if re.match(r"^wowassist-v[\d.]+\.exe$", nm, re.I):
                    return {"name": nm, "md5": "", "size": 0}
            return None

        # 优先 release_manifest.txt（蓝奏云拒收 .json，客户端 100% 但服务端不落盘），
        # 兼容旧 .json（若某环境允许）。取到后下载并解析；任何失败都退回 exe 名推断。
        data = None
        for nm in ("release_manifest.txt", "release_manifest.json"):
            mf_file = next((f for f in files if (f.get("name") or "") == nm), None)
            if not mf_file:
                continue
            st2, link = c.get_direct_link(mf_file.get("url", ""), pwd)
            if st2 != "Success" or not link:
                continue
            try:
                req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = json.loads(r.read().decode("utf-8"))
                if data and str(data.get("version") or ""):
                    break
            except Exception:
                data = None
        if not data or not str(data.get("version") or ""):
            exe_info = _pick_exe()
            if not exe_info:
                return None, "更新源文件夹里既没有 release_manifest 也没有 wowassist-v*.exe"
            m = re.match(r"wowassist-v([\d.]+)\.exe", exe_info["name"], re.I)
            data = {"version": m.group(1) if m else "",
                    "notes": "", "required": False, "exe": exe_info}
        exe_info = data.get("exe") or {}
        if not exe_info.get("name"):
            exe_info = _pick_exe() or exe_info
            data["exe"] = exe_info
        return data, ""
    except Exception as e:
        return None, "检查更新异常：" + str(e)

def _check_app_update():
    au = _app_update_cfg()
    _APP_UPDATE["enabled"] = bool(au.get("enabled", True))
    _APP_UPDATE["configured"] = bool((au.get("folder_url") or "").strip())
    _APP_UPDATE["current"] = APP_VERSION
    _APP_UPDATE["checked"] = True
    if not _APP_UPDATE["enabled"] or not _APP_UPDATE["configured"]:
        _APP_UPDATE["available"] = False
        _APP_UPDATE["err"] = "" if _APP_UPDATE["configured"] else "未配置更新源（见「下载」页）"
        return dict(_APP_UPDATE)
    data, err = _fetch_release_manifest(au)
    if err or not data:
        _APP_UPDATE["available"] = False
        _APP_UPDATE["err"] = err or "manifest 获取失败"
        return dict(_APP_UPDATE)
    latest = str(data.get("version", "") or "")
    if not latest:
        _APP_UPDATE["available"] = False
        _APP_UPDATE["err"] = "manifest 缺少 version 字段"
        return dict(_APP_UPDATE)
    skipped = str(au.get("skipped", "") or "")
    _APP_UPDATE.update({
        "available": _version_newer(latest, APP_VERSION) and latest != skipped,
        "latest": latest,
        "notes": data.get("notes", "") or "",
        "required": bool(data.get("required", False)),
        "exe_name": (data.get("exe") or {}).get("name", ""),
        "exe_md5": (data.get("exe") or {}).get("md5", ""),
        "exe_size": int((data.get("exe") or {}).get("size", 0) or 0),
        "err": "",
    })
    return dict(_APP_UPDATE)

def _bg_app_update_check():
    try:
        _check_app_update()
    except Exception:
        pass

def _apply_app_update():
    """下载最新 exe → 校验 md5 → 写更新批处理 → 启动并退出当前进程。
    仅打包(frozen)模式替换自身；脚本模式只下载不替换。返回 (ok, msg)。"""
    au = _app_update_cfg()
    data, err = _fetch_release_manifest(au)
    if err or not data:
        _APP_UPDATE["err"] = err or "manifest 获取失败"
        return False, _APP_UPDATE["err"]
    exe_info = data.get("exe") or {}
    exe_name = exe_info.get("name", "")
    exe_md5 = exe_info.get("md5", "")
    if not exe_name:
        return False, "manifest 未指定 exe 文件名"
    from lanzou_core import LanzouClient
    c = LanzouClient(timeout=30)
    st, files = c.get_folder_files((au.get("folder_url") or "").strip(),
                                   (au.get("folder_pwd") or "").strip())
    exe_file = None
    if st == "Success" and files:
        for f in files:
            if (f.get("name") or "") == exe_name:
                exe_file = f
                break
    if not exe_file:
        return False, "更新源文件夹里找不到 " + exe_name
    st2, link = c.get_direct_link(exe_file.get("url", ""), (au.get("folder_pwd") or "").strip())
    if st2 != "Success" or not link:
        return False, "新版本 exe 直链解析失败"
    _APP_UPDATE["downloading"] = True
    _APP_UPDATE["pct"] = 0
    dest = os.path.join(TEMP_DIR, "wowassist_update.exe")
    try:
        def _cb(done, total):
            _APP_UPDATE["pct"] = int(done * 100 / total) if total else 0
        got = download_file(link, TEMP_DIR, _cb)
        if not got:
            return False, "下载新版本失败"
        if os.path.abspath(got) != os.path.abspath(dest):
            if os.path.exists(dest):
                os.remove(dest)
            os.rename(got, dest)
        if exe_md5:
            import hashlib
            h = hashlib.md5()
            with open(dest, "rb") as f:
                for chunk in iter(lambda: f.read(1048576), b""):
                    h.update(chunk)
            if h.hexdigest().lower() != exe_md5.lower():
                return False, "新版本 md5 校验不一致，已取消更新"
    except Exception as e:
        return False, "下载/校验失败：" + str(e)
    finally:
        _APP_UPDATE["downloading"] = False
    if not getattr(sys, "frozen", False):
        return True, "脚本模式已完成下载（路径 " + dest + "），跳过替换自身"
    try:
        _launch_update_bat(dest)
        return True, "更新已下载，正在重启完成更新…"
    except Exception as e:
        return False, "启动更新失败：" + str(e)

def _launch_update_bat(new_exe):
    """写批处理：备份旧 exe → 覆盖新 exe → 重新启动 → 自删。当前进程随后退出。"""
    cur = os.path.abspath(sys.executable)
    bat = os.path.join(TEMP_DIR, "wowassist_update.bat")
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "timeout /t 1 /nobreak >nul",
        'taskkill /f /im "%s" >nul 2>&1' % os.path.basename(cur),
        'if exist "%s" copy /y "%s" "%s.bak" >nul 2>&1' % (cur, cur, cur),
        'move /y "%s" "%s" >nul 2>&1' % (new_exe, cur),
        'start "" "%s"' % cur,
        'del /f /q "%s"' % bat,
    ]
    with open(bat, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines) + "\r\n")
    try:
        subprocess.Popen('"%s"' % bat, shell=True,
                         creationflags=0x08000000 if sys.platform == "win32" else 0)
    except Exception:
        if sys.platform == "win32":
            os.startfile(bat)
    time.sleep(1.2)
    os._exit(0)


# ================= 3.19 用户自行导入本地模组/插件/字体 =================
# 复用现有备份/安装模型；在 install_state.custom 记录自定义导入项，
# 使其能被「移除」/「清理还原」识别与清理。

def _custom_imports():
    cfg = load_config()
    st = cfg.setdefault("install_state", {})
    cu = st.setdefault("custom", {"mods": [], "addons": [], "fonts": []})
    for k in ("mods", "addons", "fonts"):
        cu.setdefault(k, [])
    return cu

def _record_custom(kind, names):
    names = [n for n in (names or []) if n]
    if not names:
        return
    cfg = load_config()
    st = cfg.setdefault("install_state", {})
    cu = st.setdefault("custom", {"mods": [], "addons": [], "fonts": []})
    cu.setdefault(kind, [])
    have = set(x.lower() for x in cu[kind])
    for n in names:
        if n.lower() not in have:
            cu[kind].append(n)
            have.add(n.lower())
    save_config(cfg)

def _clear_custom(kind):
    cfg = load_config()
    st = cfg.get("install_state", {})
    cu = st.get("custom")
    if cu and kind in cu:
        cu[kind] = []
        save_config(cfg)

def _remove_custom_all(target, log):
    """移除所有自定义导入的模组/插件/字体（清理还原/移除时调用）。"""
    cu = _custom_imports()
    if not (target and os.path.isdir(target)):
        return
    root = client_root_of(target)
    addons = normalize_addons_path(target, create=False)
    dst_fonts = fonts_dst(target)
    for nm in list(cu.get("mods", [])):
        p = os.path.join(root, nm)
        if os.path.isfile(p):
            try:
                os.remove(p)
                log("[移除] 自定义模组 " + nm)
            except Exception as e:
                log("[移除失败] " + nm + "：" + str(e))
    for nm in list(cu.get("addons", [])):
        p = os.path.join(addons, nm) if addons else ""
        if p and os.path.isdir(p):
            try:
                shutil.rmtree(p)
                log("[移除] 自定义插件 " + nm)
            except Exception as e:
                log("[移除失败] " + nm + "：" + str(e))
    for nm in list(cu.get("fonts", [])):
        p = os.path.join(dst_fonts, nm) if dst_fonts else ""
        if p and (os.path.isfile(p) or os.path.isdir(p)):
            try:
                _fast_delete(p)
                log("[移除] 自定义字体 " + nm)
            except Exception as e:
                log("[移除失败] " + nm + "：" + str(e))

def import_fonts_local(src_fonts, target, log):
    """从用户本地文件夹导入字体到游戏 Fonts（覆盖式；客户端原有同名字体先备份）。
    返回装入文件数。"""
    if not src_fonts or not os.path.isdir(src_fonts):
        log("[失败] 字体源文件夹不存在：" + str(src_fonts))
        return 0
    dst = fonts_dst(target)
    try:
        os.makedirs(dst, exist_ok=True)
        names = [e for e in os.listdir(src_fonts)
                 if os.path.isfile(os.path.join(src_fonts, e))
                 and e.lower().endswith(_FONT_EXTS)]
        if not names:
            log("[字体] 源文件夹里没有字体文件（.ttf/.otf 等）")
            return 0
        bdir = _original_backup_dir(target, "字体备份")
        n = 0
        imported = []
        for e in names:
            sp = os.path.join(src_fonts, e)
            dp = os.path.join(dst, e)
            if os.path.exists(dp):
                _move_to_backup(dp, bdir, log, "字体")
            shutil.copy2(sp, dp)
            imported.append(e)
            n += 1
        if n:
            log("[字体] 已从本地导入 " + str(n) + " 个字体文件 → 游戏目录\\Fonts")
            if imported:
                _record_custom("fonts", imported)
            _mark_installed("fonts", log)
        return n
    except Exception as ex:
        log("[字体] 导入失败：" + str(ex))
        return 0

def choose_dir_dialog(initial_dir="", filter_ext="*.dll"):
    """选文件夹：复用原生文件对话框（GetOpenFileNameW，已验证可在本程序线程工作），
    让用户选该文件夹内的任意一个文件，返回其所在目录；取消/失败返回空串。"""
    try:
        import ctypes
        from ctypes import wintypes
        class OFN(ctypes.Structure):
            _fields_ = [
                ("lStructSize", wintypes.DWORD),
                ("hwndOwner", wintypes.HWND),
                ("hInstance", wintypes.HINSTANCE),
                ("lpstrFilter", wintypes.LPCWSTR),
                ("lpstrCustomFilter", wintypes.LPWSTR),
                ("nMaxCustFilter", wintypes.DWORD),
                ("nFilterIndex", wintypes.DWORD),
                ("lpstrFile", wintypes.LPWSTR),
                ("nMaxFile", wintypes.DWORD),
                ("lpstrFileTitle", wintypes.LPWSTR),
                ("nMaxFileTitle", wintypes.DWORD),
                ("lpstrInitialDir", wintypes.LPCWSTR),
                ("lpstrTitle", wintypes.LPCWSTR),
                ("Flags", wintypes.DWORD),
                ("nFileOffset", wintypes.WORD),
                ("nFileExtension", wintypes.WORD),
                ("lpstrDefExt", wintypes.LPWSTR),
                ("lCustData", wintypes.LPARAM),
                ("lpfnHook", wintypes.LPVOID),
                ("lpTemplateName", wintypes.LPCWSTR),
            ]
        buf = ctypes.create_unicode_buffer(260)
        flt = "导入源文件（任选一个，以其所在文件夹为源）\0*.*\0指定类型\0%s\0" % filter_ext
        init = initial_dir if (initial_dir and os.path.isdir(initial_dir)) else None
        o = OFN()
        o.lStructSize = ctypes.sizeof(OFN)
        o.hwndOwner = None
        o.lpstrFilter = flt
        o.nFilterIndex = 1
        o.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
        o.nMaxFile = 260
        o.lpstrInitialDir = init
        o.lpstrTitle = "请选择该文件夹内的任意一个文件（以其所在文件夹作为导入源）"
        o.Flags = 0x1000 | 0x800 | 0x4 | 0x8
        if ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(o)):
            p = buf.value
            if p and os.path.isfile(p):
                return os.path.dirname(p)
    except Exception:
        pass
    return ""


# ================= 3.20 加密保存游戏账号/密码（机器绑定）=================
# 密钥由本机硬件指纹派生（系统盘卷序列号 + 计算机名 + 固定盐），机器绑定：
# 本机打开即自动解密；换电脑/重装系统后密文不可解，需重新输入。明文绝不落盘。

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    _CRYPTO_OK = True
except Exception:
    _CRYPTO_OK = False

_APP_ACCOUNT_SALT = b"WowAssist-account-salt-v1"

def _machine_secret():
    parts = []
    try:
        import ctypes
        sn = ctypes.c_ulong()
        ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p("C:\\"), None, 0,
                ctypes.byref(sn), None, None, None, 0)
        if sn.value:
            parts.append(str(sn.value))
    except Exception:
        pass
    try:
        import socket
        parts.append(socket.gethostname())
    except Exception:
        pass
    return ("|".join(parts) if parts else "fallback").encode("utf-8")

def _account_key():
    import base64
    secret = _machine_secret()
    hk = HKDF(algorithm=hashes.SHA256(), length=32, salt=_APP_ACCOUNT_SALT,
              info=b"wowassist-account")
    return base64.urlsafe_b64encode(hk.derive(secret))

def _encrypt_account(data):
    f = Fernet(_account_key())
    return f.encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("utf-8")

def _decrypt_account(cipher):
    f = Fernet(_account_key())
    return json.loads(f.decrypt(cipher.encode("utf-8")).decode("utf-8"))

def _save_account(user, pwd, remember):
    cfg = load_config()
    if remember and (user or pwd):
        try:
            cfg["account"] = {"cipher": _encrypt_account({"u": user or "", "p": pwd or ""}),
                              "ts": time.time()}
        except Exception:
            cfg.pop("account", None)
    else:
        cfg.pop("account", None)
    save_config(cfg)

def _load_account():
    cfg = load_config()
    acc = cfg.get("account")
    if not acc or not acc.get("cipher"):
        return {"has": False, "user": "", "pwd": ""}
    if not _CRYPTO_OK:
        return {"has": True, "user": "", "pwd": "", "locked": True}
    try:
        d = _decrypt_account(acc["cipher"])
        return {"has": True, "user": d.get("u", ""), "pwd": d.get("p", "")}
    except Exception:
        return {"has": True, "user": "", "pwd": "", "locked": True}


def main():
    _init_dpi_awareness()   # 必须最先执行：任何弹窗/文件框之前声明 DPI 感知
    _ensure_hidden_console()
    _migrate_legacy_runtime()   # 旧数据目录 AppData\魔兽助手 -> AppData\wowassist（一次性）
    for d in (TEMP_DIR, DOWNLOAD_DIR):
        os.makedirs(d, exist_ok=True)
    # 首次启动：写入默认 folder 分享配置（作者的蓝奏云资源文件夹），
    # 用户之后可在「下载」页修改链接/提取码；已有 folder 键则不覆盖。
    _cfg = load_config()
    if "folder" not in _cfg:
        _cfg["folder"] = {"url": "https://sycc.lanzoum.com/b01i5y3r7c", "pwd": "9p81"}
        save_config(_cfg)
    # ===== 第一步：便携自检（用户要求）=====
    # 检查 exe 同级目录有没有 WoW.exe：有 → 判定 exe 被放在游戏根目录，
    # 无论 config 里存过什么路径，一律以 exe 所在的客户端为准。
    _root = _portable_detect()
    if _root:
        # target 存游戏根目录（与 WoW.exe 同级），装卸链路内部再推导 AddOns
        if _cfg.get("target") != _root:
            _cfg["target"] = _root
            save_config(_cfg)
        print("[便携] 自检：exe 位于游戏根目录，已使用该客户端：" + _root)
    else:
        # exe 不在游戏根：用已保存路径；没有才做旧探测兜底
        _t = _cfg.get("target", "")
        if not (_t and os.path.isdir(_t)):
            _guess = _to_root(_guess_target_from_exe())
            if _guess:
                _cfg["target"] = _guess
                save_config(_cfg)
                print("[便携] 已自动识别游戏路径：" + _guess)
        # 用户要求：exe 不在游戏根时明确提示引导（仅打包 exe 弹窗；脚本模式不弹）
        if getattr(sys, "frozen", False):
            _saved = _cfg.get("target", "")
            if _saved and os.path.isdir(_saved):
                _msgbox("WowAssist - 提示",
                        "检测到 wowassist.exe 不在游戏根目录。\n\n"
                        "推荐：把 exe 放到游戏根目录（与 WoW.exe 同级的文件夹），\n"
                        "即可自动识别游戏路径，随客户端自由移动。")
            else:
                _msgbox("WowAssist - 未检测到游戏",
                        "未检测到魔兽客户端！\n\n"
                        "请把 wowassist.exe 放到【游戏根目录】（与 WoW.exe 同级的文件夹）"
                        "后重新打开，即可自动识别游戏路径；\n"
                        "也可以打开界面后在首页手动设置游戏路径。")
    url = f"http://127.0.0.1:{PORT}"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        # 已有实例在跑：把它的窗口调到前台 + 置顶提示（绝不能注册
        # atexit/控制台事件/自愈还原——否则第二个实例一退出，就会把
        # 正在使用的第一个实例的会话拆掉：杀游戏+删插件模组）。
        # 不开浏览器标签页——那会让用户误以为这就是主界面、关掉就退出了。
        print(f"插件助手已在运行中，尝试把已有窗口调到前台")
        _focused = _focus_existing_window()
        _msgbox("WowAssist",
                "助手已经在运行中了" +
                ("，已为你把它的窗口调到前台（任务栏也能找到）。" if _focused
                 else "（任务栏可找到它的窗口，可能被最小化或被其他窗口挡住了）。") +
                "\n\n请直接使用那个窗口；退出请点里面的「退出工具」按钮，"
                "已安装的模组/插件/字体与缓存都会保留，不会自动还原。")
        return
    # 以下只有抢到端口的主实例才做：临时文件清理 + 退出钩子 + 缓存 GC
    _bg_rmtree(os.path.join(TEMP_DIR, "trash"))
    for e in os.listdir(TEMP_DIR):
        p = os.path.join(TEMP_DIR, e)
        if e.startswith("tmp_") and os.path.isdir(p):
            _bg_rmtree(p)
    # 持久化模型：退出工具【不】还原客户端、不杀游戏、不删缓存（已装内容与缓存都保留）。
    atexit.register(_teardown)
    _install_console_handler()
    # 启动后台跑一次缓存 GC：清理长期(默认30天)未使用的下载缓存，不影响已装内容。
    threading.Thread(target=cache_gc, daemon=True).start()
    # 启动后台检查一次新版本（不阻塞；结果由 UI 轮询 /api/app_update_status 展示）
    threading.Thread(target=_bg_app_update_check, daemon=True).start()
    print(f"WowAssist 已启动: {url}  (关闭窗口即退出；已安装的模组/插件/字体与缓存都会保留)")
    # HTTP 服务常驻后台线程；主线程尝试原生窗口模式（exe 默认），
    # 窗口创建失败则回退浏览器打开（脚本/bat 模式体验不变）
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if _run_window(url):
        return
    # 原生窗口不可用（缺 WebView2 或创建失败）→ 浏览器模式兜底，并明确提示用户
    _msgbox("WowAssist",
            "未能启动内置窗口（本机可能未安装 WebView2 运行时）。\n\n"
            "已自动用你的默认浏览器打开操作界面。\n\n"
            "注意：关闭浏览器不会退出程序；请点界面里的「退出工具」按钮安全退出"
            "（已安装的模组/插件/字体与下载缓存都会保留，不会自动还原）。")
    webbrowser.open(url)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 无窗口 exe 模式下异常无人可见：既落盘 run.log，也弹窗让用户看到
        import traceback
        tb = traceback.format_exc()
        try:
            with open(RUN_LOG, "a", encoding="utf-8") as _f:
                _f.write("\n[致命错误] " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
                _f.write(tb + "\n")
        except Exception:
            pass
        _msgbox("WowAssist - 启动失败", "程序启动出错（已记录到 run.log）：\n\n" + tb[-1500:])
        raise

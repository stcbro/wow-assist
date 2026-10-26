# -*- coding: utf-8 -*-
"""魔兽助手 · 制作更新包（作者侧工具）
用法：双击 制作更新包.bat，按提示输入：
  1) 旧版插件目录（首次可随便填个不存在的路径 = 全量）
  2) 新版插件目录（放着最新插件内容的目录，如 吉米插件包v8.8/Interface/AddOns）
产出（发布\\更新包\\）：
  - 单插件\\*.zip      变化的插件各一个包（zip 内即插件目录内容）
  - manifest.json      新版完整清单（含每插件 file/size/md5，url 从旧 manifest 继承）
  - 上传清单.txt       本次要传的文件 + 操作步骤
更新流程：跑本工具 → 按清单上传变化的 zip → 回填链接 → 上传 manifest.json
"""
import os, sys, json, zipfile, hashlib, time

ADDONS = sys.argv[1] if len(sys.argv) > 1 else ""
NEW = sys.argv[2] if len(sys.argv) > 2 else ""
OLD_MANIFEST = sys.argv[3] if len(sys.argv) > 3 else ""
OUT = r"D:/WorkBuddy/发布/更新包"
IGNORE = {".ok", ".versions.json"}


def dir_signature(path):
    """目录指纹：文件名+大小+mtime 的组合哈希（快，够用于变化检测）。"""
    h = hashlib.md5()
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for f in sorted(files):
            if f in IGNORE:
                continue
            fp = os.path.join(root, f)
            try:
                st = os.stat(fp)
                h.update(("%s|%d|%d\n" % (f, st.st_size, int(st.st_mtime))).encode("utf-8"))
            except OSError:
                pass
    return h.hexdigest()


def zip_plugin(src, dst):
    n = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _, files in os.walk(src):
            for f in files:
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, src)
                z.write(fp, rel.replace("\\", "/"))
                n += 1
    return n


def main():
    print("=" * 56)
    print("魔兽助手 · 制作更新包")
    print("=" * 56)
    new_dir = NEW or input("新版插件目录（如 D:\\...\\Interface\\AddOns）: ").strip().strip('"')
    if not os.path.isdir(new_dir):
        print("目录不存在:", new_dir)
        return
    old_dir = ADDONS or input("旧版插件目录（首次可直接回车=全量）: ").strip().strip('"')
    old_mf_path = OLD_MANIFEST or input("旧 manifest.json 路径（首次可回车）: ").strip().strip('"')
    old_mf = {}
    if old_mf_path and os.path.isfile(old_mf_path):
        with open(old_mf_path, "r", encoding="utf-8") as f:
            old_mf = json.load(f)
    old_plugins = old_mf.get("plugins", {}) or {}

    # 扫描新版
    names = [n for n in sorted(os.listdir(new_dir))
             if os.path.isdir(os.path.join(new_dir, n)) and n not in IGNORE]
    print("\n新版共 %d 个插件，正在对比…" % len(names))

    changed, new_plugins = [], {}
    t0 = time.time()
    for i, n in enumerate(names):
        src = os.path.join(new_dir, n)
        sig = dir_signature(src)
        size = 0
        for root, _, files in os.walk(src):
            for f in files:
                try:
                    size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        old = old_plugins.get(n, {})
        is_new = n not in old_plugins
        is_changed = (old.get("md5") != sig) if not is_new else True
        # 没有旧 manifest 时用目录对比（旧目录存在才比）
        if not old_plugins and old_dir and os.path.isdir(old_dir):
            old_src = os.path.join(old_dir, n)
            if os.path.isdir(old_src):
                is_changed = dir_signature(old_src) != sig
            else:
                is_changed = True
        entry = {"file": n + ".zip", "size": size, "md5": sig,
                 "url": old.get("url", ""), "pwd": old.get("pwd", "")}
        new_plugins[n] = entry
        if is_changed:
            changed.append(n)
        if i % 30 == 0:
            print("  扫描 %d/%d…" % (i + 1, len(names)))

    # 打变化插件的 zip
    if os.path.isdir(OUT):
        import shutil
        shutil.rmtree(OUT)
    single = os.path.join(OUT, "单插件")
    os.makedirs(single, exist_ok=True)
    print("\n正在打包 %d 个变化插件…" % len(changed))
    for i, n in enumerate(changed):
        zip_plugin(os.path.join(new_dir, n), os.path.join(single, n + ".zip"))
        if i % 20 == 0:
            print("  打包 %d/%d…" % (i + 1, len(changed)))

    # manifest（版本号取当前时间，可手动改）
    mf = {"version": input("\n清单版本号（如 8.8，回车用今天日期）: ").strip()
          or time.strftime("%Y%m%d"),
          "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
          "plugins": new_plugins}
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(mf, f, ensure_ascii=False, indent=1)

    # 上传清单
    total = sum(new_plugins[n]["size"] for n in changed)
    lines = ["本次更新要上传的文件（%d 个插件有变化，合计 %.1fMB）" % (len(changed), total / 1048576),
             "=" * 56, ""]
    for i, n in enumerate(changed, 1):
        e = new_plugins[n]
        lines.append("□ 单插件\\%s.zip  (%.1fMB)" % (n, e["size"] / 1048576))
    lines += ["□ manifest.json（必须最后传）", "",
              "操作步骤：",
              "1. 把上面所有 zip 上传到蓝奏云，每个创建分享链接+提取码",
              "2. 链接回填：运行 回填链接.bat，按提示粘贴每个文件的链接和提取码",
              "   （脚本会自动写进 manifest.json）",
              "3. 把回填后的 manifest.json 上传到蓝奏云，覆盖旧清单",
              "4. 把新 manifest.json 的分享链接+提取码，配置到魔兽助手「下载」页",
              "",
              "老用户重启魔兽助手即自动增量更新（只下变化的插件）。"]
    with open(os.path.join(OUT, "上传清单.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\n完成！产出目录: " + OUT)
    print("变化插件 %d 个，新增 manifest.json，详见 上传清单.txt" % len(changed))
    print("用时 %.0f 秒" % (time.time() - t0))
    input("\n回车退出…")


if __name__ == "__main__":
    main()

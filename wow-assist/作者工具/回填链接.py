# -*- coding: utf-8 -*-
"""WowAssist · 回填链接（作者侧工具）
上传完 zip 后运行：按提示把「链接 提取码」逐行粘贴（顺序与上传清单一致），
自动写入 manifest.txt 对应条目。也支持只贴链接（无提取码）。
"""
import os, json, re, sys

MANIFEST = r"D:/WorkBuddy/发布/更新包/manifest.txt"


def main():
    if not os.path.isfile(MANIFEST):
        print("找不到 manifest.txt，请先运行 制作更新包.bat")
        input("回车退出…")
        return
    with open(MANIFEST, "r", encoding="utf-8") as f:
        mf = json.load(f)
    plugins = mf.get("plugins", {})
    need = [n for n, e in plugins.items() if not e.get("url")]
    print("=" * 56)
    print("回填链接：共 %d 个条目，其中 %d 个缺链接" % (len(plugins), len(need)))
    print("=" * 56)
    if not need:
        print("全部都有链接，无需回填。")
        input("回车退出…")
        return
    print("\n请把每个文件的分享链接按顺序粘贴进来，每行一个。")
    print("格式：链接 [空格 提取码]    例如：")
    print("  https://sycc.lanzoum.com/b01i5y3r7c 9p81")
    print("粘贴完毕后输入单独一行 done 结束：\n")
    lines = []
    while True:
        try:
            ln = input().strip()
        except EOFError:
            break
        if ln.lower() == "done" or ln == "":
            if lines:
                break
            continue
        lines.append(ln)
    if not lines:
        print("没有输入任何链接。")
        input("回车退出…")
        return
    if len(lines) != len(need):
        print("提示：输入 %d 行，缺链接 %d 个，按顺序尽量对应。" % (len(lines), len(need)))
    ok = 0
    for i, ln in enumerate(lines):
        parts = ln.split()
        url = parts[0] if parts else ""
        pwd = parts[1] if len(parts) > 1 else ""
        m = re.match(r"https?://\S+", url)
        if not m:
            continue
        if i < len(need):
            plugins[need[i]]["url"] = url
            plugins[need[i]]["pwd"] = pwd
            ok += 1
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(mf, f, ensure_ascii=False, indent=1)
    print("\n已回填 %d 个链接。剩余缺链接: %d" % (
        ok, sum(1 for e in plugins.values() if not e.get("url"))))
    print("现在把 manifest.txt 上传到蓝奏云（覆盖旧清单），并把它的分享链接")
    print("配置到WowAssist「下载」页的 manifest 栏，老用户重启即自动更新。")
    input("\n回车退出…")


if __name__ == "__main__":
    main()

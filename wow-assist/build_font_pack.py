# -*- coding: utf-8 -*-
"""仅重建 字体 资源包 wowassist_字体.zip（思源黑体 / Noto Sans SC 替换版）。

只重建字体卷，不动 模组包 / 插件包（避免重新上传上百 MB 的插件分卷）。
素材源：工程内资源镜像 <工程>/wow-assist/.wbdata/resources/Fonts
        （已就地替换为 思源黑体 Regular，9 个槽位文件 + .ok 标记）
zip 内统一前缀：Fonts/

用法：
    python build_font_pack.py
"""
import os
import zipfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_FONTS = os.path.normpath(
    os.path.join(HERE, ".wbdata", "resources", "Fonts"))
OUT = r"D:/WorkBuddy/发布/蓝奏云资源包"
ZIP_PATH = os.path.join(OUT, "wowassist_字体.zip")


def main():
    if not os.path.isdir(SRC_FONTS):
        raise SystemExit("[错误] 找不到字体素材源: " + SRC_FONTS)
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    n = 0
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _, files in os.walk(SRC_FONTS):
            for f in sorted(files):
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, SRC_FONTS)
                z.write(fp, "Fonts/" + rel.replace("\\", "/"))
                n += 1
                print("  + Fonts/" + rel.replace("\\", "/"))
    sz = os.path.getsize(ZIP_PATH)
    print("\n[完成] 字体包已重建: %s" % ZIP_PATH)
    print("  文件数: %d  体积: %.1f MB  用时: %.0f 秒"
          % (n, sz / 1048576, time.time() - t0))
    if sz > 100 * 1024 * 1024:
        print("  [警告] 超过蓝奏云 100MB 单文件上限，上传会失败！")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""仅重建 模组 资源包 wowassist_模组包.zip（已剔除 VanillaFixes.exe / 使用说明.txt / 文字高清模组.rar / .ok）。

只重建模组卷，不动 字体 / 插件 包（避免重新上传上百 MB 的分卷）。
素材源：工程内资源镜像 <工程>/wow-assist/.wbdata/resources/模组包
zip 内统一前缀：模组包/

用法：
    python build_mods_pack.py
"""
import os
import zipfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_MODS = os.path.normpath(
    os.path.join(HERE, ".wbdata", "resources", "模组包"))
OUT = r"D:/WorkBuddy/发布/蓝奏云资源包"
ZIP_PATH = os.path.join(OUT, "wowassist_模组包.zip")


def main():
    if not os.path.isdir(SRC_MODS):
        raise SystemExit("[错误] 找不到模组素材源: " + SRC_MODS)
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    n = 0
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _, files in os.walk(SRC_MODS):
            for f in sorted(files):
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, SRC_MODS)
                z.write(fp, "模组包/" + rel.replace("\\", "/"))
                n += 1
                print("  + 模组包/" + rel.replace("\\", "/"))
    sz = os.path.getsize(ZIP_PATH)
    print("\n[完成] 模组包已重建: %s" % ZIP_PATH)
    print("  文件数: %d  体积: %.1f MB  用时: %.0f 秒"
          % (n, sz / 1048576, time.time() - t0))


if __name__ == "__main__":
    main()

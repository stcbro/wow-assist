# -*- coding: utf-8 -*-
"""生成精简交接包 zip（源码+脚本+exe+AI记忆+文档，排除大资源与构建产物）"""
import os, zipfile, sys, time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = r"D:/WorkBuddy/黑猫助手20261023"
OUT = os.path.join(ROOT, "魔兽助手-交接包-20261026.zip")

# (源相对路径, 包内路径)
items = []
add = lambda s, d=None: items.append((s, d or s))

# 1) 主工程源码与工具
for f in ["addon_helper.py", "ui.html", "lanzou_core.py",
          "capy.ico", "capy_favicon.ico", "web_logo.png",
          "打包exe.bat", "上传蓝奏云.py", "验证分发链接.py",
          "启动插件助手.bat", "启动插件助手-无窗口.vbs", "打开插件助手界面.url"]:
    p = os.path.join("插件助手", f)
    if os.path.isfile(os.path.join(ROOT, p)):
        add(p)

# 2) 单元测试与资源包制作脚本
for f in ["test_persist.py", "build_lanzou_packs.py"]:
    p = os.path.join("插件助手", "temp", f)
    if os.path.isfile(os.path.join(ROOT, p)):
        add(p, os.path.join("插件助手", "temp", f))

# 3) 交付 exe（带版本号）
for f in os.listdir(os.path.join(ROOT, "插件助手")):
    if f.startswith("魔兽助手 v") and f.endswith(".exe"):
        add(os.path.join("插件助手", f))

# 4) AI 记忆（接续上下文）
mdir = os.path.join(ROOT, ".workbuddy", "memory")
if os.path.isdir(mdir):
    for f in sorted(os.listdir(mdir)):
        if f.endswith(".md"):
            add(os.path.join(".workbuddy", "memory", f))

# 5) 顶层文档
for f in ["开发交接文档.md", ".gitignore", "黑猫助手分析报告.md"]:
    if os.path.isfile(os.path.join(ROOT, f)):
        add(f)

print("待打包 %d 个文件：" % len(items))
total = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for src, dst in items:
        p = os.path.join(ROOT, src)
        z.write(p, dst)
        total += os.path.getsize(p)
print("解压后合计: %.1f MB" % (total / 1048576))
print("输出: %s (%.1f MB)" % (OUT, os.path.getsize(OUT) / 1048576))
print("\n包内清单:")
with zipfile.ZipFile(OUT) as z:
    for i in z.namelist():
        print("   ", i)

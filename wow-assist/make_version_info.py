# -*- coding: utf-8 -*-
"""生成 PyInstaller 版本信息文件 version_info.txt（exe 右键属性→详细信息可见）。
用法：python 生成本版本信息.py 3.13
行业惯例：版权标识写进二进制资源的 VS_VERSIONINFO，比界面文字更正式、不可被界面篡改。
"""
import io, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ver = (sys.argv[1] if len(sys.argv) > 1 else "0").strip().strip('"')
parts = [int(x) for x in ver.split(".") if x.isdigit()]
while len(parts) < 4:
    parts.append(0)
ver4 = parts[:4]
ver_str = ".".join(str(x) for x in ver4)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "version_info.txt")

tpl = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, {d}), prodvers=({a}, {b}, {c}, {d}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404b0', [
        StringStruct('CompanyName', 'Bro.Cui'),
        StringStruct('FileDescription', 'WowAssist 香草旧世魔兽游戏助手'),
        StringStruct('FileVersion', '{vs}'),
        StringStruct('InternalName', 'wowassist'),
        StringStruct('LegalCopyright', 'Copyright (C) 2026 Bro.Cui. All rights reserved.'),
        StringStruct('OriginalFilename', 'wowassist.exe'),
        StringStruct('ProductName', 'WowAssist'),
        StringStruct('ProductVersion', '{vs}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
txt = tpl.format(a=ver4[0], b=ver4[1], c=ver4[2], d=ver4[3], vs=ver_str)
io.open(OUT, "w", encoding="utf-8").write(txt)
print("[版本信息] version_info.txt 已生成（FileVersion=%s, 版权=Bro.Cui）" % ver_str)

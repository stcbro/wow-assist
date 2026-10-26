# -*- coding: utf-8 -*-
"""黑猫助手 解包 v5 —— 全量提取（研究用途）"""
import struct, os, json, hashlib

path = r"D:\WorkBuddy\黑猫助手20261023\黑猫助手.exe"
data = open(path, "rb").read()
HOST_END = 0x1f000
overlay = data[HOST_END:]
OUT = r"D:\WorkBuddy\黑猫助手20261023\LanzouTool\extracted"
os.makedirs(OUT, exist_ok=True)

BIG_SIZE = 24929280
big = overlay[:BIG_SIZE]
open(os.path.join(OUT, "1_主程序大模块.dll"), "wb").write(big)
print(f"[1] 主程序大模块: {BIG_SIZE/1024/1024:.2f} MB  sha256={hashlib.sha256(big).hexdigest()[:16]}...")

# bundle 清单
name0 = "黑猫助手.dll".encode("utf-8")
marker = bytes([0x01, len(name0)]) + name0
p = overlay.find(marker, 0x17e0000)
entries = []
while p + 2 <= len(overlay):
    try:
        ctype = overlay[p]
        namelen = overlay[p + 1]
        if ctype not in (1, 2, 3, 4, 5, 6, 8) or namelen == 0 or namelen > 300:
            break
        name = overlay[p + 2:p + 2 + namelen].decode("utf-8", "replace")
        off, size, csize = struct.unpack_from("<QQQ", overlay, p + 2 + namelen)
        if off + (csize or size) > len(overlay) or size == 0:
            break
        entries.append((name, off, size, csize, ctype))
        p = p + 2 + namelen + 24
    except struct.error:
        break

print(f"\n[2] bundle 条目 ({len(entries)}):")
for name, off, size, csize, ctype in entries:
    blob = overlay[off:off + (csize if csize else size)]
    fn = os.path.join(OUT, "2_" + name.replace("/", "_"))
    open(fn, "wb").write(blob)
    print(f"    type={ctype} {name:45s} size={size:>9d}  sha256={hashlib.sha256(blob).hexdigest()[:12]}")

# deps.json 在文件末尾 24 字节被截断——直接从其内容定位提取
i = data.rfind("黑猫助手.deps.json".encode("utf-8"))
# deps.json 内容起点: 其条目 name 结束即内容（被截断的清单）。内容其实是 bundle 里 off 指向的位置
# 从 System.Management 条目内容之后找 JSON 开头
j = data.rfind(b'{"runtimeTarget', 0, len(data))
if j < 0:
    j = data.rfind(b'{\r\n  "runtimeTarget', 0, len(data))
deps_blob = data[j:]
open(os.path.join(OUT, "2_黑猫助手.deps.json"), "wb").write(deps_blob)
print(f"\n[3] deps.json 直接定位 @ {hex(j)}  ({len(deps_blob)} bytes)")

deps, _ = json.JSONDecoder().raw_decode(deps_blob.decode("utf-8", "replace"))
print("    依赖清单:")
for tfm, libs in deps.get("targets", {}).items():
    for lib, meta in libs.items():
        print(f"      - {lib}")
print("    条目类型:", {k: v.get("type") for k, v in deps.get("libraries", {}).items()})

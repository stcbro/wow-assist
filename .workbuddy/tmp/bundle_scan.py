# -*- coding: utf-8 -*-
"""解析 overlay 内嵌 PE + 文件尾 bundle 结构"""
import struct

path = r"D:\WorkBuddy\黑猫助手20261023\黑猫助手.exe"
data = open(path, "rb").read()
HOST_END = 0x1f000
overlay = data[HOST_END:]

def parse_pe_at(buf, off, label):
    if buf[off:off+2] != b"MZ":
        print(f"[{label}] 非 MZ")
        return
    e_lfanew = struct.unpack_from("<I", buf, off + 0x3c)[0]
    sig = buf[off+e_lfanew:off+e_lfanew+4]
    if sig[:2] != b"PE":
        print(f"[{label}] e_lfanew={hex(e_lfanew)} sig={sig} 不是有效 PE")
        return
    machine, nsec, tstamp = struct.unpack_from("<HHI", buf, off+e_lfanew+4)
    opt_off = off + e_lfanew + 24
    magic = struct.unpack_from("<H", buf, opt_off)[0]
    print(f"[{label}] machine={hex(machine)} sections={nsec} timestamp={tstamp} magic={hex(magic)}")
    sec_off = opt_off + (240 if magic == 0x20b else 224)
    total_raw = 0
    for i in range(nsec):
        name = buf[sec_off:sec_off+8].rstrip(b"\x00").decode(errors="replace")
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", buf, sec_off+8)
        print(f"   {name:8s} raw={rsize:>10} va={hex(vaddr)}")
        total_raw = max(total_raw, raddr + rsize)
        sec_off += 40
    print(f"   -> 该 PE 占用约 {total_raw} bytes ({total_raw/1024/1024:.2f} MB)")
    return total_raw

# overlay 开头的 PE
sz = parse_pe_at(overlay, 0, "overlay开头PE")

# 文件尾部
print("\n文件尾 256 字节 hex:")
print(data[-256:].hex())
print("\n文件尾 ASCII 尝试:")
tail = data[-4096:]
import re
for m in re.finditer(rb"[\x20-\x7e]{6,}", tail):
    print("  ", m.group().decode()[:120])

# bundle 头通常在尾部：Bundle Manifest: num_embedded_files(7字节前缀?)
# .NET bundle 头: major,minor(2B) + num_embedded(4B) + bundle_id(字符串) ...
# 我们直接暴力扫描 overlay 找 "黑猫助手" UTF8 出现位置
needle = "黑猫助手".encode("utf-8")
pos = 0
cnt = 0
while cnt < 20:
    i = overlay.find(needle, pos)
    if i < 0: break
    ctx = overlay[max(0,i-48):i+64]
    print(f"\n黑猫助手 @ overlay+{hex(i)}: {ctx!r}"[:220])
    pos = i + 1; cnt += 1

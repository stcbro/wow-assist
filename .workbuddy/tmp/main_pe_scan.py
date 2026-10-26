# -*- coding: utf-8 -*-
"""检查内嵌主 PE 的导入表 + 完整 bundle 文件清单"""
import struct, re, io
import pefile

path = r"D:\WorkBuddy\黑猫助手20261023\黑猫助手.exe"
data = open(path, "rb").read()
HOST_END = 0x1f000
overlay = data[HOST_END:]

# 内嵌 PE 的完整数据（用其 .text raw size 估计结束位置）
e_lfanew = struct.unpack_from("<I", overlay, 0x3c)[0]
sec_off = 0 + e_lfanew + 24 + 224  # PE32
nsec = struct.unpack_from("<H", overlay, e_lfanew+6)[0]
end = 0
for i in range(nsec):
    rsize, raddr = struct.unpack_from("<II", overlay, sec_off+16)
    end = max(end, raddr + rsize)
    sec_off += 40
print(f"内嵌主 PE 结束: {end} ({end/1024/1024:.2f} MB)")

pe = pefile.PE(data=overlay[:end], fast_load=False)
print("\n=== 内嵌主 PE 导入表 ===")
net = False
try:
    for e in pe.DIRECTORY_ENTRY_IMPORT:
        dll = e.dll.decode()
        funcs = [i.name.decode() for i in e.imports if i.name]
        interesting = [f for f in funcs if any(k in f.lower() for k in ("socket","connect","internet","http","url","wininet","wsa","send","recv","dns","getaddrinfo"))]
        flag = " <-- 网络相关" if interesting else ""
        print(f"{dll}: {len(funcs)} 函数{flag}")
        if interesting: 
            net = True
            for f in interesting[:12]: print("    ", f)
except Exception as ex:
    print("err:", ex)

# TLS 证书目录 / 签名
print("\n内嵌 PE 是否有签名目录:", pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size)

# bundle 尾部 manifest 提取文件名+偏移+大小
print("\n=== Bundle 清单解析（尾部） ===")
tail = data[-8192:]
# 记录格式近似: 01 LL <name> 00 <offset 8B> <size 8B> ... 直接正则
for m in re.finditer(rb"[\x20-\x7e\xe4-\xe9\x80-\xbf\x00]{4,120}?\.(?:dll|json|exe|resources)", data[-65536:]):
    s = m.group().replace(b"\x00", b"")
    try:
        t = s.decode("utf-8", errors="ignore")
    except Exception:
        continue
    if len(t) > 4 and "\\" not in t[:3]:
        print("  ", t[:100])

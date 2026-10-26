# -*- coding: utf-8 -*-
"""分析 overlay 与嵌入文件签名"""
import pefile, hashlib, math, re
from collections import Counter

path = r"D:\WorkBuddy\黑猫助手20261023\黑猫助手.exe"
data = open(path, "rb").read()
pe = pefile.PE(path, fast_load=True)
end = max(s.PointerToRawData + s.SizeOfRawData for s in pe.sections)
overlay = data[end:]
print(f"PE 节区结束偏移: {hex(end)} ({end})")
print(f"Overlay 大小: {len(overlay)} bytes ({len(overlay)/1024/1024:.2f} MB)")
print("Overlay 头 64 字节:", overlay[:64].hex())
print("Overlay 头 ASCII:", overlay[:48])

def entropy(b):
    if not b: return 0
    c = Counter(b)
    return -sum(v/len(b)*math.log2(v/len(b)) for v in c.values())
print(f"Overlay 熵: {entropy(overlay[:1024*1024]):.3f}")

# 常见归档/嵌入签名
sigs = {
    "ZIP/PK": b"PK\x03\x04", "7z": b"7z\xbc\xaf\x27\x1c", "RAR4": b"Rar!\x1a\x07\x00",
    "RAR5": b"Rar!\x1a\x07\x01\x00", "CAB": b"MSCF", "GZIP": b"\x1f\x8b",
    "MZ(PE)": b"MZ", "XZ": b"\xfd7zXZ", "ZSTD": b"\x28\xb5\x2f\xfd",
    "BZIP2": b"BZh", "LZMA": b"\x5d\x00\x00", "NSIS第一标记": b"\xef\xbe\xad\xdeNullsoftInst",
}
for name, sig in sigs.items():
    pos = overlay.find(sig)
    if pos >= 0:
        print(f"  [{name}] 首次出现在 overlay+{hex(pos)}")
        # 统计出现次数
        cnt = overlay.count(sig)
        print(f"      共出现 {cnt} 次")

# .NET bundle 签名两种
for sig in [bytes.fromhex("8b1202b96a612038727b930214d7a03213f5b9e6efae3318ee3b2dce24b36aae"),
            bytes.fromhex("8b1202b96a612038727b930214d7a03213f5b9e6efae3318ee3b2dce24b36aae")]:
    pass
bsig = data.find(bytes.fromhex("8b1202b96a612038727b930214d7a03213f5b9e6efae3318ee3b2dce24b36aae"))
print("\n.NET bundle 签名:", hex(bsig) if bsig >= 0 else "整个文件中未找到")

# 查找 .dll 名称字符串（bundle 文件名表通常是 UTF8）
names = re.findall(rb"[\x20-\x7e]{3,}\.(?:dll|json|exe|pdb|so|dat|resources)", overlay)
from collections import OrderedDict
seen = OrderedDict()
for n in names:
    s = n.decode()
    seen.setdefault(s, 0)
    seen[s] += 1
print(f"\nOverlay 中出现的文件名 ({len(seen)} 种):")
for k, v in list(seen.items())[:100]:
    print(f"  {k}  x{v}")

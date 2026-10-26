# -*- coding: utf-8 -*-
"""深挖 .NET 单文件包与关键字符串"""
import re, struct

path = r"D:\WorkBuddy\黑猫助手20261023\黑猫助手.exe"
data = open(path, "rb").read()

# .NET single-file bundle 签名 (bundle header placeholder)
bundle_sig = bytes.fromhex("8b1202b96a612038727b930214d7a03213f5b9e6efae3318ee3b2dce24b36aae")
idx = data.find(bundle_sig)
print("Bundle 签名偏移:", hex(idx) if idx >= 0 else "未找到")

# 查找 UTF-8 中文串
cn_re = re.compile(rb"(?:[\xe4-\xe9][\x80-\xbf]{2}){2,}[\x20-\x7e\xe4-\xe9\x80-\xbf]{0,60}")
cn = []
seen = set()
for m in cn_re.finditer(data):
    try:
        s = m.group().decode("utf-8")
    except Exception:
        continue
    if s not in seen and len(s) >= 3:
        seen.add(s); cn.append(s)
print(f"UTF-8 中文串: {len(cn)} 条, 样本:")
for s in cn[:150]:
    print("  ", s[:100])

# 所有 http/https URL
urls = re.findall(rb"https?://[\x21-\x7e]+", data)
useen = []
us = set()
for u in urls:
    s = u.decode(errors="replace")
    if s not in us:
        us.add(s); useen.append(s)
print(f"\nURL 共 {len(useen)} 条:")
for s in useen[:80]:
    print("  ", s[:140])

# 域名类
doms = re.findall(rb"[\x20-\x7e]{2,}\.(?:com|cn|net|org|io|cc|top|xyz|me)[/\x00-\x20\"\x27]", data)
dset = set()
out = []
for d in doms:
    s = d[:-1].decode(errors="replace")
    if s not in dset: dset.add(s); out.append(s)
print("\n域名:", out[:60])

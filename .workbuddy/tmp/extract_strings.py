# -*- coding: utf-8 -*-
"""提取 exe 字符串 + 检测捆绑器特征"""
import re, sys

path = r"D:\WorkBuddy\黑猫助手20261023\黑猫助手.exe"
data = open(path, "rb").read()

# ASCII strings >= 6
ascii_re = re.compile(rb"[\x20-\x7e]{6,}")
# UTF-16LE strings >= 6 chars
u16_re = re.compile(rb"(?:[\x20-\x7e]\x00){6,}")

ascii_hits = [m.group().decode() for m in ascii_re.finditer(data)]
u16_hits = [m.group().decode("utf-16le") for m in u16_re.finditer(data)]

def dedupe(seq, minlen=8):
    seen, out = set(), []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return [s for s in out if len(s) >= minlen]

a = dedupe(ascii_hits)
u = dedupe(u16_hits)
print(f"ASCII unique: {len(a)}, UTF16 unique: {len(u)}")

# 特征关键词检测
markers = ["tauri", "webview", "electron", "nsis", "inno", "innoSetup", "Nullsoft",
           "pyinstaller", "python3", "nexe", "pkg/prelude", "wails", "QT",
           "flutter", "cef", "nwjs", "7z", "setup", "install", "upgrade",
           "WebView2", "msedgewebview", "http://", "https://", "github", "gitee",
           "python", "go1.", "rustc", "cargo", ".rs", "dotnet", "clr"]
print("\n=== 框架特征 ===")
low_a = [s.lower() for s in a]
low_u = [s.lower() for s in u]
for m in markers:
    hits_a = [s for s in a if m.lower() in s.lower()][:6]
    hits_u = [s for s in u if m.lower() in s.lower()][:6]
    if hits_a or hits_u:
        print(f"\n[{m}]")
        for h in hits_a: print("  A:", h[:120])
        for h in hits_u: print("  U:", h[:120])

print("\n=== ASCII 字符串样本 (前 80 条, len>=12) ===")
for s in [x for x in a if len(x) >= 12][:80]:
    print(" ", s[:150])

print("\n=== UTF16 字符串样本 (前 80 条) ===")
for s in u[:80]:
    print(" ", s[:150])

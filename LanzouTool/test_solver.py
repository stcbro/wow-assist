# -*- coding: utf-8 -*-
"""离线验证：构造一个模拟的阿里云盾反爬页面，验证 acw_sc__v2 计算是否正确"""
import base64
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanzou_core import AntiCrawler

# ---- 构造模拟数据 ----
arg1 = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"  # 40位
pos_list = [0x17, 0x7, 0x2, 0x10, 0xf, 0x1, 0xb, 0x14, 0x5, 0x18,
            0x9, 0x3, 0x16, 0xd, 0x19, 0x6, 0x13, 0x8, 0x12, 0x4,
            0x1e, 0x1c, 0xc, 0xa, 0x15, 0x11, 0xe, 0x1d, 0x1b, 0x1a,
            0x24, 0x1f, 0x22, 0x23, 0x20, 0x21, 0x25, 0x26, 0x27, 0x28]

mask_str = "a3f19e2b5c7d018f4a6e90d2c4b87f3e15a609d2c8e74b3f"  # 假 mask（44位十六进制，真实场景即为hex串）
# 阿里云字典: 小写在前大写在后 → 编码时用该字典；解码端翻转大小写后用标准表
def to_aliyun_b64(data: bytes) -> str:
    std = base64.b64encode(data).decode().rstrip("=")
    aliyun = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/="
    table = std.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",
        aliyun[:52] + "0123456789+/")
    return std.translate(table)

mask_b64_aliyun = to_aliyun_b64(mask_str.encode())

# 期望结果（模拟 JS 逻辑）
expected_rearranged = "".join(arg1[p - 1] for p in pos_list)
expected = "".join(
    "%02x" % (int(expected_rearranged[i:i+2], 16) ^ int(mask_str[i//2:i//2+2].encode()[0] if False else 0, 16))
    for i in range(0, 0))  # 下面直接按字节算
mask_bytes = bytes.fromhex(mask_str)  # mask 是十六进制串，需按 2 字符=1 字节解码
expected_out = "".join(
    "%02x" % (int(expected_rearranged[i:i+2], 16) ^ mask_bytes[i // 2])
    for i in range(0, min(len(expected_rearranged), len(mask_bytes) * 2) - 1, 2))

# ---- 构造假反爬页面 ----
html = f"""<html><body><script>
var arg1='{arg1}';
var _0x1f2a = [{','.join('0x%x' % p for p in pos_list)}];
var _0x3b4c = "{mask_b64_aliyun}";
var dict = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/=";
function test(){{ var a = "0123456789abcdef"; }}
</script></body></html>"""

# ---- 运行求解 ----
result = AntiCrawler.solve(html)
print("arg1        :", arg1)
print("mask 原文   :", mask_str)
print("期望 cookie :", "acw_sc__v2=" + expected_out)
print("实际 cookie :", result)
print()
assert AntiCrawler.is_anti_crawler_page(html), "识别失败"
print("页面识别    : OK")
assert result == "acw_sc__v2=" + expected_out, "计算不匹配!"
print("计算结果    : 完全一致 ✓")

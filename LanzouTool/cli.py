# -*- coding: utf-8 -*-
"""
cli.py — 命令行入口

用法:
  python cli.py <分享链接> [密码]
  python cli.py                     # 交互模式，逐行输入链接
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lanzou_core import LanzouClient, SUCCESS


def parse_one(client: LanzouClient, url: str, pwd: str = ""):
    print(f"\n[解析] {url}" + (f"  (密码: {pwd})" if pwd else ""))
    if pwd:
        state, link = client.get_direct_link(url, password=pwd, retries=3)
    else:
        state, link = client.get_direct_link(url, retries=2)

    if state == SUCCESS and link:
        st, fi = client.get_file_info(url, pwd)
        if st == SUCCESS and fi:
            for k, v in fi.items():
                if v:
                    print(f"  {k}: {v}")
        print(f"  ✅ 直链: {link}")
        return link
    else:
        print(f"  ❌ 解析失败 ({state})")
        for line in client.log_lines:
            print(f"     {line}")
        return None


def main():
    client = LanzouClient()
    links = []

    if len(sys.argv) > 1:
        url = sys.argv[1]
        pwd = sys.argv[2] if len(sys.argv) > 2 else ""
        link = parse_one(client, url, pwd)
        if link:
            links.append(link)
    else:
        print("蓝奏云直链解析器（交互模式）— 输入链接和可选密码（空格分隔），回车解析，q 退出")
        while True:
            try:
                line = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if line.lower() in ("q", "quit", "exit"):
                break
            parts = line.split()
            if not parts:
                continue
            link = parse_one(client, parts[0], parts[1] if len(parts) > 1 else "")
            if link:
                links.append(link)

    if links:
        print("\n===== 全部直链 =====")
        for l in links:
            print(l)


if __name__ == "__main__":
    main()

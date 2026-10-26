# -*- coding: utf-8 -*-
import pefile, hashlib, sys, re

path = r"D:\WorkBuddy\黑猫助手20261023\黑猫助手.exe"
data = open(path, "rb").read()

print("=== 基本信息 ===")
print("size:", len(data))
print("md5 :", hashlib.md5(data).hexdigest())
print("sha1:", hashlib.sha1(data).hexdigest())
print("sha256:", hashlib.sha256(data).hexdigest())

pe = pefile.PE(path, fast_load=False)
print("\n=== PE 头 ===")
print("Machine:", hex(pe.FILE_HEADER.Machine))
print("TimeDateStamp:", pe.FILE_HEADER.TimeDateStamp)
import datetime
try:
    print("编译时间:", datetime.datetime.utcfromtimestamp(pe.FILE_HEADER.TimeDateStamp).strftime("%Y-%m-%d %H:%M:%S UTC"))
except Exception:
    pass
print("Subsystem:", pe.OPTIONAL_HEADER.Subsystem)
print("EntryPoint:", hex(pe.OPTIONAL_HEADER.AddressOfEntryPoint))

print("\n=== 节区 ===")
for s in pe.sections:
    name = s.Name.decode(errors="replace").strip("\x00")
    print(f"{name:10s} VA=0x{s.VirtualAddress:08x} VSize={s.Misc_VirtualSize:8d} RawSize={s.SizeOfRawData:8d} entropy={s.get_entropy():.2f}")

print("\n=== 导入 DLL ===")
try:
    for e in pe.DIRECTORY_ENTRY_IMPORT:
        dll = e.dll.decode()
        funcs = [i.name.decode() for i in e.imports if i.name]
        print(f"{dll} ({len(funcs)} funcs): {', '.join(funcs[:15])}{' ...' if len(funcs)>15 else ''}")
except Exception as ex:
    print("no imports:", ex)

print("\n=== 版本信息 ===")
try:
    for fi in pe.FileInfo[0]:
        if fi.Key.decode() == "StringFileInfo":
            for st in fi.StringTable:
                for k, v in st.entries.items():
                    print(f"{k.decode():20s}: {v.decode(errors='replace')}")
except Exception as ex:
    print("no version info:", ex)

print("\n=== 签名 ===")
try:
    d = pe.OPTIONAL_HEADER.DATA_DIRECTORY[4]
    print("Certificate dir:", d.VirtualAddress, d.Size)
except Exception:
    pass

# -*- coding: utf-8 -*-
"""将指定目录移入 Windows 回收站（可恢复），SHFileOperationW"""
import ctypes
from ctypes import wintypes
import sys

FO_DELETE = 3
FOF_ALLOWUNDO = 0x40   # 移入回收站而非永久删除
FOF_NOCONFIRMATION = 0x10
FOF_NOERRORUI = 0x400
FOF_SILENT = 0x0004

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", ctypes.c_uint),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]

def recycle(path):
    # 路径必须是双 null 结尾
    src = path.rstrip("\\/") + "\x00\x00"
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = src
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    # 关键：必须设 argtypes 防 64 位指针截断
    ctypes.windll.shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
    ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return ret

path = sys.argv[1]
import os
if not os.path.exists(path):
    print("路径不存在:", path); sys.exit(0)
ret = recycle(path)
if os.path.exists(path):
    print(f"ret={ret} 但目录仍在（可能重试/检查）")
    sys.exit(1)
else:
    print(f"✅ 已移入回收站: {path}")

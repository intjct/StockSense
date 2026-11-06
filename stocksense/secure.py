"""Keeps the login session unreadable to other Windows users / copied files.

On Windows we use DPAPI (CryptProtectData): only this Windows account on this
PC can decrypt it. Elsewhere (tests on Linux) it is just base64."""
from __future__ import annotations

import base64
import os

IS_WIN = os.name == "nt"

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    def _call(fn, data: bytes) -> bytes:
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _BLOB()
        if fn == "protect":
            ok = _crypt32.CryptProtectData(ctypes.byref(blob_in), "StockSense", None, None, None, 0,
                                           ctypes.byref(blob_out))
        else:
            ok = _crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0,
                                             ctypes.byref(blob_out))
        if not ok:
            raise OSError("DPAPI failed")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(blob_out.pbData)


def protect(text: str) -> str:
    raw = text.encode("utf-8")
    if IS_WIN:
        raw = _call("protect", raw)
        return "dpapi:" + base64.b64encode(raw).decode("ascii")
    return "b64:" + base64.b64encode(raw).decode("ascii")


def unprotect(blob: str) -> str:
    if not blob:
        return ""
    try:
        kind, data = blob.split(":", 1)
        raw = base64.b64decode(data)
        if kind == "dpapi":
            if not IS_WIN:
                return ""
            raw = _call("unprotect", raw)
        return raw.decode("utf-8")
    except Exception:
        return ""

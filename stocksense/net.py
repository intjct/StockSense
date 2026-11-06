"""One small HTTP layer for every data source, with friendly Thai errors and a
day cache on disk. Tests swap `Http.transport` for a fake."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time

import requests

from . import VERSION
from .settings import config_dir

UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
# SEC asks every program to say who it is: a name plus a contact email (only SEC sees this).
UA_SEC = f"StockSense thisnott@gmail.com StockSense/{VERSION} (personal investing tool; https://github.com/intjct/StockSense)"


class SourceError(Exception):
    """kind: network | key | quota | notfound | other. `th` is shown to the user."""

    def __init__(self, kind: str, th: str, source: str = ""):
        super().__init__(f"{source}:{kind}: {th}")
        self.kind, self.th, self.source = kind, th, source


NAMES = {"yahoo": "ราคาหุ้น", "sec": "งบการเงิน (SEC)", "finnhub": "ข่าวและนักวิเคราะห์ (Finnhub)",
         "gemini": "AI (Gemini)", "fx": "อัตราแลกเปลี่ยน"}


def friendly(source: str, status: int | None, body: str = "") -> SourceError:
    name = NAMES.get(source, source)
    low = (body or "").lower()
    if status is None:
        return SourceError("network", f"ต่อ{name}ไม่ได้ ลองเช็กอินเทอร์เน็ตแล้วกดใหม่", source)
    if status == 429 or "quota" in low or "resource_exhausted" in low:
        return SourceError("quota", f"ใช้{name}ครบโควตาฟรีแล้ว รอสักพัก (หรือพรุ่งนี้) แล้วลองใหม่", source)
    if status in (401, 403) or "api_key_invalid" in low or "api key not valid" in low:
        if source in ("gemini", "finnhub"):
            return SourceError("key", f"คีย์ของ{name}ใช้ไม่ได้ ลองเช็กในหน้าตั้งค่า", source)
        if "undeclared" in low or "automated tool" in low:
            return SourceError("other", f"{name}ไม่รับรู้ว่าโปรแกรมนี้คือใคร (รหัส {status}) แจ้งผู้สร้างโปรแกรมได้เลย", source)
        if "rate" in low and ("threshold" in low or "limit" in low):
            return SourceError("other", f"{name}บล็อกชั่วคราวเพราะขอข้อมูลถี่เกินไป (รหัส {status}) รอประมาณ 10 นาทีแล้วลองใหม่", source)
        return SourceError("other", f"{name}ไม่ยอมให้ดึงข้อมูลตอนนี้ (รหัส {status}) ลองใหม่อีกครั้งภายหลัง", source)
    if status == 400 and source == "gemini" and "key" in low:
        return SourceError("key", f"คีย์ของ{name}ใช้ไม่ได้ ลองเช็กในหน้าตั้งค่า", source)
    if status == 404:
        return SourceError("notfound", f"ไม่เจอข้อมูลนี้ใน{name}", source)
    return SourceError("other", f"{name}มีปัญหาชั่วคราว ลองใหม่อีกครั้ง", source)


class Http:
    """transport(method, url, headers, params, json_body, timeout) -> (status, text).
    status None means the network failed."""

    def __init__(self, transport=None):
        self.transport = transport or self._requests
        self._session = requests.Session()
        self.last_sec = 0.0

    def _requests(self, method, url, headers, params, json_body, timeout):
        try:
            r = self._session.request(method, url, headers=headers, params=params, json=json_body,
                                      timeout=timeout)
            return r.status_code, r.text
        except requests.RequestException:
            return None, ""

    def call(self, source: str, method: str, url: str, *, headers=None, params=None, json_body=None,
             timeout: float = 25) -> str:
        h = {"User-Agent": UA_SEC if source == "sec" else UA_BROWSER, "Accept-Encoding": "gzip, deflate"}
        h.update(headers or {})
        if source == "sec":                       # SEC allows 10 requests a second; stay well below
            wait = 0.15 - (time.time() - self.last_sec)
            if wait > 0:
                time.sleep(wait)
            self.last_sec = time.time()
        status, text = self.transport(method, url, h, params, json_body, timeout)
        if status is None or status >= 300:
            raise friendly(source, status, text)
        return text

    def get_json(self, source: str, url: str, **kw):
        text = self.call(source, "GET", url, **kw)
        try:
            return json.loads(text)
        except ValueError:
            raise SourceError("other", f"{NAMES.get(source, source)}ส่งข้อมูลแปลกๆ มา ลองใหม่อีกครั้ง", source)

    def get_text(self, source: str, url: str, **kw) -> str:
        return self.call(source, "GET", url, **kw)

    def post_json(self, source: str, url: str, body, **kw):
        text = self.call(source, "POST", url, json_body=body,
                         headers={"Content-Type": "application/json", **kw.pop("headers", {})}, **kw)
        try:
            return json.loads(text)
        except ValueError:
            raise SourceError("other", f"{NAMES.get(source, source)}ส่งข้อมูลแปลกๆ มา ลองใหม่อีกครั้ง", source)


class Cache:
    """JSON files in %APPDATA%\\StockSense\\cache, each with its own age limit."""

    def __init__(self, folder: str | None = None):
        self.folder = folder or os.path.join(config_dir(), "cache")
        os.makedirs(self.folder, exist_ok=True)

    def _path(self, key: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)[:60]
        return os.path.join(self.folder, f"{safe}-{hashlib.sha1(key.encode()).hexdigest()[:8]}.json")

    def get(self, key: str, max_age: float):
        p = self._path(key)
        try:
            if time.time() - os.path.getmtime(p) > max_age:
                return None
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def put(self, key: str, value) -> None:
        p = self._path(key)
        tmp = f"{p}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False)
        os.replace(tmp, p)

    def remember(self, key: str, max_age: float, make):
        v = self.get(key, max_age)
        if v is None:
            v = make()
            self.put(key, v)
        return v


HOUR = 3600
DAY = 24 * HOUR

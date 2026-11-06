"""Where every number comes from.

| data                          | source                         | key        |
|-------------------------------|--------------------------------|------------|
| price history, current price  | Yahoo Finance chart            | none       |
| USD -> THB                    | open.er-api.com (Yahoo backup) | none       |
| company list, statements,     | SEC EDGAR (official filings)   | none       |
|   filings text                |                                |            |
| news, analysts, earnings,     | Finnhub (free plan)            | user's own |
|   valuation ratios            |                                |            |
| plain-Thai explanations       | Gemini                         | user's own |
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from html.parser import HTMLParser

from .net import DAY, HOUR, Cache, Http, SourceError

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
FX_URL = "https://open.er-api.com/v6/latest/USD"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_SUBS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"
FINNHUB = "https://finnhub.io/api/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Stable models first; the next one is tried only if Google has retired the previous.
GEMINI_MODELS = ("gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-flash-latest")

# Index funds people commonly hold. They have no company statements.
ETFS = {
    "SPY": "SPDR S&P 500 ETF", "VOO": "Vanguard S&P 500 ETF", "IVV": "iShares Core S&P 500 ETF",
    "SPLG": "SPDR Portfolio S&P 500 ETF", "QQQ": "Invesco QQQ (Nasdaq-100)", "QQQM": "Invesco Nasdaq-100 ETF",
    "VTI": "Vanguard Total Stock Market ETF", "DIA": "SPDR Dow Jones ETF", "IWM": "iShares Russell 2000 ETF",
    "SCHD": "Schwab US Dividend Equity ETF", "VT": "Vanguard Total World Stock ETF",
    "VUG": "Vanguard Growth ETF", "SOXX": "iShares Semiconductor ETF", "SMH": "VanEck Semiconductor ETF",
    "XLK": "Technology Select Sector SPDR", "ARKK": "ARK Innovation ETF", "GLD": "SPDR Gold Shares",
}
# Names people type that don't appear in the registered company name.
ALIASES = {
    "GOOGLE": "GOOGL", "กูเกิล": "GOOGL", "FACEBOOK": "META", "เฟซบุ๊ก": "META", "INSTAGRAM": "META",
    "S&P 500": "VOO", "S&P500": "VOO", "SP500": "VOO", "NASDAQ": "QQQ", "NASDAQ100": "QQQ",
    "NASDAQ 100": "QQQ", "DOW": "DIA", "DOW JONES": "DIA", "ดาวโจนส์": "DIA",
    "แอปเปิล": "AAPL", "APPLE": "AAPL", "เทสลา": "TSLA", "อเมซอน": "AMZN", "ไมโครซอฟท์": "MSFT",
    "เอ็นวิเดีย": "NVDA", "NVIDIA": "NVDA", "เน็ตฟลิกซ์": "NFLX", "ดิสนีย์": "DIS", "โคคา โคล่า": "KO",
    "COCA COLA": "KO", "COCA-COLA": "KO", "แมคโดนัลด์": "MCD", "สตาร์บัคส์": "SBUX", "ไนกี้": "NKE",
    "TSMC": "TSM", "ไต้หวันเซมิ": "TSM", "BERKSHIRE": "BRK-B", "VISA": "V", "วีซ่า": "V",
}


# ---------------------------------------------------------------- small helpers

def to_date(ts) -> str:
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%d")


class _Text(HTMLParser):
    SKIP = {"script", "style", "head", "title"}
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "table", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
        elif tag == "td":
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(raw: str) -> str:
    p = _Text()
    try:
        p.feed(raw)
        text = "".join(p.out)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(\s*\|\s*)+\n", "\n", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------- sources

class Sources:
    def __init__(self, http: Http | None = None, cache: Cache | None = None,
                 gemini_key: str = "", finnhub_key: str = ""):
        self.http = http or Http()
        self.cache = cache or Cache()
        self.gemini_key = gemini_key
        self.finnhub_key = finnhub_key

    # ---- prices (Yahoo)
    def history(self, sym: str) -> dict:
        """{price, prev_close, name, currency, dates[], closes[], highs[], lows[]} for the last ~1 year."""
        def make():
            d = self.http.get_json("yahoo", YAHOO_CHART.format(sym=sym),
                                   params={"range": "1y", "interval": "1d", "includePrePost": "false"})
            res = (d.get("chart") or {}).get("result") or []
            if not res:
                raise SourceError("notfound", f"ไม่เจอหุ้นชื่อ {sym}", "yahoo")
            r = res[0]
            meta = r.get("meta") or {}
            q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
            rows = [(to_date(t), c, h, lo) for t, c, h, lo in
                    zip(r.get("timestamp") or [], q.get("close") or [], q.get("high") or [], q.get("low") or [])
                    if c is not None and h is not None and lo is not None]
            if not rows:
                raise SourceError("notfound", f"ไม่มีราคาย้อนหลังของ {sym}", "yahoo")
            price = meta.get("regularMarketPrice") or rows[-1][1]
            return {"symbol": sym, "price": float(price),
                    "prev_close": float(meta.get("chartPreviousClose") or meta.get("previousClose") or rows[-1][1]),
                    "name": meta.get("longName") or meta.get("shortName") or sym,
                    "currency": meta.get("currency") or "USD",
                    "dates": [r[0] for r in rows], "closes": [float(r[1]) for r in rows],
                    "highs": [float(r[2]) for r in rows], "lows": [float(r[3]) for r in rows]}
        return self.cache.remember(f"hist-{sym}", 20 * 60, make)

    def price(self, sym: str) -> float:
        return self.history(sym)["price"]

    def usd_thb(self) -> float:
        def make():
            try:
                d = self.http.get_json("fx", FX_URL)
                v = float((d.get("rates") or {})["THB"])
            except (SourceError, KeyError, TypeError, ValueError):
                d = self.http.get_json("yahoo", YAHOO_CHART.format(sym="THB=X"), params={"range": "5d", "interval": "1d"})
                v = float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])
            return {"rate": v}
        return float(self.cache.remember("fx-usdthb", 6 * HOUR, make)["rate"])

    def usd_thb_on(self, date: str) -> float | None:
        """Baht per dollar on a past day (last trading day on or before it). None if Yahoo has no data."""
        def make():
            d0 = dt.date.fromisoformat(date)
            t0 = int(dt.datetime.combine(d0 - dt.timedelta(days=6), dt.time(), dt.timezone.utc).timestamp())
            t1 = int(dt.datetime.combine(d0 + dt.timedelta(days=2), dt.time(), dt.timezone.utc).timestamp())
            d = self.http.get_json("yahoo", YAHOO_CHART.format(sym="THB=X"),
                                   params={"period1": t0, "period2": t1, "interval": "1d"})
            r = ((d.get("chart") or {}).get("result") or [{}])[0]
            q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
            rows = [(to_date(t), c) for t, c in zip(r.get("timestamp") or [], q.get("close") or []) if c]
            rows = [x for x in rows if x[0] <= date] or rows
            return {"rate": float(rows[-1][1]) if rows else 0.0}
        try:
            v = float(self.cache.remember(f"fx-on-{date}", 365 * DAY, make)["rate"])
        except (SourceError, ValueError, TypeError, KeyError):
            return None
        return v or None

    # ---- SEC
    def sec_tickers(self) -> dict:
        """TICKER -> {cik, name}"""
        def make():
            d = self.http.get_json("sec", SEC_TICKERS)
            out = {}
            for row in d.values():
                t = str(row.get("ticker", "")).upper()
                if t and t not in out:
                    out[t] = {"cik": int(row["cik_str"]), "name": row.get("title", t)}
            return out
        return self.cache.remember("sec-tickers", 7 * DAY, make)

    def cik(self, sym: str) -> int | None:
        row = self.sec_tickers().get(sym.upper()) or self.sec_tickers().get(sym.upper().replace("-", "."))
        return row["cik"] if row else None

    def company_facts(self, cik: int) -> dict:
        return self.cache.remember(f"sec-facts-{cik}", 12 * HOUR,
                                   lambda: self.http.get_json("sec", SEC_FACTS.format(cik=cik), timeout=45))

    def submissions(self, cik: int) -> dict:
        def make():
            d = self.http.get_json("sec", SEC_SUBS.format(cik=cik))
            r = (d.get("filings") or {}).get("recent") or {}
            keep = ("form", "accessionNumber", "filingDate", "reportDate", "primaryDocument", "items")
            n = min(200, len(r.get("form") or []))
            return {"name": d.get("name", ""), "recent": {k: (r.get(k) or [""] * n)[:n] for k in keep}}
        return self.cache.remember(f"sec-subs-{cik}", 6 * HOUR, make)

    def filing_files(self, cik: int, acc: str) -> list[str]:
        url = SEC_ARCHIVE.format(cik=cik, acc=acc.replace("-", "")) + "index.json"
        d = self.cache.remember(f"sec-idx-{acc}", 30 * DAY, lambda: self.http.get_json("sec", url))
        return [i.get("name", "") for i in ((d.get("directory") or {}).get("item") or [])]

    def filing_text(self, cik: int, acc: str, name: str) -> str:
        url = SEC_ARCHIVE.format(cik=cik, acc=acc.replace("-", "")) + name
        return self.cache.remember(f"sec-doc-{acc}-{name}", 60 * DAY,
                                   lambda: {"t": html_to_text(self.http.get_text("sec", url, timeout=60))})["t"]

    @staticmethod
    def filing_url(cik: int, acc: str, name: str = "") -> str:
        return SEC_ARCHIVE.format(cik=cik, acc=acc.replace("-", "")) + name

    # ---- Finnhub
    def _fh(self, path: str, params: dict, max_age: float, key: str):
        if not self.finnhub_key:
            raise SourceError("key", "ยังไม่ได้ใส่คีย์ Finnhub ในหน้าตั้งค่า", "finnhub")
        return self.cache.remember(key, max_age, lambda: self.http.get_json(
            "finnhub", FINNHUB + path, params=params, headers={"X-Finnhub-Token": self.finnhub_key}))

    def news(self, sym: str, days: int = 14) -> list[dict]:
        today = dt.date.today()
        d = self._fh("/company-news", {"symbol": sym, "from": str(today - dt.timedelta(days=days)), "to": str(today)},
                     3 * HOUR, f"fh-news-{sym}-{today}")
        items, seen = [], set()
        for n in sorted(d if isinstance(d, list) else [], key=lambda x: -(x.get("datetime") or 0)):
            head = (n.get("headline") or "").strip()
            if not head or head.lower() in seen:
                continue
            seen.add(head.lower())
            items.append({"headline": head, "summary": (n.get("summary") or "").strip()[:400],
                          "source": n.get("source") or "", "url": n.get("url") or "",
                          "date": to_date(n.get("datetime") or 0)})
            if len(items) >= 10:
                break
        return items

    def recommendations(self, sym: str) -> list[dict]:
        d = self._fh("/stock/recommendation", {"symbol": sym}, 12 * HOUR, f"fh-rec-{sym}")
        return d if isinstance(d, list) else []

    def earnings(self, sym: str) -> list[dict]:
        d = self._fh("/stock/earnings", {"symbol": sym, "limit": 8}, 12 * HOUR, f"fh-earn-{sym}")
        return d if isinstance(d, list) else []

    def metrics(self, sym: str) -> dict:
        d = self._fh("/stock/metric", {"symbol": sym, "metric": "all"}, 12 * HOUR, f"fh-metric-{sym}")
        return d if isinstance(d, dict) else {}

    def profile(self, sym: str) -> dict:
        d = self._fh("/stock/profile2", {"symbol": sym}, 7 * DAY, f"fh-prof-{sym}")
        return d if isinstance(d, dict) else {}

    def price_target(self, sym: str) -> dict:
        """Not on every free plan — an empty dict when unavailable."""
        try:
            d = self._fh("/stock/price-target", {"symbol": sym}, 12 * HOUR, f"fh-pt-{sym}")
            return d if isinstance(d, dict) and d.get("targetMean") else {}
        except SourceError as e:
            if e.kind == "key" and self.finnhub_key:
                return {}
            if e.kind in ("other", "notfound"):
                return {}
            raise

    def next_earnings(self, sym: str) -> str:
        today = dt.date.today()
        try:
            d = self._fh("/calendar/earnings", {"symbol": sym, "from": str(today), "to": str(today + dt.timedelta(days=120))},
                         12 * HOUR, f"fh-cal-{sym}-{today}")
        except SourceError as e:
            if e.kind in ("other", "notfound") or (e.kind == "key" and self.finnhub_key):
                return ""
            raise
        rows = sorted((r.get("date") or "" for r in (d or {}).get("earningsCalendar") or []))
        return rows[0] if rows else ""

    # ---- Gemini
    def ask_ai(self, prompt: str) -> dict:
        """Sends one prompt, expects a JSON object back."""
        if not self.gemini_key:
            raise SourceError("key", "ยังไม่ได้ใส่คีย์ Gemini ในหน้าตั้งค่า", "gemini")
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.25}}
        last: SourceError | None = None
        for model in GEMINI_MODELS:
            try:
                d = self.http.post_json("gemini", GEMINI_URL.format(model=model), body,
                                        headers={"x-goog-api-key": self.gemini_key}, timeout=120)
            except SourceError as e:
                last = e
                if e.kind == "notfound":
                    continue
                raise
            parts = (((d.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            return parse_ai_json(text)
        raise last or SourceError("other", "AI ตอบไม่ได้ตอนนี้", "gemini")


def parse_ai_json(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        v = json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        try:
            v = json.loads(m.group(0)) if m else None
        except ValueError:
            v = None
    if not isinstance(v, dict):
        raise SourceError("other", "AI ตอบกลับมาไม่ครบ ลองกดใหม่อีกครั้ง", "gemini")
    return v

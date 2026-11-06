"""A pretend internet for tests and `StockSense.exe --selftest`: every data
source answers with realistic made-up data, so no keys or quota are used."""
from __future__ import annotations

import datetime as dt
import json
import math
from urllib.parse import urlparse

CIK = 1045810


def _chart(sym: str, base: float = 120.0) -> dict:
    today = dt.datetime(2026, 11, 5, 21, tzinfo=dt.timezone.utc)
    ts, c, h, l = [], [], [], []
    for i in range(252):
        d = today - dt.timedelta(days=(251 - i) * 1.45)
        v = base * (0.75 + 0.4 * i / 251) + 6 * math.sin(i / 9)
        ts.append(int(d.timestamp()))
        c.append(round(v, 2))
        h.append(round(v * 1.012, 2))
        l.append(round(v * 0.988, 2))
    return {"chart": {"result": [{"meta": {"currency": "USD", "regularMarketPrice": c[-1], "chartPreviousClose": c[-2],
                                           "longName": {"NVDA": "NVIDIA Corporation", "VOO": "Vanguard S&P 500 ETF"}.get(sym, sym + " Inc")},
                                  "timestamp": ts, "indicators": {"quote": [{"close": c, "high": h, "low": l}]}}]}}


def _facts() -> dict:
    rev, ni, opi, ocf, capex = [], [], [], [], []
    for y in (2023, 2024, 2025, 2026):
        for q in (1, 2, 3, 4):
            if (y, q) > (2026, 3):
                break
            r = 10e9 * (1 + 0.12 * ((y - 2023) * 4 + q))
            if q < 4:
                rev.append({"val": r, "frame": f"CY{y}Q{q}", "form": "10-Q", "end": f"{y}-{q * 3:02d}-28"})
                ni.append({"val": r * 0.45, "frame": f"CY{y}Q{q}", "form": "10-Q", "end": f"{y}-{q * 3:02d}-28"})
                opi.append({"val": r * 0.55, "frame": f"CY{y}Q{q}", "form": "10-Q", "end": f"{y}-{q * 3:02d}-28"})
        if y < 2026:
            yr = sum(10e9 * (1 + 0.12 * ((y - 2023) * 4 + q)) for q in (1, 2, 3, 4))
            rev.append({"val": yr, "frame": f"CY{y}", "form": "10-K", "end": f"{y}-12-28"})
            ni.append({"val": yr * 0.45, "frame": f"CY{y}", "form": "10-K", "end": f"{y}-12-28"})
            ocf.append({"val": yr * 0.5, "frame": f"CY{y}", "form": "10-K", "end": f"{y}-12-28"})
            capex.append({"val": yr * 0.05, "frame": f"CY{y}", "form": "10-K", "end": f"{y}-12-28"})

    def inst(v, end="2026-09-28", form="10-Q"):
        return [{"val": v * 0.8, "end": "2025-09-28", "form": "10-Q"}, {"val": v, "end": end, "form": form}]
    g = {"Revenues": rev, "NetIncomeLoss": ni, "OperatingIncomeLoss": opi,
         "NetCashProvidedByUsedInOperatingActivities": ocf, "PaymentsToAcquirePropertyPlantAndEquipment": capex,
         "CashAndCashEquivalentsAtCarryingValue": inst(40e9), "LongTermDebtNoncurrent": inst(8e9),
         "Liabilities": inst(30e9), "StockholdersEquity": inst(90e9)}
    return {"facts": {"us-gaap": {k: {"units": {"USD": v}} for k, v in g.items()}}}


NEWS = [
    ("NVIDIA beats estimates as data center sales jump", "Revenue rose sharply on AI chip demand."),
    ("New export rules could limit chip sales to China", "Regulators propose tighter limits."),
    ("NVIDIA announces new partnership with major cloud provider", "Multi-year deal."),
    ("Analysts raise targets after strong quarter", "Several brokers lift price targets."),
    ("Stock market rallies broadly on rate hopes", "Indexes up."),
]

TH_NEWS = ["ยอดขายชิปศูนย์ข้อมูลพุ่ง กำไรออกมาดีกว่าที่คาด", "อาจมีกฎใหม่จำกัดการขายชิปให้จีน",
           "จับมือผู้ให้บริการคลาวด์รายใหญ่ สัญญาหลายปี", "นักวิเคราะห์หลายเจ้าปรับราคาเป้าหมายขึ้น",
           "ตลาดหุ้นโดยรวมปรับขึ้น จากความหวังเรื่องดอกเบี้ย"]


def _gemini(prompt: str) -> dict:
    if '"news": [' in prompt and "line_th" in prompt and "ข่าว:" in prompt:
        n = sum(1 for ln in prompt.split("ข่าว:")[-1].splitlines() if ln.startswith("["))
        eff = ["good", "bad", "good", "good", "neutral"]
        out = {"news": [{"i": i, "effect": eff[i % 5], "line_th": TH_NEWS[i % 5]} for i in range(n)]}
    elif "ผลตรวจพอร์ต" in prompt:
        out = {"headline": "พอร์ตของคุณค่อนข้างแข็งแรง แต่ NVDA มีน้ำหนักค่อนข้างมาก และยังซ้อนอยู่ในกองทุนอีกชั้น",
               "watch": ["NVDA เป็นสัดส่วนใหญ่ของพอร์ต ถ้าตกแรงพอร์ตจะได้รับผลมาก",
                         "จับตาวันประกาศงบของ NVDA ที่ใกล้เข้ามา"]}
    elif '"overview"' in prompt:
        out = {"overview": "ไตรมาสล่าสุดขายได้มากขึ้น 40% จากปีก่อน กำไรโตตามกัน", "trend": "ดีขึ้นต่อเนื่อง 8 ไตรมาส",
               "segments": [{"name": "ชิปศูนย์ข้อมูล", "value": "$30 พันล้าน", "change": "โต 55%"},
                            {"name": "การ์ดจอเกม", "value": "$3 พันล้าน", "change": "โต 10%"}],
               "health": "มีเงินสดมากกว่าหนี้หลายเท่า เงินสดจากธุรกิจเป็นบวก", "direction": ["ขยายกำลังผลิตชิป AI"],
               "guidance": "ผู้บริหารคาดว่ายอดขายไตรมาสหน้าจะโตต่อ", "risks": ["ข้อจำกัดการส่งออกไปจีน"],
               "pros": ["กำไรโต", "เงินสดเยอะ", "ตลาดใหม่"], "cons": ["ราคาแพง", "พึ่งลูกค้าน้อยราย", "การแข่งขัน"],
               "effect": "up", "effect_why": "ตัวเลขดีกว่าปีก่อนชัดเจน"}
    else:
        parts = {
            "financials": {"short": "ขายได้มากขึ้น กำไรโตต่อเนื่อง", "detail": "ยอดขายไตรมาสล่าสุดโตประมาณ 20% จากปีก่อน และกำไรโตพอๆ กัน บริษัทมีเงินสดมากกว่าหนี้"},
            "valuation": {"short": "ราคาพอๆ กับปกติของตัวเอง", "detail": "ตอนนี้ต้องจ่ายประมาณ 48 ดอลลาร์ เพื่อซื้อกำไร 1 ดอลลาร์ ใกล้เคียงค่าเฉลี่ย 5 ปีของหุ้นตัวนี้"},
            "earnings": {"short": "กำไรออกมาดีกว่าคาด 3 ใน 4 ไตรมาส", "detail": "3 ไตรมาสล่าสุดกำไรออกมาดีกว่าที่นักวิเคราะห์คาด ประกาศงบครั้งหน้า 19 พ.ย."},
            "analysts": {"short": "ส่วนใหญ่แนะนำซื้อ", "detail": "45 จาก 51 คนแนะนำให้ซื้อ มีแค่ 1 คนแนะนำขาย"},
            "news": {"short": "ข่าวดีมากกว่าข่าวร้าย", "detail": "ข่าวดีเรื่องยอดขายและพาร์ทเนอร์ใหม่ แต่มีข่าวร้ายเรื่องกฎการส่งออกชิปไปจีน"},
            "chart": {"short": "อยู่ในขาขึ้น ใกล้จุดที่ราคามักติด", "detail": "ราคาสูงกว่าราคาเฉลี่ย 200 วัน แปลว่าภาพใหญ่ยังเป็นขาขึ้น แต่ตอนนี้ใกล้แนวต้าน อาจขึ้นต่อยาก"}}
        out = {"headline": "งบดีมาก ข่าวส่วนใหญ่เป็นบวก แต่ราคาแพงกว่าปกติ", "parts": parts, "conflict": "",
               "watch": "จับตาวันประกาศงบครั้งหน้า", "reason_check": "เหตุผลที่คุณซื้อยังจริงอยู่ ยอดขายจากธุรกิจ AI ยังโตต่อเนื่อง"}
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(out, ensure_ascii=False)}]}}]}


class FakeInternet:
    """Use as Http(transport=FakeInternet()). `calls` records every URL asked for."""

    def __init__(self, gemini_status: int = 200, finnhub_status: int = 200):
        self.calls: list[str] = []
        self.gemini_status = gemini_status
        self.finnhub_status = finnhub_status

    def __call__(self, method, url, headers, params, json_body, timeout):
        self.calls.append(url)
        u = urlparse(url)
        p = u.path
        params = params or {}
        ok = lambda d: (200, json.dumps(d))  # noqa: E731
        if "finance.yahoo.com" in u.netloc and p == "/v1/finance/search":
            q = str(params.get("q", "")).lower()
            rows = [("DELL", "Dell Technologies Inc."), ("PLTR", "Palantir Technologies Inc.")]
            return ok({"quotes": [{"symbol": a, "longname": b, "quoteType": "EQUITY", "exchange": "NYQ"}
                                  for a, b in rows if q in a.lower() or q in b.lower()] +
                       [{"symbol": "DELL.DE", "shortname": "Dell DE", "quoteType": "EQUITY", "exchange": "GER"}]})
        if "finance.yahoo.com" in u.netloc:
            sym = p.rsplit("/", 1)[-1]
            if sym == "THB=X":
                if params.get("period1"):
                    t0 = int(params["period1"])
                    ts = [t0 + i * 86400 for i in range(6)]
                    return ok({"chart": {"result": [{"meta": {}, "timestamp": ts,
                                                     "indicators": {"quote": [{"close": [32.5] * 6}]}}]}})
                return ok({"chart": {"result": [{"meta": {"regularMarketPrice": 34.9}}]}})
            if sym in ("NVDA", "AAPL", "VOO", "MSFT"):
                return ok(_chart(sym, 120 if sym == "NVDA" else 400 if sym == "VOO" else 200))
            return ok({"chart": {"result": None, "error": {"code": "Not Found"}}})
        if "er-api.com" in u.netloc:
            return ok({"rates": {"THB": 34.85}})
        if p == "/files/company_tickers.json":
            return ok({"0": {"cik_str": CIK, "ticker": "NVDA", "title": "NVIDIA CORP"},
                       "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
                       "2": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"}})
        if p.startswith("/api/xbrl/companyfacts/"):
            return ok(_facts())
        if p.startswith("/submissions/"):
            return ok({"name": "NVIDIA CORP", "filings": {"recent": {
                "form": ["4", "8-K", "10-Q", "8-K"], "accessionNumber": ["0001-26-1", "0001-26-2", "0001-26-3", "0001-26-4"],
                "filingDate": ["2026-11-01", "2026-10-20", "2026-10-25", "2026-08-01"],
                "reportDate": ["", "2026-10-20", "2026-09-28", ""], "primaryDocument": ["x.xml", "a8k.htm", "q3.htm", "b.htm"],
                "items": ["", "2.02,9.01", "", "5.02"]}}})
        if p.endswith("/index.json"):
            return ok({"directory": {"item": [{"name": "a8k.htm"}, {"name": "q3fy27pr-ex991.htm"}, {"name": "R1.htm"}]}})
        if p.endswith("ex991.htm"):
            return 200, "<html><body><p>NVIDIA Announces Financial Results for Third Quarter</p><table><tr><td>Revenue</td><td>$35.1 billion</td></tr></table><p>Outlook: revenue expected to be $37.5 billion.</p></body></html>"
        if p.endswith("q3.htm"):
            body = "<p>Table of Contents</p><p>Item 2. Management's Discussion and Analysis 25</p>" \
                   "<p>Item 3. Quantitative and Qualitative Disclosures About Market Risk 40</p>" + "<p>filler</p>" * 50 + \
                   "<h2>Item 2. Management's Discussion and Analysis of Financial Condition</h2>" + \
                   "<p>Data Center revenue grew 55% driven by demand for accelerated computing.</p>" * 30 + \
                   "<h2>Item 3. Quantitative and Qualitative Disclosures About Market Risk</h2><p>end</p>"
            return 200, body
        if "finnhub.io" in u.netloc:
            if self.finnhub_status != 200:
                return self.finnhub_status, '{"error":"Invalid API key"}'
            if p.endswith("/company-news"):
                base = int(dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc).timestamp())
                return ok([{"headline": h, "summary": s, "source": "Reuters", "url": f"https://example.com/{i}",
                            "datetime": base - i * 86400} for i, (h, s) in enumerate(NEWS)])
            if p.endswith("/stock/recommendation"):
                return ok([{"period": "2026-11-01", "strongBuy": 20, "buy": 25, "hold": 5, "sell": 1, "strongSell": 0},
                           {"period": "2026-10-01", "strongBuy": 19, "buy": 24, "hold": 6, "sell": 1, "strongSell": 0},
                           {"period": "2026-09-01", "strongBuy": 18, "buy": 24, "hold": 7, "sell": 1, "strongSell": 0},
                           {"period": "2026-08-01", "strongBuy": 17, "buy": 23, "hold": 8, "sell": 2, "strongSell": 0}])
            if p.endswith("/stock/earnings"):
                return ok([{"period": f"2026-0{m}-30", "actual": 0.8 + m / 100, "estimate": 0.75} for m in (3, 6, 9)] +
                          [{"period": "2025-12-31", "actual": 0.7, "estimate": 0.72}])
            if p.endswith("/stock/metric"):
                return ok({"metric": {"peTTM": 48.0, "psTTM": 25.0, "dividendYieldIndicatedAnnual": 0.03},
                           "series": {"annual": {"pe": [{"period": "2025", "v": 50}, {"period": "2024", "v": 60},
                                                        {"period": "2023", "v": 40}, {"period": "2022", "v": 70}]}}})
            if p.endswith("/stock/price-target"):
                return 403, '{"error":"You don\'t have access to this resource."}'
            if p.endswith("/calendar/earnings"):
                return ok({"earningsCalendar": [{"date": "2026-11-19", "symbol": params.get("symbol")}]})
            if p.endswith("/stock/profile2"):
                return ok({"name": "NVIDIA Corp"})
            return 404, "{}"
        if "generativelanguage.googleapis.com" in u.netloc:
            if self.gemini_status != 200:
                return self.gemini_status, '{"error":{"message":"API key not valid. Please pass a valid API key."}}'
            prompt = json_body["contents"][0]["parts"][0]["text"]
            return ok(_gemini(prompt))
        if "api.github.com" in u.netloc:
            return ok({"tag_name": "v0.0.1", "assets": []})
        return None, ""

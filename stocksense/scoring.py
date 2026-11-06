"""The % is worked out here with fixed rules, so the same data always gives the
same number. The AI only explains it in plain Thai — it can't move the score.

Each part scores 0–100 ("how much this part says buy"). Parts with no data
are left out and the rest are re-weighted."""
from __future__ import annotations

import statistics

PARTS = ("financials", "valuation", "earnings", "analysts", "news", "chart")
TITLES = {"financials": "งบการเงิน", "valuation": "ราคาถูกหรือแพง", "earnings": "ผลประกอบการ",
          "analysts": "นักวิเคราะห์", "news": "ข่าว 14 วัน", "chart": "กราฟราคา"}
HELP = {
    "financials": "ดูว่าบริษัทขายของได้มากขึ้นไหม กำไรโตไหม มีเงินสดพอ และหนี้ไม่เยอะเกินไป",
    "valuation": "เทียบราคาหุ้นกับกำไรของบริษัท (เรียกว่า P/E) ยิ่งตัวเลขสูง แปลว่าต้องจ่ายแพงขึ้นเพื่อซื้อกำไร 1 ดอลลาร์",
    "earnings": "ทุกไตรมาสบริษัทประกาศกำไร ดูว่ากำไรจริงออกมาดีกว่าหรือแย่กว่าที่นักวิเคราะห์คาดไว้",
    "analysts": "รวมความเห็นของนักวิเคราะห์จากโบรกเกอร์ต่างๆ ว่าแนะนำซื้อ ถือ หรือขาย",
    "news": "ข่าวของบริษัทในช่วง 14 วันล่าสุด แยกว่าข่าวไหนดีหรือร้ายต่อหุ้น",
    "chart": "ดูจากราคาย้อนหลัง 1 ปี ว่าราคากำลังขึ้นหรือลง และใกล้จุดที่ราคามักเด้ง (แนวรับ) หรือจุดที่มักติด (แนวต้าน)",
}
BUY_WEIGHTS = {"financials": 25, "valuation": 20, "earnings": 15, "analysts": 15, "news": 10, "chart": 15}
SELL_WEIGHTS = {"financials": 15, "valuation": 20, "earnings": 15, "analysts": 10, "news": 15, "chart": 25}


def clamp(v: float, lo: float = 0, hi: float = 100) -> int:
    return int(round(max(lo, min(hi, v))))


def pct(a, b):
    return None if (a is None or b in (None, 0)) else (a - b) / abs(b) * 100


# ---------------------------------------------------------------- chart

def sma(xs: list[float], n: int):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def swing_levels(lows: list[float], highs: list[float], w: int = 5) -> tuple[list[float], list[float]]:
    sup, res = [], []
    for i in range(w, len(lows) - w):
        if lows[i] == min(lows[i - w:i + w + 1]):
            sup.append(lows[i])
        if highs[i] == max(highs[i - w:i + w + 1]):
            res.append(highs[i])
    return sup, res


def chart(h: dict) -> dict:
    closes, price = h["closes"], h["price"]
    s50, s200 = sma(closes, 50), sma(closes, 200)
    sup, res = swing_levels(h["lows"], h["highs"])
    below = [x for x in sup if x < price * 0.995]
    above = [x for x in res if x > price * 1.005]
    support = max(below) if below else min(h["lows"])
    resistance = min(above) if above else None
    f = {
        "price": round(price, 2),
        "avg_50_days": round(s50, 2) if s50 else None,
        "avg_200_days": round(s200, 2) if s200 else None,
        "high_1y": round(max(h["highs"]), 2), "low_1y": round(min(h["lows"]), 2),
        "support": round(support, 2),
        "resistance": round(resistance, 2) if resistance else None,
        "to_support_pct": round(pct(support, price), 1),
        "to_resistance_pct": round(pct(resistance, price), 1) if resistance else None,
        "change_1m_pct": round(pct(price, closes[-22]), 1) if len(closes) > 22 else None,
        "change_3m_pct": round(pct(price, closes[-64]), 1) if len(closes) > 64 else None,
        "broke_support": bool(sup) and price < sup[-1] * 0.98,
    }
    score = 50.0
    if s200:
        score += 15 if price > s200 else -15
    if s50:
        score += 6 if price > s50 else -6
    d_sup = -f["to_support_pct"]                       # how far above the floor (%)
    if d_sup <= 4:
        score += 10
    elif d_sup >= 15:
        score -= 6
    if resistance and f["to_resistance_pct"] is not None and f["to_resistance_pct"] <= 3:
        score -= 8
    if f["broke_support"]:
        score -= 10
    return {"score": clamp(score, 5, 95), "facts": f}


# ---------------------------------------------------------------- valuation

def valuation(metrics: dict, is_etf: bool = False) -> dict:
    if is_etf:
        return {"score": None, "facts": {}}
    m = (metrics or {}).get("metric") or {}
    pe = m.get("peTTM") or m.get("peExclExtraTTM") or m.get("peBasicExclExtraTTM")
    hist = [x.get("v") for x in (((metrics or {}).get("series") or {}).get("annual") or {}).get("pe") or []
            if isinstance(x, dict) and isinstance(x.get("v"), (int, float)) and x.get("v") > 0][:5]
    f = {"pe_now": round(pe, 1) if isinstance(pe, (int, float)) else None,
         "pe_usual_5y": round(statistics.median(hist), 1) if len(hist) >= 3 else None,
         "ps_now": round(m["psTTM"], 1) if isinstance(m.get("psTTM"), (int, float)) else None,
         "dividend_yield_pct": round(m["dividendYieldIndicatedAnnual"], 2)
         if isinstance(m.get("dividendYieldIndicatedAnnual"), (int, float)) else None}
    if f["pe_now"] is None:
        return {"score": None, "facts": f}
    if f["pe_now"] <= 0:
        return {"score": 30, "facts": {**f, "losing_money": True}}
    if f["pe_usual_5y"]:
        r = f["pe_now"] / f["pe_usual_5y"]
        f["vs_usual_pct"] = round((r - 1) * 100)
        score = 82 if r <= 0.8 else 66 if r <= 1.05 else 50 if r <= 1.25 else 36 if r <= 1.5 else 24
    else:
        p = f["pe_now"]
        score = 72 if p < 15 else 60 if p < 25 else 46 if p < 40 else 32
    return {"score": score, "facts": f}


# ---------------------------------------------------------------- statements

def financials(s: dict | None) -> dict:
    if not s or not s.get("has_data"):
        return {"score": None, "facts": {}}
    pts = 0
    g = s.get("revenue_yoy")
    if g is not None:
        pts += 2 if g > 10 else 1 if g > 0 else -1 if g > -10 else -2
    ng = s.get("net_income_yoy")
    if ng is not None:
        pts += 1 if ng > 0 else -1
    last = (s.get("quarters") or [{}])[-1].get("net_income")
    if last is not None:
        pts += 1 if last > 0 else -2
    mn, my = s.get("net_margin_now"), s.get("net_margin_year_ago")
    if mn is not None and my is not None:
        pts += 1 if mn > my + 0.5 else -1 if mn < my - 0.5 else 0
    eq, liab = s.get("equity"), s.get("liabilities")
    if eq and liab is not None:
        r = liab / eq if eq > 0 else 99
        pts += 1 if r < 1 else -1 if r > 2.5 else 0
    cf = [c["ocf"] for c in s.get("cashflow") or [] if c.get("ocf") is not None]
    if cf:
        pts += 1 if cf[-1] > 0 else -1
    f = {"last_quarter": s.get("last_quarter"),
         "sales_growth_vs_last_year_pct": round(g, 1) if g is not None else None,
         "profit_growth_vs_last_year_pct": round(ng, 1) if ng is not None else None,
         "profit_last_quarter_usd": last,
         "profit_margin_now_pct": round(mn, 1) if mn is not None else None,
         "profit_margin_year_ago_pct": round(my, 1) if my is not None else None,
         "debt_to_equity": round(liab / eq, 2) if (eq and eq > 0 and liab is not None) else None,
         "operating_cash_last_year_usd": cf[-1] if cf else None}
    return {"score": clamp(50 + pts * 7, 10, 92), "facts": f}


# ---------------------------------------------------------------- earnings surprises

def earnings(rows: list[dict], next_date: str = "") -> dict:
    rows = [r for r in rows or [] if isinstance(r.get("actual"), (int, float)) and isinstance(r.get("estimate"), (int, float))]
    rows.sort(key=lambda r: r.get("period") or "", reverse=True)
    rows = rows[:4]
    if not rows:
        return {"score": None, "facts": {"next_earnings_date": next_date or None}}
    beats = sum(1 for r in rows if r["actual"] > r["estimate"])
    last = rows[0]
    surprise = pct(last["actual"], last["estimate"]) if last["estimate"] else None
    score = {0: 25, 1: 40, 2: 55, 3: 68, 4: 80}[beats]
    if surprise is not None:
        score += 6 if surprise > 5 else -8 if surprise < -2 else 0
    f = {"beats_last_4": beats, "quarters_counted": len(rows),
         "last_period": last.get("period"), "last_actual_eps": last["actual"], "last_expected_eps": last["estimate"],
         "last_surprise_pct": round(surprise, 1) if surprise is not None else None,
         "next_earnings_date": next_date or None}
    return {"score": clamp(score, 10, 92), "facts": f}


# ---------------------------------------------------------------- analysts

def analysts(recs: list[dict], target: dict | None, price: float) -> dict:
    recs = sorted([r for r in recs or [] if isinstance(r, dict)], key=lambda r: r.get("period") or "", reverse=True)
    if not recs:
        return {"score": None, "facts": {}}
    r = recs[0]
    sb, b, h, s, ss = (int(r.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell"))
    total = sb + b + h + s + ss
    if not total:
        return {"score": None, "facts": {}}
    net = (2 * sb + b - s - 2 * ss) / (2 * total)
    f = {"month": r.get("period"), "analysts": total, "say_buy": sb + b, "say_hold": h, "say_sell": s + ss}
    score = 50 + 42 * net
    if target and target.get("targetMean"):
        up = pct(target["targetMean"], price)
        f.update({"target_avg_usd": round(target["targetMean"], 2), "upside_to_target_pct": round(up, 1)})
        score += 8 if up > 15 else -12 if up < 0 else 0
    if len(recs) >= 3:
        def buy_share(x):
            t = sum(int(x.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell"))
            return (int(x.get("strongBuy") or 0) + int(x.get("buy") or 0)) / t if t else 0
        f["buy_share_change_3m_pct"] = round((buy_share(recs[0]) - buy_share(recs[min(3, len(recs) - 1)])) * 100)
    return {"score": clamp(score, 8, 92), "facts": f}


# ---------------------------------------------------------------- news

def news(classified: list[dict]) -> dict:
    if not classified:
        return {"score": None, "facts": {"count": 0}}
    g = sum(1 for n in classified if n.get("effect") == "good")
    b = sum(1 for n in classified if n.get("effect") == "bad")
    n = len(classified)
    return {"score": clamp(50 + 40 * (g - b) / n, 12, 88), "facts": {"count": n, "good": g, "bad": b, "neutral": n - g - b}}


# ---------------------------------------------------------------- combine

def combine(parts: dict, mode: str = "buy") -> int | None:
    w = BUY_WEIGHTS if mode == "buy" else SELL_WEIGHTS
    tot = num = 0.0
    for k, p in parts.items():
        sc = p.get("score")
        if sc is None:
            continue
        v = sc if mode == "buy" else 100 - sc
        num += v * w[k]
        tot += w[k]
    return clamp(num / tot) if tot else None


def buy_label(score: int) -> tuple[str, str]:
    """(label, tone) tone: good | mid | bad"""
    if score >= 70:
        return "น่าซื้อ", "good"
    if score >= 55:
        return "ก้ำกึ่ง", "mid"
    return "รอก่อน", "bad"


def sell_label(score: int) -> tuple[str, str]:
    if score >= 65:
        return "น่าพิจารณาขาย", "bad"
    if score >= 45:
        return "ถือต่อได้ แต่จับตาดู", "mid"
    return "ถือต่อ", "good"


def part_tone(score: int | None) -> str:
    """Colour of a part: green = good for the stock, red = bad for the stock (same in buy and sell)."""
    if score is None:
        return "none"
    return "good" if score >= 62 else "bad" if score < 45 else "mid"

"""Whole-portfolio maths for the "ตรวจพอร์ต" button and the buy-button portfolio note.

Pure functions, no internet: they take what the Analyzer already fetched.
Everything is deterministic, so the same portfolio gives the same answer."""
from __future__ import annotations

# What the big index funds hold inside, as a rough share of the fund (%).
# Weights drift every day, so these are rounded and only meant to show
# "you already own this stock through your fund". Checked against fund
# sites in Nov 2026. Funds not listed here count as spread-out.
TABLES = {
    "SP500": {"NVDA": 8.0, "AAPL": 7.0, "MSFT": 5.5, "GOOGL": 5.4, "AMZN": 4.0, "AVGO": 2.8, "META": 2.0, "TSLA": 1.7},
    "NDX": {"NVDA": 8.0, "AAPL": 7.0, "MSFT": 5.0, "AMZN": 4.0, "TSLA": 3.5, "META": 3.5, "GOOGL": 3.5},
    "TOTAL": {"NVDA": 6.5, "AAPL": 6.0, "MSFT": 4.5, "AMZN": 3.3, "GOOGL": 4.0},
    "WORLD": {"NVDA": 4.0, "AAPL": 3.8, "MSFT": 3.0, "AMZN": 2.3, "GOOGL": 1.8},
}
ETF_TABLE = {"VOO": "SP500", "SPY": "SP500", "IVV": "SP500", "SPLG": "SP500", "QQQ": "NDX", "QQQM": "NDX",
             "VTI": "TOTAL", "VT": "WORLD"}
SPREAD_OUT = {"DIA", "IWM", "SCHD", "VUG", "GLD"}      # many holdings (or not a stock): not counted as one bet
THEME = {"SOXX", "SMH", "XLK", "ARKK"}                 # one industry only: counted as one bet
SAME_COMPANY = {"GOOG": "GOOGL", "BRK.B": "BRK-B"}

CALM, WARN, DANGER = 20.0, 35.0, 50.0                  # % of portfolio in one bet
STRESS_DROP = 30.0


def norm(t: str) -> str:
    t = (t or "").upper().strip()
    return SAME_COMPANY.get(t, t)


def exposures(items: list[dict]) -> dict:
    """items: [{ticker, value, is_etf}] -> look-through dollars per stock/theme.

    Returns {total, stocks:{T:{direct, via:{ETF:usd}}}, themes:{ETF:usd}}."""
    total = sum(max(i["value"], 0) for i in items)
    stocks: dict[str, dict] = {}
    themes: dict[str, float] = {}

    def slot(t):
        return stocks.setdefault(t, {"direct": 0.0, "via": {}})
    for i in items:
        t, v = norm(i["ticker"]), max(i["value"], 0.0)
        if t in ETF_TABLE:
            for name, w in TABLES[ETF_TABLE[t]].items():
                s = slot(name)
                s["via"][t] = s["via"].get(t, 0.0) + v * w / 100
        elif t in THEME:
            themes[t] = themes.get(t, 0.0) + v
        elif t in SPREAD_OUT or i.get("is_etf"):
            continue
        else:
            slot(t)["direct"] += v
    return {"total": total, "stocks": stocks, "themes": themes}


def bets(ex: dict) -> list[dict]:
    """Every single bet (stock or theme) as % of portfolio, biggest first."""
    total = ex["total"] or 1.0
    out = []
    for t, s in ex["stocks"].items():
        via = sum(s["via"].values())
        tot = s["direct"] + via
        if tot > 0:
            out.append({"name": t, "pct": tot / total * 100, "direct_pct": s["direct"] / total * 100,
                        "via_pct": via / total * 100, "etfs": sorted(s["via"], key=s["via"].get, reverse=True),
                        "theme": False})
    for t, v in ex["themes"].items():
        out.append({"name": t, "pct": v / total * 100, "direct_pct": v / total * 100, "via_pct": 0.0, "etfs": [],
                    "theme": True})
    return sorted(out, key=lambda b: -b["pct"])


def overlaps(all_bets: list[dict]) -> list[dict]:
    """Stocks the person holds directly AND through a fund."""
    return [b for b in all_bets if b["direct_pct"] > 0 and b["via_pct"] > 0.05]


def concentration_score(top_pct: float) -> int:
    return int(round(max(0.0, min(100.0, 100 - max(0.0, top_pct - CALM) * 2.5))))


def stress_loss(top_pct: float, drop: float = STRESS_DROP) -> float:
    return top_pct * drop / 100


def conc_tone(pct: float) -> str:
    return "bad" if pct >= WARN else "mid" if pct >= CALM + 5 else "good"


def health(hold_score: float | None, conc: int) -> tuple[int, str, str]:
    """60% how healthy the stocks you hold look, 40% how spread out you are."""
    h = conc if hold_score is None else 0.6 * hold_score + 0.4 * conc
    s = int(round(h))
    if s >= 70:
        return s, "ค่อนข้างแข็งแรง", "good"
    if s >= 50:
        return s, "พอใช้ ควรจับตา", "mid"
    return s, "ควรระวัง", "bad"


def currency_split(rows: list[dict], fx_now: float | None) -> dict | None:
    """Splits the baht gain/loss into 'the stock moved' and 'the baht moved'.

    rows: [{value, paid, fx_buy}] in USD. Both parts add up exactly to the total."""
    use = [r for r in rows if r.get("fx_buy") and r.get("paid")]
    if not use or not fx_now:
        return None
    value_thb = sum(r["value"] * fx_now for r in use)
    paid_thb = sum(r["paid"] * r["fx_buy"] for r in use)
    stock = sum((r["value"] - r["paid"]) * r["fx_buy"] for r in use)
    money = sum(r["value"] * (fx_now - r["fx_buy"]) for r in use)
    return {"total_thb": value_thb - paid_thb, "stock_thb": stock, "currency_thb": money,
            "value_thb": value_thb, "paid_thb": paid_thb, "counted": len(use), "skipped": len(rows) - len(use)}


def buy_fit(items: list[dict], sym: str, is_etf: bool, amount: float) -> dict | None:
    """What happens to the portfolio mix if `amount` dollars go into `sym`."""
    before = exposures(items)
    if before["total"] <= 0:
        return None
    after = exposures(items + [{"ticker": sym, "value": amount, "is_etf": is_etf}])
    s = norm(sym)

    def pct_of(ex, name):
        b = next((x for x in bets(ex) if x["name"] == name), None)
        return b["pct"] if b else 0.0
    held_direct = sum(i["value"] for i in items if norm(i["ticker"]) == s)
    out = {"amount": amount, "held_value": held_direct, "total_before": before["total"],
           "weight_before": pct_of(before, s), "weight_after": pct_of(after, s)}
    after_bets = bets(after)
    out["top_after"] = after_bets[0] if after_bets else None
    out["fund_weight_after"] = (held_direct + amount) / (before["total"] + amount) * 100 if (is_etf or s in ETF_TABLE) else None
    out["is_fund"] = is_etf
    out["via_funds"] = [e for e in ((after["stocks"].get(s) or {}).get("via") or {})]
    w = out["weight_after"] if not is_etf else (out["top_after"]["pct"] if out["top_after"] else 0.0)
    out["tone"] = conc_tone(w)
    out["level_pct"] = w
    return out

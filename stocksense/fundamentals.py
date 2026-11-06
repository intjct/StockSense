"""Turns SEC "company facts" (every number a company has ever filed) into the
few series a beginner needs: quarterly sales/profit, margins, cash, debt."""
from __future__ import annotations

import re

REVENUE = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
           "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "RevenuesNetOfInterestExpense")
NET_INCOME = ("NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic")
OP_INCOME = ("OperatingIncomeLoss",)
GROSS = ("GrossProfit",)
OCF = ("NetCashProvidedByUsedInOperatingActivities",
       "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")
CAPEX = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")
CASH = ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashAndCashEquivalentsAtCarryingValueIncludingDiscontinuedOperations")
SHORT_INV = ("ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent")
DEBT = ("LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations")
DEBT_CURRENT = ("LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings")
LIABILITIES = ("Liabilities",)
EQUITY = ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")

Q_FRAME = re.compile(r"^CY(\d{4})Q([1-4])$")
Y_FRAME = re.compile(r"^CY(\d{4})$")
I_FRAME = re.compile(r"^CY(\d{4})Q([1-4])I$")


def _units(facts: dict, concept: str) -> list[dict]:
    c = ((facts.get("facts") or {}).get("us-gaap") or {}).get(concept) or {}
    return (c.get("units") or {}).get("USD") or []


def _flow(facts: dict, concept: str) -> tuple[dict, dict]:
    """(quarters {"2025Q3": v}, years {"2024": v}) — Q4 filled in from the year when missing."""
    q, y = {}, {}
    for row in _units(facts, concept):
        fr = row.get("frame") or ""
        m = Q_FRAME.match(fr)
        if m:
            q[f"{m.group(1)}Q{m.group(2)}"] = float(row["val"])
            continue
        m = Y_FRAME.match(fr)
        if m:
            y[m.group(1)] = float(row["val"])
    for year, total in y.items():
        k = f"{year}Q4"
        parts = [q.get(f"{year}Q{i}") for i in (1, 2, 3)]
        if k not in q and all(p is not None for p in parts):
            q[k] = total - sum(parts)
    return q, y


def _pick_flow(facts: dict, concepts) -> tuple[dict, dict, str]:
    """The concept with the most recent quarter wins (companies switch tags over the years)."""
    best = ({}, {}, "")
    best_key = ""
    for c in concepts:
        q, y = _flow(facts, c)
        if not q and not y:
            continue
        latest = max(list(q) + [f"{k}Q0" for k in y])
        if latest > best_key:
            best, best_key = (q, y, c), latest
    return best


def _instant(facts: dict, concepts) -> tuple[float | None, str]:
    """Latest balance-sheet value and its date."""
    best_v, best_d = None, ""
    for c in concepts:
        for row in _units(facts, c):
            d = row.get("end") or ""
            if d > best_d and row.get("form", "").startswith(("10-Q", "10-K", "20-F", "40-F", "6-K")):
                best_v, best_d = float(row["val"]), d
    return best_v, best_d


def _instant_year_ago(facts: dict, concepts, ref_date: str) -> float | None:
    if not ref_date:
        return None
    target = f"{int(ref_date[:4]) - 1}{ref_date[4:]}"
    best, gap = None, 10**9
    for c in concepts:
        for row in _units(facts, c):
            d = row.get("end") or ""
            if not d:
                continue
            g = abs(_days(d) - _days(target))
            if g < gap and g <= 45:
                best, gap = float(row["val"]), g
    return best


def _days(d: str) -> int:
    y, m, dd = (int(x) for x in d.split("-"))
    return y * 372 + m * 31 + dd


def last_n(q: dict, n: int = 8) -> list[tuple[str, float]]:
    return [(k, q[k]) for k in sorted(q)[-n:]]


def summarize(facts: dict) -> dict:
    """Everything the scoring + statement page needs, in plain numbers (USD)."""
    rev_q, rev_y, rev_tag = _pick_flow(facts, REVENUE)
    ni_q, ni_y, _ = _pick_flow(facts, NET_INCOME)
    op_q, _, _ = _pick_flow(facts, OP_INCOME)
    gp_q, _, _ = _pick_flow(facts, GROSS)
    _, ocf_y, _ = _pick_flow(facts, OCF)
    _, capex_y, _ = _pick_flow(facts, CAPEX)

    quarters = [k for k, _ in last_n(rev_q, 8)] or [k for k, _ in last_n(ni_q, 8)]
    rows = []
    for k in quarters:
        r, n = rev_q.get(k), ni_q.get(k)
        rows.append({"q": k, "revenue": r, "net_income": n, "op_income": op_q.get(k), "gross": gp_q.get(k),
                     "net_margin": (n / r * 100) if (r and n is not None) else None})

    def yoy(series: dict, k: str):
        if not k:
            return None
        prev = f"{int(k[:4]) - 1}{k[4:]}"
        a, b = series.get(k), series.get(prev)
        if a is None or b is None or b == 0:
            return None
        return (a - b) / abs(b) * 100

    last_q = quarters[-1] if quarters else ""
    prev_y_q = f"{int(last_q[:4]) - 1}{last_q[4:]}" if last_q else ""
    margin_now = rows[-1]["net_margin"] if rows else None
    margin_then = (ni_q[prev_y_q] / rev_q[prev_y_q] * 100) if (prev_y_q in ni_q and rev_q.get(prev_y_q)) else None

    cash, cash_date = _instant(facts, CASH)
    inv, _ = _instant(facts, SHORT_INV)
    debt, _ = _instant(facts, DEBT)
    debt_cur, _ = _instant(facts, DEBT_CURRENT)
    liab, liab_date = _instant(facts, LIABILITIES)
    eq, _ = _instant(facts, EQUITY)

    years = sorted(set(ocf_y))[-3:]
    cashflow = [{"year": y, "ocf": ocf_y.get(y), "capex": capex_y.get(y),
                 "fcf": (ocf_y[y] - capex_y[y]) if (y in ocf_y and y in capex_y) else None} for y in years]

    ttm_rev = sum(rev_q[k] for k in quarters[-4:]) if len(quarters) >= 4 and all(k in rev_q for k in quarters[-4:]) else None
    ttm_ni = sum(ni_q[k] for k in quarters[-4:]) if len(quarters) >= 4 and all(k in ni_q for k in quarters[-4:]) else None

    return {
        "has_data": bool(rows),
        "revenue_tag": rev_tag,
        "quarters": rows,
        "last_quarter": last_q,
        "revenue_yoy": yoy(rev_q, last_q),
        "net_income_yoy": yoy(ni_q, last_q),
        "net_margin_now": margin_now,
        "net_margin_year_ago": margin_then,
        "ttm_revenue": ttm_rev,
        "ttm_net_income": ttm_ni,
        "annual_revenue": [{"year": y, "v": rev_y[y]} for y in sorted(rev_y)[-4:]],
        "annual_net_income": [{"year": y, "v": ni_y[y]} for y in sorted(ni_y)[-4:]],
        "cashflow": cashflow,
        "balance_date": cash_date or liab_date,
        "cash": cash,
        "short_investments": inv,
        "debt": (debt or 0) + (debt_cur or 0) if (debt is not None or debt_cur is not None) else None,
        "liabilities": liab,
        "liabilities_year_ago": _instant_year_ago(facts, LIABILITIES, liab_date),
        "equity": eq,
    }


def health(s: dict) -> str:
    """strong | ok | weak — worked out from numbers, not by the AI."""
    pts = 0
    cash = (s.get("cash") or 0) + (s.get("short_investments") or 0)
    debt = s.get("debt")
    if debt is not None:
        pts += 1 if cash >= debt else (-1 if debt > 3 * max(cash, 1) else 0)
    eq, liab = s.get("equity"), s.get("liabilities")
    if eq and liab is not None:
        r = liab / eq if eq > 0 else 99
        pts += 1 if r < 1 else (-1 if r > 3 else 0)
    elif eq is not None and eq <= 0:
        pts -= 1
    cf = [c["ocf"] for c in s.get("cashflow") or [] if c.get("ocf") is not None]
    if cf:
        pts += 1 if cf[-1] > 0 else -2
    ni = s.get("ttm_net_income")
    if ni is not None:
        pts += 1 if ni > 0 else -1
    return "strong" if pts >= 3 else ("weak" if pts <= 0 else "ok")

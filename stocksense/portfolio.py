"""The user's own holdings (portfolio.json) and past analyses (history.json)."""
from __future__ import annotations

import datetime as dt

from . import rules as RL
from .settings import read_json, write_json


class Portfolio:
    def __init__(self):
        data = read_json("portfolio.json", {})
        rows = data.get("holdings") if isinstance(data, dict) else None
        self.holdings: list[dict] = [h for h in (rows or []) if isinstance(h, dict) and h.get("ticker")]

    def save(self) -> None:
        write_json("portfolio.json", {"holdings": self.holdings})

    def get(self, ticker: str) -> dict | None:
        t = ticker.upper()
        return next((h for h in self.holdings if h["ticker"].upper() == t), None)

    def upsert(self, h: dict) -> None:
        """Rules ("rules") are kept from the old record unless the new one brings its own."""
        rules = h.get("rules")
        h = {"ticker": h["ticker"].upper().strip(), "name": h.get("name") or h["ticker"].upper(),
             "shares": float(h.get("shares") or 0), "avg_price": float(h.get("avg_price") or 0),
             "buy_date": h.get("buy_date") or dt.date.today().isoformat(), "reason": (h.get("reason") or "").strip()}
        for i, old in enumerate(self.holdings):
            if old["ticker"] == h["ticker"]:
                h["rules"] = RL.clean(rules if rules is not None else old.get("rules"))
                self.holdings[i] = h
                break
        else:
            h["rules"] = RL.clean(rules)
            self.holdings.append(h)
        self.save()

    def remove(self, ticker: str) -> None:
        self.holdings = [h for h in self.holdings if h["ticker"] != ticker.upper()]
        self.save()


class History:
    """Every finished analysis: kind, ticker, score, price, time. Newest first, capped."""
    LIMIT = 300

    def __init__(self):
        rows = read_json("history.json", [])
        self.rows: list[dict] = rows if isinstance(rows, list) else []

    def add(self, r: dict) -> None:
        if r.get("kind") not in ("buy", "sell"):
            return
        self.rows.insert(0, {"kind": r["kind"], "sym": r["sym"], "score": r["score"], "label": r["label"],
                             "price": r["price"], "at": r["at"]})
        del self.rows[self.LIMIT:]
        write_json("history.json", self.rows)

    def previous(self, sym: str, kind: str, skip_first: bool = True) -> dict | None:
        found = [r for r in self.rows if r["sym"] == sym and r["kind"] == kind]
        return (found[1] if len(found) > 1 else None) if skip_first else (found[0] if found else None)

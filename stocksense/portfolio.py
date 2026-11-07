"""The user's own holdings (portfolio.json) and past analyses (history.json)."""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid

from . import rules as RL
from .settings import config_dir, read_json, write_json


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
    """Every finished buy/sell analysis. Newest first. Each one also keeps its FULL result in a small file
    (history/<id>.json) so it can be opened again later without asking any website or AI."""
    LIMIT = 300        # rows kept in history.json
    FULL_LIMIT = 80    # full results kept on disk

    def __init__(self):
        rows = read_json("history.json", [])
        self.rows: list[dict] = rows if isinstance(rows, list) else []

    @staticmethod
    def _full_path(rid: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in rid)
        return os.path.join(config_dir(), "history", safe + ".json")

    def add(self, r: dict) -> str | None:
        if r.get("kind") not in ("buy", "sell"):
            return None
        rid = f"{r['sym']}-{r['kind']}-" + "".join(c for c in str(r.get("at", "")) if c.isdigit()) + "-" + uuid.uuid4().hex[:6]
        self.rows.insert(0, {"id": rid, "kind": r["kind"], "sym": r["sym"], "name": r.get("name") or r["sym"],
                             "score": r["score"], "label": r["label"], "tone": r.get("tone", "none"),
                             "price": r["price"], "at": r["at"]})
        try:
            write_json(os.path.join("history", os.path.basename(self._full_path(rid))), r)
        except (OSError, TypeError, ValueError):
            pass                                                           # the summary row is still saved
        self._prune()
        write_json("history.json", self.rows)
        return rid

    def _prune(self) -> None:
        for x in self.rows[self.FULL_LIMIT:]:
            try:
                os.remove(self._full_path(x["id"]))
            except (OSError, KeyError):
                pass
        del self.rows[self.LIMIT:]

    def full(self, rid: str | None) -> dict | None:
        if not rid:
            return None
        try:
            with open(self._full_path(rid), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else None
        except (OSError, ValueError):
            return None

    def entries(self, limit: int = 40) -> list[dict]:
        """Newest first, one row per (ticker, kind): the latest. `has_full` says whether it can be reopened."""
        seen, out = set(), []
        for x in self.rows:
            k = (x["sym"], x["kind"])
            if k in seen:
                continue
            seen.add(k)
            out.append({**x, "has_full": bool(x.get("id")) and os.path.exists(self._full_path(x["id"]))})
            if len(out) >= limit:
                break
        return out

    def previous(self, sym: str, kind: str, skip_first: bool = True) -> dict | None:
        found = [r for r in self.rows if r["sym"] == sym and r["kind"] == kind]
        return (found[1] if len(found) > 1 else None) if skip_first else (found[0] if found else None)

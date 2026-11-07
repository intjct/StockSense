"""The three buttons: วิเคราะห์ซื้อ / วิเคราะห์ขาย / วิเคราะห์งบล่าสุด.

Each returns a plain dict the UI draws. Numbers come from the data sources and
scoring rules; the AI only turns them into simple Thai."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

from . import fundamentals as F
from . import portfolio_check as PC
from . import rules as RL
from . import scoring as S
from .net import DAY, SourceError
from .sources import ETFS, Sources

RULES = """กติกาสำคัญ:
- ใช้เฉพาะข้อมูลที่ให้ไว้ด้านล่างเท่านั้น ห้ามใช้ความรู้ของตัวเองเพิ่ม ห้ามแต่งตัวเลขหรือข่าว
- เขียนภาษาไทยง่ายๆ ให้คนที่ไม่รู้เรื่องหุ้นเลยเข้าใจ ประโยคสั้น ไม่ใช้ศัพท์เทคนิค
  ถ้าจำเป็นต้องใช้คำเฉพาะ ให้อธิบายในวงเล็บสั้นๆ
- ตัวเลขเงินให้เขียนแบบอ่านง่าย เช่น "4.2 หมื่นล้านดอลลาร์" ไม่ใช่ 42000000000
- ถ้าข้อมูลขัดกัน ให้บอกตรงๆ ว่าขัดกัน ไม่ต้องปัดให้เป็นคำตอบเดียว
- ไม่สั่งให้ซื้อหรือขาย แค่อธิบายว่าข้อมูลบอกอะไร
- ตอบเป็น JSON ตามรูปแบบที่กำหนดเท่านั้น"""


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _money(v) -> str:
    if v is None:
        return "-"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e9:
        return f"{sign}${a / 1e9:,.1f} พันล้าน"
    if a >= 1e6:
        return f"{sign}${a / 1e6:,.1f} ล้าน"
    return f"{sign}${a:,.0f}"


def _brief(r: dict) -> dict:
    return {k: r.get(k) for k in ("sym", "name", "score", "label", "tone", "price", "at", "headline", "is_etf")}


def _strs(v) -> list[str]:
    return [str(x).strip() for x in v if str(x).strip()][:3] if isinstance(v, list) else []


class Analyzer:
    def __init__(self, src: Sources, progress=None):
        self.src = src
        self.progress = progress or (lambda text: None)

    # ------------------------------------------------------------ shared data
    def _soft(self, missing: list, label: str, fn, default):
        """Runs one optional source. A missing key stops everything; anything else is noted and skipped."""
        try:
            return fn()
        except SourceError as e:
            if e.kind == "key" and e.source in ("gemini", "finnhub"):
                raise
            missing.append(f"{label}: {e.th}")
            return default

    def gather(self, sym: str) -> dict:
        sym = sym.upper().strip()
        is_etf = sym in ETFS
        missing: list[str] = []
        self.progress("กำลังดึงราคาหุ้น…")
        hist = self.src.history(sym)
        if hist.get("currency") not in (None, "USD"):
            raise SourceError("notfound", f"{sym} ไม่ใช่หุ้นสหรัฐ (โปรแกรมนี้รองรับเฉพาะหุ้นสหรัฐ)", "yahoo")
        self.progress("กำลังดึงความเห็นนักวิเคราะห์และผลประกอบการ…")
        metrics = self._soft(missing, "ราคาเทียบกำไร", lambda: self.src.metrics(sym), {})
        earn = [] if is_etf else self._soft(missing, "ผลประกอบการ", lambda: self.src.earnings(sym), [])
        nxt = "" if is_etf else self._soft(missing, "วันประกาศงบ", lambda: self.src.next_earnings(sym), "")
        recs = [] if is_etf else self._soft(missing, "นักวิเคราะห์", lambda: self.src.recommendations(sym), [])
        target = {} if is_etf else self._soft(missing, "ราคาเป้าหมาย", lambda: self.src.price_target(sym), {})
        self.progress("กำลังอ่านข่าว 14 วันล่าสุด…")
        news = self._soft(missing, "ข่าว", lambda: self.src.news(sym), [])
        summ = None
        cik = None
        if not is_etf:
            self.progress("กำลังเปิดงบการเงินจาก SEC…")
            cik = self._soft(missing, "งบการเงิน", lambda: self.src.cik(sym), None)
            if cik:
                facts = self._soft(missing, "งบการเงิน", lambda: self.src.company_facts(cik), None)
                summ = F.summarize(facts) if facts else None
        name = (ETFS.get(sym) or hist.get("name") or sym)
        return {"sym": sym, "name": name, "is_etf": is_etf, "hist": hist, "metrics": metrics, "earnings": earn,
                "next_earnings": nxt, "recs": recs, "target": target, "news": news, "summary": summ,
                "cik": cik, "missing": missing}

    def classify_news(self, sym: str, news: list[dict]) -> list[dict]:
        return self.news_ai(sym, news)["news"]

    def news_ai(self, sym: str, news: list[dict]) -> dict:
        """One AI call: tag each news item good/bad/neutral AND pick out named analysts
        quoted in the news. Names are kept only if they appear word-for-word in the news text."""
        if not news:
            return {"news": [], "people": []}
        key = "news-ai2-" + sym + "-" + hashlib.sha1(json.dumps([n["headline"] for n in news]).encode()).hexdigest()[:10]
        cached = self.src.cache.get(key, 2 * DAY)
        if isinstance(cached, dict):
            return cached
        self.progress("AI กำลังแยกข่าวดีข่าวร้าย…")
        lines = "\n".join(f"[{i}] {n['date']} | {n['headline']} | {n['summary'][:300]}" for i, n in enumerate(news))
        prompt = f"""ข่าวของหุ้น {sym} ในช่วง 14 วัน แต่ละข่าวมีเลขกำกับ
{RULES}

งาน 1: บอกว่าแต่ละข่าว ดี (good) ร้าย (bad) หรือไม่ค่อยมีผล (neutral) ต่อราคาหุ้น {sym}
และสรุปแต่ละข่าวเป็นภาษาไทย 1 บรรทัด (ไม่เกิน 20 คำ) ข่าวที่ไม่เกี่ยวกับบริษัทนี้โดยตรงให้เป็น neutral

งาน 2: หา "นักวิเคราะห์ที่ถูกระบุชื่อบุคคลจริง" ในข่าว (เช่น analyst, strategist ของบริษัทหลักทรัพย์หรือธนาคาร)
- เอาเฉพาะชื่อคนที่เขียนอยู่ในหัวข่าวหรือเนื้อข่าวย่อ ก๊อปชื่อและชื่อบริษัทมาตรงตัวอักษร ห้ามเดา ห้ามแต่งชื่อเอง
- ไม่เอาผู้บริหารของ {sym} เอง ไม่เอาชื่อบริษัทหรือสถาบันที่ไม่มีชื่อคน
- ถ้าไม่มีชื่อคนเลย ให้ analysts เป็น []
- role_th = ตำแหน่งสั้นๆ เป็นภาษาไทยเท่าที่ข่าวบอก (ถ้าข่าวไม่บอกให้เขียนว่า นักวิเคราะห์)
- stance = good (มองบวก) / bad (ระวังหรือมองลบ) / neutral
- view_th = ความเห็นของเขาต่อ {sym} 1 บรรทัดภาษาไทย (ไม่เกิน 25 คำ) เอาเฉพาะที่ข่าวบอก

รูปแบบ JSON:
{{"news": [{{"i": 0, "effect": "good|bad|neutral", "line_th": "..."}}],
 "analysts": [{{"i": 0, "name": "...", "firm": "...", "role_th": "...", "stance": "good|bad|neutral", "view_th": "..."}}]}}

ข่าว:
{lines}"""
        d = self.src.ask_ai(prompt)
        out = []
        for row in d.get("news") or []:
            try:
                i = int(row.get("i"))
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(news):
                eff = row.get("effect") if row.get("effect") in ("good", "bad", "neutral") else "neutral"
                out.append({**news[i], "effect": eff, "line_th": str(row.get("line_th") or news[i]["headline"])})
        people = self._verify_people(d.get("analysts"), news)
        res = {"news": out, "people": people}
        self.src.cache.put(key, res)
        return res

    @staticmethod
    def _verify_people(rows, news: list[dict]) -> list[dict]:
        """Keep an analyst only if the name really appears in that news item (guards against AI inventing people)."""
        people, seen = [], set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                i = int(row.get("i"))
            except (TypeError, ValueError):
                continue
            name = str(row.get("name") or "").strip()
            if not (0 <= i < len(news)) or len(name.split()) < 2 or len(name) < 5:
                continue
            text = (news[i]["headline"] + " " + news[i].get("summary", "")).lower()
            if name.lower() not in text or name.lower() in seen:
                continue
            seen.add(name.lower())
            firm = str(row.get("firm") or "").strip()
            if firm and firm.lower() not in text:
                firm = ""
            stance = row.get("stance") if row.get("stance") in ("good", "bad", "neutral") else "neutral"
            view = str(row.get("view_th") or "").strip()
            if not view:
                continue
            n = news[i]
            people.append({"name": name, "firm": firm, "role": str(row.get("role_th") or "นักวิเคราะห์").strip(),
                           "stance": stance, "view": view, "date": n["date"], "url": n.get("url", ""),
                           "source": n.get("source", "")})
            if len(people) >= 3:
                break
        return people

    # ------------------------------------------------------------ compare
    TIE_GAP = 5

    def compare(self, a: dict, b: dict, ai: bool = True) -> dict:
        """Side-by-side of two finished BUY analyses taken from history. Nothing is downloaded; only the
        written explanation comes from one AI call (cached per pair). The leader is decided by the scores, not by AI."""
        gap = a["score"] - b["score"]
        leader = "tie" if abs(gap) < self.TIE_GAP else ("a" if gap > 0 else "b")
        cb = {c["key"]: c for c in b.get("cards", [])}
        rows = []
        for c in a.get("cards", []):
            o = cb.get(c["key"])
            rows.append({"key": c["key"], "title": c["title"], "a": c["score"], "b": o["score"] if o else None,
                         "a_short": c.get("short", ""), "b_short": (o or {}).get("short", "")})
        out = {"kind": "compare", "a": _brief(a), "b": _brief(b), "gap": gap, "leader": leader, "rows": rows,
               "ai": {}, "ai_ok": False, "ai_error": ""}
        if not ai:
            out["ai_error"] = "ต้องใส่คีย์ Gemini ในหน้าตั้งค่าก่อน ถึงจะให้ AI สรุปให้ได้"
            return out
        key = "cmp-" + hashlib.sha1(f"{a['sym']}|{a['at']}|{b['sym']}|{b['at']}".encode()).hexdigest()[:16]
        cached = self.src.cache.get(key, 30 * DAY)
        if isinstance(cached, dict) and cached.get("summary_th"):
            out["ai"], out["ai_ok"] = cached, True
            return out
        self.progress("AI กำลังเทียบให้ 2 ตัว…")
        try:
            d = self.src.ask_ai(self._compare_prompt(a, b, leader))
        except SourceError as e:
            out["ai_error"] = e.th
            return out
        res = {"summary_th": str(d.get("summary_th") or "").strip(),
               "a_good_th": _strs(d.get("a_good_th")), "b_good_th": _strs(d.get("b_good_th")),
               "caution_th": str(d.get("caution_th") or "").strip()}
        if not res["summary_th"]:
            out["ai_error"] = "AI ตอบกลับมาไม่ครบ ลองกดเปรียบเทียบอีกครั้ง"
            return out
        self.src.cache.put(key, res)
        out["ai"], out["ai_ok"] = res, True
        return out

    @staticmethod
    def _compare_prompt(a: dict, b: dict, leader: str) -> str:
        def block(tag, r):
            lines = [f"{tag} = {r['sym']} ({r['name']}) คะแนนน่าซื้อ {r['score']}% ({r['label']}) ราคา ${r['price']} วิเคราะห์เมื่อ {r['at']}",
                     f"  สรุปเดิม: {r.get('headline', '')}"]
            for c in r.get("cards", []):
                lines.append(f"  - {c['title']}: {c['score']}/100 · {c.get('short', '')}")
            box = (r.get("analyst_box") or {}).get("summary")
            if box:
                lines.append(f"  - นักวิเคราะห์รวม: ส่วนใหญ่แนะนำ {box['word']} (ซื้อ {box['buy']} ถือ {box['hold']} ขาย {box['sell']})")
            return "\n".join(lines)
        who = {"a": f"A ({a['sym']}) ได้คะแนนสูงกว่า", "b": f"B ({b['sym']}) ได้คะแนนสูงกว่า",
               "tie": "คะแนนสูสีกัน (ต่างกันไม่ถึง 5 คะแนน)"}[leader]
        return f"""เปรียบเทียบหุ้น 2 ตัวจากผลวิเคราะห์ที่ทำไว้แล้ว เพื่อบอกว่าตัวไหนน่าสนใจกว่าในแง่ "น่าซื้อ"
{RULES}
- ผลตัดสินจากคะแนนถูกกำหนดแล้ว: {who} ห้ามเปลี่ยนผล ให้อธิบายเหตุผลตามตัวเลขที่ให้เท่านั้น
- ถ้าวิเคราะห์ไว้คนละวัน ราคาอาจเปลี่ยนไปแล้ว ให้เตือนสั้นๆ

{block('A', a)}

{block('B', b)}

ตอบเป็น JSON:
{{"summary_th": "สรุป 2-3 ประโยคว่าตัวไหนน่าสนใจกว่าหรือสูสี เพราะอะไร",
 "a_good_th": ["จุดเด่นของ A สั้นๆ ไม่เกิน 3 ข้อ"],
 "b_good_th": ["จุดเด่นของ B สั้นๆ ไม่เกิน 3 ข้อ"],
 "caution_th": "ข้อควรระวังเวลาเทียบ 2 ตัวนี้ 1 ประโยค (เช่น คะแนนสูงกว่าไม่ได้แปลว่ากำไรมากกว่า)"}}"""

    # ------------------------------------------------------------ buy / sell
    def run(self, sym: str, mode: str = "buy", holding: dict | None = None, fx: float | None = None,
            explain: bool = True, holdings: list | None = None) -> dict:
        """holdings: the whole portfolio, so a buy result can say how the mix would change
        and a sell result can check the person's เงื่อนไขเปลี่ยนใจ (weight rule)."""
        g = self.gather(sym)
        news, people = [], []
        try:
            ai = self.news_ai(g["sym"], g["news"])
            news, people = ai["news"], ai["people"]
        except SourceError as e:
            if e.kind == "key":
                raise
            g["missing"].append(f"ข่าว: {e.th}")
        price = g["hist"]["price"]
        parts = {
            "financials": S.financials(g["summary"]),
            "valuation": S.valuation(g["metrics"], g["is_etf"]),
            "earnings": S.earnings(g["earnings"], g["next_earnings"]),
            "analysts": S.analysts(g["recs"], g["target"], price),
            "news": S.news(news),
            "chart": S.chart(g["hist"]),
        }
        score = S.combine(parts, mode)
        if score is None:
            raise SourceError("other", "ข้อมูลไม่พอให้วิเคราะห์ ลองใหม่อีกครั้งภายหลัง", "")
        if mode == "sell" and g["is_etf"]:
            score = min(score, 55)
        label, tone = (S.buy_label if mode == "buy" else S.sell_label)(score)

        pos = self._position(holding, price, fx) if holding else None
        flags = self._danger_flags(parts, news) if mode == "sell" else []
        texts = self._explain(g, parts, news, score, label, mode, pos, flags) if explain else {}

        cards = []
        for k in S.PARTS:
            p = parts[k]
            t = texts.get("parts", {}).get(k) or {}
            cards.append({"key": k, "title": S.TITLES[k], "help": S.HELP[k], "score": p["score"],
                          "tone": S.part_tone(p["score"]),
                          "short": t.get("short") or self._fallback_short(k, p),
                          "detail": t.get("detail") or "",
                          "facts": p["facts"]})
        result = {
            "kind": mode, "sym": g["sym"], "name": g["name"], "is_etf": g["is_etf"], "price": price,
            "day_change_pct": S.pct(price, g["hist"]["prev_close"]), "score": score, "label": label, "tone": tone,
            "headline": texts.get("headline") or self._fallback_headline(parts, mode),
            "conflict": texts.get("conflict") or "", "watch": texts.get("watch") or "",
            "reason_check": texts.get("reason_check") or "", "ai_ok": texts.get("ok", False),
            "cards": cards, "news": news, "position": pos, "flags": flags,
            "next_earnings": g["next_earnings"], "missing": g["missing"], "at": _now(),
            "chart_closes": g["hist"]["closes"][-180:], "support": parts["chart"]["facts"].get("support"),
            "resistance": parts["chart"]["facts"].get("resistance"),
        }
        if not g["is_etf"]:
            result["analyst_box"] = S.analyst_box(parts["analysts"]["facts"], people)
        if mode == "buy" and holdings:
            result["fit"] = self.buy_fit(g["sym"], g["is_etf"], holdings)
        if mode == "sell" and holding:
            weight = None
            if holdings:
                weight = self._weight(g["sym"], *self._items_bets(holdings))
            ctx = {"price": price, "avg_price": holding.get("avg_price"), "weight_pct": weight,
                   "surprise_pct": parts["earnings"]["facts"].get("last_surprise_pct")}
            result["rule_ctx"] = ctx
            result["rules"] = RL.evaluate_all(holding.get("rules"), ctx)
            result["suggested_rules"] = [] if result["rules"] else RL.default_rules(
                price, parts["chart"]["facts"].get("support"), not g["is_etf"])
        if g["is_etf"]:
            result["etf_note"] = ("นี่คือกองทุนรวมหุ้นหลายร้อยตัว ไม่มีงบการเงินของตัวเอง "
                                  + ("คนส่วนใหญ่ซื้อสะสมเรื่อยๆ ระยะยาว การรอจังหวะซื้อมักได้ผลไม่ต่างกันมาก"
                                     if mode == "buy" else
                                     "การขายเพราะตลาดลงชั่วคราวเป็นความผิดพลาดที่พบบ่อยที่สุด ถ้ายังถือยาวได้ มักไม่จำเป็นต้องขาย"))
        return result



    # ------------------------------------------------------------ เงื่อนไขเปลี่ยนใจ
    def _items_bets(self, holdings: list[dict]):
        items = self._values(holdings)
        return items, PC.bets(PC.exposures(items))

    @staticmethod
    def _weight(sym: str, items: list[dict], bets: list[dict]) -> float | None:
        """Share of the portfolio (counting what sits inside index funds); None if the price is unknown."""
        total = sum(i["value"] for i in items)
        if not total or not any(i["ticker"] == sym for i in items):
            return None
        b = next((x for x in bets if x["name"] == PC.norm(sym)), None)
        if b:
            return b["pct"]
        return sum(i["value"] for i in items if i["ticker"] == sym) / total * 100

    def _surprise(self, sym: str) -> float | None:
        try:
            return S.earnings(self.src.earnings(sym), "")["facts"].get("last_surprise_pct")
        except SourceError:
            return None

    def check_rules(self, holdings: list[dict]) -> dict:
        """{ticker: [evaluated rules]} for every holding that has at least one rule switched on.
        Runs quietly at start-up: no AI, and a failed source simply makes that rule "unknown"."""
        todo = [h for h in holdings if any(r["on"] for r in RL.clean(h.get("rules")))]
        if not todo:
            return {}
        items, bets = self._items_bets(holdings)
        prices = {i["ticker"]: i["price"] for i in items}
        out = {}
        for h in todo:
            sym, rules = h["ticker"], RL.clean(h.get("rules"))
            ctx = {"price": prices.get(sym), "avg_price": h.get("avg_price"), "weight_pct": self._weight(sym, items, bets)}
            if sym not in ETFS and any(r["kind"] == "earnings_miss" and r["on"] for r in rules):
                ctx["surprise_pct"] = self._surprise(sym)
            out[sym] = RL.evaluate_all(rules, ctx)
        return out

    # ------------------------------------------------------------ portfolio
    FIT_AMOUNT = 500.0

    def _values(self, holdings: list[dict], missing: list | None = None) -> list[dict]:
        """[{ticker, value, is_etf}] using the latest prices (cached 20 min). Prices that fail are skipped."""
        items = []
        for h in holdings:
            try:
                price = self.src.price(h["ticker"])
            except SourceError as e:
                if missing is not None:
                    missing.append(f"ราคา {h['ticker']}: {e.th}")
                continue
            items.append({"ticker": h["ticker"], "value": price * float(h.get("shares") or 0),
                          "is_etf": h["ticker"] in ETFS, "price": price})
        return items

    def buy_fit(self, sym: str, is_etf: bool, holdings: list[dict]) -> dict | None:
        """The "what if I buy $500 more" note on the buy result. Never blocks the main answer."""
        try:
            items = self._values(holdings)
        except SourceError as e:
            if e.kind == "key":
                raise
            return None
        return PC.buy_fit(items, sym, is_etf, self.FIT_AMOUNT)

    def check_portfolio(self, holdings: list[dict], fx: float | None) -> dict:
        if not holdings:
            raise SourceError("other", "ยังไม่มีหุ้นในพอร์ต กด “+ เพิ่มหุ้น” ทางซ้ายก่อน", "")
        missing: list[str] = []
        rows: list[dict] = []
        n = len(holdings)
        for i, h in enumerate(holdings, 1):
            sym = h["ticker"]
            self.progress(f"กำลังตรวจ {sym} ({i} จาก {n})…")
            row = {"ticker": sym, "name": h.get("name") or sym, "shares": float(h.get("shares") or 0),
                   "avg_price": float(h.get("avg_price") or 0), "is_etf": sym in ETFS, "score": None}
            try:
                r = self.run(sym, "sell", h, fx, explain=False)
                row.update(price=r["price"], score=r["score"], label=r["label"], tone=r["tone"],
                           headline=r["headline"], flags=r["flags"], next_earnings=r.get("next_earnings") or "",
                           name=r["name"], is_etf=r["is_etf"])
                missing += [f"{sym}: {m}" for m in r["missing"]]
            except SourceError as e:
                if e.kind == "key":
                    raise
                missing.append(f"{sym}: {e.th}")
                try:
                    row["price"] = self.src.price(sym)
                except SourceError:
                    row["price"] = None
            if row.get("price") is not None:
                row["value"] = row["price"] * row["shares"]
                row["paid"] = row["avg_price"] * row["shares"]
                row["pl_pct"] = S.pct(row["value"], row["paid"]) if row["paid"] else None
                row["fx_buy"] = self._soft(missing, "ค่าเงินวันที่ซื้อ", lambda d=h.get("buy_date"): self.src.usd_thb_on(d), None) \
                    if h.get("buy_date") else None
            rows.append(row)
        priced = [r for r in rows if r.get("value") is not None]
        if not priced:
            raise SourceError("other", "ดึงราคาหุ้นในพอร์ตไม่ได้เลย ลองใหม่อีกครั้งภายหลัง", "")

        total = sum(r["value"] for r in priced)
        paid = sum(r["paid"] for r in priced)
        for r in priced:
            r["weight"] = r["value"] / total * 100
        scored = [r for r in priced if r["score"] is not None]
        sw = sum(r["value"] for r in scored)
        hold_score = sum((100 - r["score"]) * r["value"] for r in scored) / sw if sw else None

        ex = PC.exposures([{"ticker": r["ticker"], "value": r["value"], "is_etf": r["is_etf"]} for r in priced])
        all_bets = PC.bets(ex)
        top = all_bets[0] if all_bets else None
        top_pct = top["pct"] if top else 0.0
        conc = PC.concentration_score(top_pct)
        hs, hlabel, htone = PC.health(hold_score, conc)

        today = dt.date.today()
        soon = []
        for r in priced:
            d = r.get("next_earnings")
            if not d or r["is_etf"]:
                continue
            try:
                days = (dt.date.fromisoformat(d) - today).days
            except ValueError:
                continue
            if 0 <= days <= 30:
                soon.append({"ticker": r["ticker"], "date": d, "days": days, "weight": r["weight"]})
        soon.sort(key=lambda x: x["days"])

        ranking = sorted(priced, key=lambda r: (-(r["score"] if r["score"] is not None else -1), -r["weight"]))
        res = {
            "kind": "portfolio", "at": _now(), "total": total, "paid": paid, "pl": total - paid,
            "pl_pct": S.pct(total, paid) if paid else None, "fx": fx, "total_thb": total * fx if fx else None,
            "health": hs, "health_label": hlabel, "health_tone": htone,
            "hold_score": None if hold_score is None else int(round(hold_score)), "conc_score": conc,
            "top": top, "stress": PC.stress_loss(top_pct) if top else 0.0, "stress_drop": PC.STRESS_DROP,
            "bets": all_bets[:6], "overlaps": PC.overlaps(all_bets), "ranking": ranking, "currency": PC.currency_split(priced, fx),
            "earnings": soon, "missing": missing, "count": len(priced), "unpriced": n - len(priced),
        }
        res.update(self._portfolio_text(res))
        return res

    def _portfolio_text(self, r: dict) -> dict:
        top = r["top"]
        fallback_head = f"คะแนนสุขภาพพอร์ต {r['health']}% ({r['health_label']})"
        if top and top["pct"] >= PC.WARN:
            fallback_head += f" · {top['name']} มีน้ำหนักสูง {top['pct']:.0f}% ของพอร์ต"
        watch = []
        if top and top["pct"] >= PC.CALM + 5:
            watch.append(f"{top['name']} คิดเป็น {top['pct']:.0f}% ของพอร์ต ถ้าตกไป {r['stress_drop']:.0f}% พอร์ตจะลดประมาณ {r['stress']:.0f}%")
        for o in r["overlaps"][:2]:
            watch.append(f"คุณถือ {o['name']} ตรงๆ และมีอยู่ในกองทุน {', '.join(o['etfs'])} ด้วย รวมแล้วเป็น {o['pct']:.0f}% ของพอร์ต")
        for x in r["ranking"][:2]:
            if x["score"] is not None and x["score"] >= 45:
                watch.append(f"{x['ticker']}: {x['label']} ({x['score']}%)")
        for e in r["earnings"][:2]:
            watch.append(f"{e['ticker']} ประกาศงบอีก {e['days']} วัน ({e['date']})")
        out = {"headline": fallback_head, "watch": watch[:4], "ai_ok": False}
        facts = {"คะแนนสุขภาพ": r["health"], "สุขภาพหุ้นที่ถือ": r["hold_score"], "คะแนนการกระจาย": r["conc_score"],
                 "ตัวที่หนักสุด": top and {"ชื่อ": top["name"], "เปอร์เซ็นต์ของพอร์ต": round(top["pct"], 1)},
                 "ถ้าตัวหนักสุดตก 30% พอร์ตลดประมาณ": round(r["stress"], 1),
                 "หุ้นเรียงจากน่ากังวลสุด": [{"หุ้น": x["ticker"], "น้ำหนัก": round(x["weight"], 1), "ป้ายขาย": x.get("label"),
                                             "คะแนนขาย": x["score"], "ข้อสังเกต": x.get("headline")} for x in r["ranking"][:6]],
                 "ประกาศงบใน 30 วัน": [f"{e['ticker']} {e['date']}" for e in r["earnings"]],
                 "ถือซ้ำกับกองทุน": [f"{o['name']} รวม {o['pct']:.0f}%" for o in r["overlaps"]]}
        prompt = f"""นี่คือผลตรวจพอร์ตหุ้นสหรัฐของผู้ใช้ โปรแกรมคิดคะแนนไว้แล้ว ห้ามเปลี่ยนตัวเลข
{RULES}
- ห้ามสั่งให้ซื้อหรือขายหุ้นตัวใด ให้บอกแค่จุดที่ควรจับตา

ข้อมูล:
{json.dumps(facts, ensure_ascii=False, default=str)}

รูปแบบ JSON:
{{"headline": "ประโยคเดียว สรุปภาพรวมพอร์ตว่าแข็งแรงหรือเสี่ยงตรงไหน",
 "watch": ["สิ่งที่ควรจับตา 1 ประโยคต่อข้อ ไม่เกิน 4 ข้อ"]}}"""
        self.progress("AI กำลังสรุปภาพรวมพอร์ต…")
        try:
            d = self.src.ask_ai(prompt)
        except SourceError as e:
            if e.kind == "key":
                raise
            r["missing"].append(f"คำอธิบายจาก AI: {e.th}")
            return out
        head = str(d.get("headline") or "").strip()
        raw = d.get("watch") or []
        w = [str(x).strip() for x in ([raw] if isinstance(raw, str) else raw) if str(x).strip()]
        if head:
            out["headline"] = head
        if w:
            out["watch"] = w[:4]
        out["ai_ok"] = bool(head)
        return out

    @staticmethod
    def _position(h: dict, price: float, fx: float | None) -> dict:
        shares, cost = float(h.get("shares") or 0), float(h.get("avg_price") or 0)
        value, paid = shares * price, shares * cost
        pl = value - paid
        return {"shares": shares, "avg_price": cost, "value": value, "paid": paid, "pl": pl,
                "pl_pct": S.pct(value, paid) if paid else None, "fx": fx,
                "value_thb": value * fx if fx else None, "pl_thb": pl * fx if fx else None,
                "buy_date": h.get("buy_date") or "", "reason": (h.get("reason") or "").strip()}

    @staticmethod
    def _danger_flags(parts: dict, news: list[dict]) -> list[str]:
        f, out = parts["chart"]["facts"], []
        if f.get("broke_support"):
            out.append("ราคาเพิ่งหลุดจุดที่เคยเด้งขึ้น (หลุดแนวรับ)")
        if f.get("avg_200_days") and f["price"] < f["avg_200_days"]:
            out.append("ราคาต่ำกว่าราคาเฉลี่ย 200 วัน แปลว่าภาพใหญ่กำลังเป็นขาลง")
        e = parts["earnings"]["facts"]
        if e.get("last_surprise_pct") is not None and e["last_surprise_pct"] < -2:
            out.append("กำไรไตรมาสล่าสุดออกมาแย่กว่าที่คาด")
        a = parts["analysts"]["facts"]
        if a.get("upside_to_target_pct") is not None and a["upside_to_target_pct"] < 0:
            out.append("ราคาตอนนี้สูงกว่าราคาเป้าหมายเฉลี่ยของนักวิเคราะห์แล้ว")
        bad = [n for n in news if n.get("effect") == "bad"]
        if len(bad) >= 3 and len(bad) > len([n for n in news if n.get("effect") == "good"]):
            out.append("ข่าวร้ายมากกว่าข่าวดีในช่วงนี้")
        fin = parts["financials"]["facts"]
        if fin.get("profit_last_quarter_usd") is not None and fin["profit_last_quarter_usd"] < 0:
            out.append("ไตรมาสล่าสุดบริษัทขาดทุน")
        return out

    def _explain(self, g, parts, news, score, label, mode, pos, flags) -> dict:
        data = {k: {"score_0_100": parts[k]["score"], **parts[k]["facts"]} for k in S.PARTS}
        news_lines = [f"- ({n['effect']}) {n['line_th']}" for n in news[:8]]
        extra = ""
        if mode == "sell" and pos:
            extra = f"""
ข้อมูลการถือของผู้ใช้: ถือ {pos['shares']:g} หุ้น ต้นทุนเฉลี่ย ${pos['avg_price']:.2f} ซื้อเมื่อ {pos['buy_date'] or 'ไม่ระบุ'}
กำไร/ขาดทุนตอนนี้ {(pos['pl_pct'] or 0):.1f}%
เหตุผลที่ผู้ใช้จดไว้ตอนซื้อ: "{pos['reason'] or 'ไม่ได้จดไว้'}"
สัญญาณอันตรายที่โปรแกรมเจอ: {', '.join(flags) or 'ไม่มี'}"""
        q = "น่าซื้อ" if mode == "buy" else "น่าขาย"
        prompt = f"""หุ้น {g['sym']} ({g['name']}) ราคา ${g['hist']['price']:.2f}
{'นี่คือกองทุนดัชนี (ETF) ไม่ใช่บริษัทเดี่ยว' if g['is_etf'] else ''}
โปรแกรมคิดคะแนนความ{q}ไว้แล้ว = {score}% ({label}) จากข้อมูล 6 เรื่อง แต่ละเรื่องมีคะแนน 0-100
(คะแนนแต่ละเรื่อง = ยิ่งสูง ยิ่งดีต่อหุ้น / null = ไม่มีข้อมูล)
{RULES}
- ห้ามเปลี่ยนคะแนน ให้อธิบายว่าทำไมได้คะแนนนี้

ข้อมูล:
{json.dumps(data, ensure_ascii=False, default=str)}
ข่าวที่แยกแล้ว:
{chr(10).join(news_lines) or 'ไม่มีข่าว'}{extra}

รูปแบบ JSON:
{{
 "headline": "ประโยคเดียว สรุปภาพรวมว่าทำไมได้ {score}%",
 "parts": {{
   "financials": {{"short": "ไม่เกิน 8 คำ", "detail": "2-3 ประโยค อธิบายตัวเลขสำคัญ"}},
   "valuation": {{...}}, "earnings": {{...}}, "analysts": {{...}}, "news": {{...}}, "chart": {{...}}
 }},
 "conflict": "ถ้าข้อมูลขัดกัน บอก 1 ประโยค ไม่งั้นเป็น \\"\\"",
 "watch": "สิ่งที่ควรจับตาต่อจากนี้ 1 ประโยค"{''',
 "reason_check": "เหตุผลที่ผู้ใช้จดไว้ตอนซื้อ ตอนนี้ยังจริงอยู่ไหม 1-2 ประโยค (ถ้าไม่ได้จด ให้เป็น \\"\\")"''' if mode == 'sell' else ''}
}}
เรื่องที่ไม่มีข้อมูล ให้ short เป็น "ไม่มีข้อมูล" และ detail อธิบายสั้นๆ ว่าทำไม"""
        self.progress("AI กำลังสรุปให้เป็นภาษาคน…")
        try:
            d = self.src.ask_ai(prompt)
        except SourceError as e:
            if e.kind == "key":
                raise
            g["missing"].append(f"คำอธิบายจาก AI: {e.th}")
            return {}
        out_parts = {}
        for k in S.PARTS:
            v = (d.get("parts") or {}).get(k) or {}
            if isinstance(v, dict):
                out_parts[k] = {"short": str(v.get("short") or "").strip(), "detail": str(v.get("detail") or "").strip()}
        return {"ok": True, "headline": str(d.get("headline") or "").strip(), "parts": out_parts,
                "conflict": str(d.get("conflict") or "").strip(), "watch": str(d.get("watch") or "").strip(),
                "reason_check": str(d.get("reason_check") or "").strip()}

    @staticmethod
    def _fallback_short(k: str, p: dict) -> str:
        f = p["facts"]
        if p["score"] is None:
            return "ไม่มีข้อมูล"
        if k == "financials":
            g = f.get("sales_growth_vs_last_year_pct")
            return f"ยอดขาย{'โต' if (g or 0) >= 0 else 'ลด'} {abs(g or 0):.0f}% จากปีก่อน" if g is not None else "ดูรายละเอียด"
        if k == "valuation":
            v = f.get("vs_usual_pct")
            if v is not None:
                return f"{'แพง' if v > 0 else 'ถูก'}กว่าปกติ {abs(v)}%"
            return f"P/E {f.get('pe_now')}"
        if k == "earnings":
            return f"ดีกว่าที่คาด {f.get('beats_last_4', 0)} ใน {f.get('quarters_counted', 4)} ไตรมาส"
        if k == "analysts":
            return f"ให้ซื้อ {f.get('say_buy', 0)} จาก {f.get('analysts', 0)} คน"
        if k == "news":
            return f"ดี {f.get('good', 0)} · ร้าย {f.get('bad', 0)}"
        if k == "chart":
            a = f.get("avg_200_days")
            return ("อยู่ในขาขึ้น" if f["price"] > a else "อยู่ในขาลง") if a else "ดูรายละเอียด"
        return ""

    @staticmethod
    def _fallback_headline(parts: dict, mode: str) -> str:
        good = [S.TITLES[k] for k in S.PARTS if S.part_tone(parts[k]["score"]) == "good"]
        bad = [S.TITLES[k] for k in S.PARTS if S.part_tone(parts[k]["score"]) == "bad"]
        bits = []
        if good:
            bits.append("จุดดี: " + ", ".join(good))
        if bad:
            bits.append("จุดที่ต้องระวัง: " + ", ".join(bad))
        return " · ".join(bits) or "ข้อมูลส่วนใหญ่อยู่ในระดับกลางๆ"

    # ------------------------------------------------------------ latest statements
    def statements(self, sym: str) -> dict:
        sym = sym.upper().strip()
        if sym in ETFS:
            raise SourceError("notfound", f"{sym} เป็นกองทุนดัชนี ไม่มีงบการเงินของตัวเอง ใช้ปุ่มวิเคราะห์ซื้อหรือขายแทนได้", "")
        self.progress("กำลังหาเลขทะเบียนบริษัทที่ SEC…")
        cik = self.src.cik(sym)
        if not cik:
            raise SourceError("notfound", f"ไม่เจอ {sym} ในทะเบียน SEC (อาจเป็นบริษัทต่างชาติที่ไม่ได้ส่งงบแบบนี้)", "sec")
        self.progress("กำลังดึงตัวเลขงบการเงินย้อนหลัง…")
        summ = F.summarize(self.src.company_facts(cik))
        if not summ["has_data"]:
            raise SourceError("notfound", f"SEC ไม่มีตัวเลขงบรายไตรมาสของ {sym}", "sec")
        self.progress("กำลังหาเอกสารงบล่าสุด…")
        subs = self.src.submissions(cik)
        r = subs["recent"]
        periodic = mdna = press = None
        for i, form in enumerate(r["form"]):
            if periodic is None and form in ("10-Q", "10-K"):
                periodic = {"form": form, "acc": r["accessionNumber"][i], "doc": r["primaryDocument"][i],
                            "date": r["filingDate"][i], "period": r["reportDate"][i]}
            if press is None and form == "8-K" and "2.02" in (r["items"][i] or ""):
                press = {"form": "8-K", "acc": r["accessionNumber"][i], "date": r["filingDate"][i], "doc": ""}
            if periodic and press:
                break
        missing: list[str] = []
        if periodic:
            self.progress(f"กำลังอ่านรายงาน {periodic['form']} ที่ส่ง SEC…")
            try:
                mdna = find_mdna(self.src.filing_text(cik, periodic["acc"], periodic["doc"]))
            except SourceError as e:
                missing.append(f"รายงาน {periodic['form']}: {e.th}")
        if press:
            try:
                files = self.src.filing_files(cik, press["acc"])
                ex = pick_ex99(files)
                if ex:
                    press["doc"] = ex
                    self.progress("กำลังอ่านข่าวประกาศผลประกอบการของบริษัท…")
                    press["text"] = self.src.filing_text(cik, press["acc"], ex)[:32000]
            except SourceError as e:
                missing.append(f"ข่าวประกาศผลประกอบการ: {e.th}")
        level = F.health(summ)
        key = f"stmt-ai-{sym}-{(periodic or {}).get('acc', '')}-{(press or {}).get('acc', '')}"
        ai = self.src.cache.get(key, 90 * DAY)
        if ai is None:
            ai = self._statement_ai(sym, subs.get("name") or sym, summ, level, periodic, mdna, press)
            if ai.get("ok"):
                self.src.cache.put(key, ai)
            else:
                missing.append(ai.get("error") or "คำอธิบายจาก AI ใช้ไม่ได้ตอนนี้")
        links = []
        if press and press.get("doc"):
            links.append({"title": f"ข่าวประกาศผลประกอบการ ({press['date']})",
                          "url": self.src.filing_url(cik, press["acc"], press["doc"])})
        if periodic:
            links.append({"title": f"รายงาน {periodic['form']} ฉบับเต็ม ({periodic['date']})",
                          "url": self.src.filing_url(cik, periodic["acc"], periodic["doc"])})
        return {"kind": "statement", "sym": sym, "name": subs.get("name") or sym, "summary": summ,
                "health": level, "ai": ai if ai.get("ok") else {}, "links": links, "missing": missing,
                "period": (periodic or {}).get("period") or summ["last_quarter"], "at": _now()}

    def _statement_ai(self, sym, name, summ, level, periodic, mdna, press) -> dict:
        rows = [{"quarter": q["q"], "sales": _money(q["revenue"]), "net_profit": _money(q["net_income"]),
                 "profit_margin_pct": round(q["net_margin"], 1) if q["net_margin"] is not None else None}
                for q in summ["quarters"]]
        nums = {"quarters_oldest_to_newest": rows,
                "sales_growth_vs_same_quarter_last_year_pct": summ["revenue_yoy"],
                "profit_growth_vs_same_quarter_last_year_pct": summ["net_income_yoy"],
                "cash_and_short_investments": _money((summ["cash"] or 0) + (summ["short_investments"] or 0)),
                "debt": _money(summ["debt"]), "total_liabilities": _money(summ["liabilities"]),
                "shareholder_equity": _money(summ["equity"]),
                "yearly_operating_cash": [{"year": c["year"], "operating_cash": _money(c["ocf"]),
                                           "free_cash": _money(c["fcf"])} for c in summ["cashflow"]],
                "financial_health_from_rules": {"strong": "แข็งแรง", "ok": "พอใช้", "weak": "น่าห่วง"}[level]}
        docs = ""
        if press and press.get("text"):
            docs += f"\n\n=== ข่าวประกาศผลประกอบการของบริษัท (ยื่น SEC {press['date']}) ===\n{press['text']}"
        if mdna:
            docs += f"\n\n=== ส่วนที่ผู้บริหารอธิบายผลงานและแผน จากรายงาน {periodic['form']} ({periodic['date']}) ===\n{mdna}"
        prompt = f"""บริษัท {name} (หุ้น {sym}) — วิเคราะห์งบการเงินล่าสุด
{RULES}
- "ทิศทางบริษัท" และ "คาดการณ์" ให้ยึดตามสิ่งที่บริษัทเขียนเองในเอกสาร และบอกว่าเป็นสิ่งที่ผู้บริหารบอก
- ถ้าเอกสารไม่ได้พูดถึงเรื่องไหน ให้เว้นว่างหรือบอกว่า "เอกสารไม่ได้ระบุ" ห้ามเดา

ตัวเลขงบ (ดอลลาร์สหรัฐ):
{json.dumps(nums, ensure_ascii=False, default=str)}
{docs or '(ไม่มีเอกสารข้อความ ใช้ตัวเลขอย่างเดียว)'}

รูปแบบ JSON:
{{
 "overview": "ภาพรวมไตรมาสล่าสุด 2-3 ประโยค (ยอดขาย กำไร เทียบปีก่อน ดีกว่าหรือแย่กว่าที่ตลาดคาดถ้าเอกสารบอก)",
 "trend": "แนวโน้ม 4-8 ไตรมาส 1-2 ประโยค ว่ากำลังดีขึ้นหรือแย่ลง",
 "segments": [{{"name": "ชื่อธุรกิจภาษาไทยง่ายๆ", "value": "ยอดขาย เช่น $4.2 พันล้าน", "change": "โต/ลด กี่ % ถ้ามี"}}],
 "health": "สุขภาพการเงิน 2 ประโยค (เงินสด หนี้ กระแสเงินสด)",
 "direction": ["สิ่งที่ผู้บริหารบอกว่าจะทำต่อ ข้อละ 1 ประโยค สูงสุด 4 ข้อ"],
 "guidance": "คาดการณ์ไตรมาสหน้าหรือปีหน้าที่ผู้บริหารให้ไว้ 1-2 ประโยค หรือ \\"\\" ถ้าไม่มี",
 "risks": ["ความเสี่ยงที่บริษัทพูดถึงเอง สูงสุด 3 ข้อ"],
 "pros": ["ข้อดี 3 ข้อ"],
 "cons": ["ข้อควรระวัง 3 ข้อ"],
 "effect": "up|down|neutral  (งบนี้ทำให้หุ้นน่าซื้อขึ้น ลง หรือเท่าเดิม)",
 "effect_why": "1 ประโยค"
}}"""
        self.progress("AI กำลังอ่านงบและสรุปให้…")
        try:
            d = self.src.ask_ai(prompt)
        except SourceError as e:
            if e.kind == "key":
                raise
            return {"ok": False, "error": f"คำอธิบายจาก AI: {e.th}"}

        def lst(v, n):
            return [str(x).strip() for x in (v or []) if str(x).strip()][:n] if isinstance(v, list) else []
        segs = []
        for s in d.get("segments") or []:
            if isinstance(s, dict) and s.get("name"):
                segs.append({"name": str(s["name"]), "value": str(s.get("value") or ""), "change": str(s.get("change") or "")})
        return {"ok": True, "overview": str(d.get("overview") or ""), "trend": str(d.get("trend") or ""),
                "segments": segs[:6], "health": str(d.get("health") or ""), "direction": lst(d.get("direction"), 4),
                "guidance": str(d.get("guidance") or ""), "risks": lst(d.get("risks"), 3),
                "pros": lst(d.get("pros"), 3), "cons": lst(d.get("cons"), 3),
                "effect": d.get("effect") if d.get("effect") in ("up", "down", "neutral") else "neutral",
                "effect_why": str(d.get("effect_why") or "")}


# ---------------------------------------------------------------- filing helpers

_MDNA = re.compile(r"management[’'`]?s\s+discussion\s+and\s+analysis", re.I)
_END = re.compile(r"quantitative\s+and\s+qualitative\s+disclosures?\s+about\s+market\s+risk", re.I)


def find_mdna(text: str, limit: int = 40000) -> str:
    """The part of a 10-Q/10-K where management explains results and plans (skips the table of contents)."""
    best, best_len = None, 0
    for m in _MDNA.finditer(text):
        end = _END.search(text, m.end())
        length = (end.start() if end else len(text)) - m.start()
        if length > best_len:
            best, best_len = m.start(), length
    if best is None:
        start = len(text) // 10
        return text[start:start + limit]
    return text[best:best + min(best_len, limit)]


def pick_ex99(files: list[str]) -> str:
    """The press-release attachment of an earnings 8-K."""
    cands = [f for f in files if f.lower().endswith((".htm", ".html")) and re.search(r"ex[-_]?99|99[-_.]?1|ex991", f.lower())]
    cands.sort(key=lambda f: (0 if re.search(r"99[-_.]?1|991", f.lower()) else 1, len(f)))
    return cands[0] if cands else ""

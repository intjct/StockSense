"""The three buttons: วิเคราะห์ซื้อ / วิเคราะห์ขาย / วิเคราะห์งบล่าสุด.

Each returns a plain dict the UI draws. Numbers come from the data sources and
scoring rules; the AI only turns them into simple Thai."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

from . import fundamentals as F
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
        if not news:
            return []
        key = "news-ai-" + sym + "-" + hashlib.sha1(json.dumps([n["headline"] for n in news]).encode()).hexdigest()[:10]
        cached = self.src.cache.get(key, 2 * DAY)
        if cached is not None:
            return cached
        self.progress("AI กำลังแยกข่าวดีข่าวร้าย…")
        lines = "\n".join(f"[{i}] {n['date']} | {n['headline']} | {n['summary'][:300]}" for i, n in enumerate(news))
        prompt = f"""ข่าวของหุ้น {sym} ในช่วง 14 วัน แต่ละข่าวมีเลขกำกับ
{RULES}

งาน: บอกว่าแต่ละข่าว ดี (good) ร้าย (bad) หรือไม่ค่อยมีผล (neutral) ต่อราคาหุ้น {sym}
และสรุปแต่ละข่าวเป็นภาษาไทย 1 บรรทัด (ไม่เกิน 20 คำ) ข่าวที่ไม่เกี่ยวกับบริษัทนี้โดยตรงให้เป็น neutral

รูปแบบ JSON:
{{"news": [{{"i": 0, "effect": "good|bad|neutral", "line_th": "..."}}]}}

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
        self.src.cache.put(key, out)
        return out

    # ------------------------------------------------------------ buy / sell
    def run(self, sym: str, mode: str = "buy", holding: dict | None = None, fx: float | None = None) -> dict:
        g = self.gather(sym)
        news = []
        try:
            news = self.classify_news(g["sym"], g["news"])
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
        texts = self._explain(g, parts, news, score, label, mode, pos, flags)

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
        if g["is_etf"]:
            result["etf_note"] = ("นี่คือกองทุนรวมหุ้นหลายร้อยตัว ไม่มีงบการเงินของตัวเอง "
                                  + ("คนส่วนใหญ่ซื้อสะสมเรื่อยๆ ระยะยาว การรอจังหวะซื้อมักได้ผลไม่ต่างกันมาก"
                                     if mode == "buy" else
                                     "การขายเพราะตลาดลงชั่วคราวเป็นความผิดพลาดที่พบบ่อยที่สุด ถ้ายังถือยาวได้ มักไม่จำเป็นต้องขาย"))
        return result

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

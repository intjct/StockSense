"""Draws analysis results (buy / sell / latest statements) and the empty,
loading and error states."""
from __future__ import annotations

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QProgressBar, QVBoxLayout, QWidget

from . import theme
from .widgets import (MiniBars, PriceLine, Ring, baht, big_money, button, card, help_mark, label, money, pill, row,
                      signed_pct)

DISCLAIMER = "ข้อมูลนี้ช่วยประกอบการตัดสินใจเท่านั้น ไม่ใช่คำแนะนำการลงทุน · % คือสัดส่วนสัญญาณที่บอกว่าน่าซื้อหรือน่าขาย ไม่ใช่โอกาสได้กำไร"

FACTS = {
    "financials": [("sales_growth_vs_last_year_pct", "ยอดขายเทียบไตรมาสเดียวกันปีก่อน", "pct"),
                   ("profit_growth_vs_last_year_pct", "กำไรเทียบไตรมาสเดียวกันปีก่อน", "pct"),
                   ("profit_margin_now_pct", "ขาย 100 ดอลลาร์ เหลือเป็นกำไร", "usd_of_100"),
                   ("debt_to_equity", "หนี้สินทั้งหมด เทียบกับเงินของเจ้าของ", "times"),
                   ("operating_cash_last_year_usd", "เงินสดที่ธุรกิจหามาได้ (ปีล่าสุด)", "big")],
    "valuation": [("pe_now", "ราคาเทียบกำไร (P/E) ตอนนี้", "num"), ("pe_usual_5y", "ปกติช่วง 5 ปี อยู่ที่", "num"),
                  ("vs_usual_pct", "แพงหรือถูกกว่าปกติ", "pct"), ("dividend_yield_pct", "เงินปันผลต่อปี", "pct_plain")],
    "earnings": [("beats_last_4", "ไตรมาสที่กำไรออกมาดีกว่าคาด (จาก 4)", "int"),
                 ("last_surprise_pct", "ไตรมาสล่าสุด ดีกว่า/แย่กว่าที่คาด", "pct"),
                 ("next_earnings_date", "ประกาศงบครั้งหน้า", "text")],
    "analysts": [("analysts", "จำนวนนักวิเคราะห์", "int"), ("say_buy", "แนะนำซื้อ", "int"), ("say_hold", "แนะนำถือ", "int"),
                 ("say_sell", "แนะนำขาย", "int"), ("target_avg_usd", "ราคาเป้าหมายเฉลี่ย", "usd"),
                 ("upside_to_target_pct", "ห่างจากราคาเป้าหมาย", "pct")],
    "news": [("good", "ข่าวดี", "int"), ("bad", "ข่าวร้าย", "int"), ("neutral", "ไม่ค่อยมีผล", "int")],
    "chart": [("price", "ราคาตอนนี้", "usd"), ("avg_200_days", "ราคาเฉลี่ย 200 วัน", "usd"),
              ("support", "แนวรับ (จุดที่ราคามักเด้งขึ้น)", "usd"), ("resistance", "แนวต้าน (จุดที่ราคามักติด)", "usd"),
              ("change_1m_pct", "เปลี่ยนไปใน 1 เดือน", "pct"), ("change_3m_pct", "เปลี่ยนไปใน 3 เดือน", "pct")],
}


def _fmt(v, kind):
    if v is None:
        return None
    if kind == "pct":
        return signed_pct(v)
    if kind == "pct_plain":
        return f"{v:.2f}%"
    if kind == "usd":
        return money(v)
    if kind == "big":
        return big_money(v)
    if kind == "times":
        return f"{v:.2f} เท่า"
    if kind == "usd_of_100":
        return f"${v:.0f}"
    if kind == "num":
        return f"{v:,.1f}"
    if kind == "int":
        return f"{int(v)}"
    return str(v)


def _open(url: str):
    QDesktopServices.openUrl(QUrl(url))


def _tone_word(tone: str) -> str:
    return {"good": "▲", "bad": "▼", "mid": "●", "none": "–"}[tone]


# ---------------------------------------------------------------- part card

class PartCard(QFrame):
    def __init__(self, c: dict):
        super().__init__()
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(3)
        title = label(c["title"], 12, name="Soft")
        score = label("" if c["score"] is None else f"{c['score']}/100", 11, name="Faint")
        lay.addLayout(row(title, help_mark(c["help"]), None, score, spacing=6))
        fg = theme.TONE_FG[c["tone"]]
        short = label(c["short"], 14, True, wrap=True)
        arrow = label(_tone_word(c["tone"]), 13, True, color=fg)
        line = QHBoxLayout()
        line.setSpacing(8)
        line.addWidget(arrow, 0, Qt.AlignmentFlag.AlignTop)
        line.addWidget(short, 1)
        lay.addLayout(line)
        self.more = QWidget()
        ml = QVBoxLayout(self.more)
        ml.setContentsMargins(0, 6, 0, 0)
        ml.setSpacing(4)
        if c.get("detail"):
            ml.addWidget(label(c["detail"], 13, wrap=True))
        for key, name, kind in FACTS.get(c["key"], []):
            v = _fmt(c["facts"].get(key), kind)
            if v is not None:
                ml.addLayout(row(label(name, 12, name="Soft"), None, label(v, 12, True)))
        if ml.count() == 0:
            ml.addWidget(label("ไม่มีรายละเอียดเพิ่ม", 12, name="Soft"))
        self.more.setVisible(False)
        lay.addWidget(self.more)
        self.hint = label("แตะเพื่อดูรายละเอียด", 11, name="Faint")
        lay.addWidget(self.hint)

    def mousePressEvent(self, e):
        on = not self.more.isVisible()
        self.more.setVisible(on)
        self.hint.setText("แตะเพื่อย่อ" if on else "แตะเพื่อดูรายละเอียด")
        super().mousePressEvent(e)


def _metric(title: str, value: str, sub: str = "", tone: str | None = None) -> QFrame:
    f, l = card("SoftCard", (12, 10, 12, 10), 2)
    l.addWidget(label(title, 11, name="Soft"))
    l.addWidget(label(value, 17, True, color=theme.TONE_FG[tone] if tone else None))
    if sub:
        l.addWidget(label(sub, 11, name="Soft"))
    return f


def _section(title: str, tip: str = "") -> tuple[QFrame, QVBoxLayout]:
    f, l = card()
    head = [label(title, 14, True)]
    if tip:
        head.append(help_mark(tip))
    l.addLayout(row(*head, None, spacing=6))
    return f, l


def _footer(page: QVBoxLayout, missing: list[str]):
    if missing:
        page.addWidget(label("ข้อมูลบางส่วนดึงไม่ได้ ระบบจึงคิดจากส่วนที่เหลือ:\n• " + "\n• ".join(missing), 12,
                             name="Warn", wrap=True))
    page.addWidget(label(DISCLAIMER, 11, name="Faint", wrap=True))


# ---------------------------------------------------------------- buy / sell

def build_trade(r: dict, prev: dict | None = None, on_add_holding=None) -> QWidget:
    w = QWidget()
    w.setObjectName("Page")
    page = QVBoxLayout(w)
    page.setContentsMargins(0, 4, 0, 16)
    page.setSpacing(12)

    # header
    ring_color = theme.INK if r["kind"] == "buy" else theme.TONE_FG.get(r["tone"], theme.INK)
    head = QHBoxLayout()
    head.setSpacing(16)
    head.addWidget(Ring(r["score"], 104, ring_color), 0, Qt.AlignmentFlag.AlignTop)
    col = QVBoxLayout()
    col.setSpacing(4)
    word = "ความน่าซื้อ" if r["kind"] == "buy" else "ความน่าขาย"
    tone = "lime" if (r["kind"] == "buy" and r["tone"] == "good") else r["tone"]
    chg = r.get("day_change_pct")
    col.addLayout(row(pill(r["label"], tone), label(f"{word} {r['score']}%", 12, name="Soft"), None, spacing=8))
    col.addWidget(label(f"{r['name']}  ·  {r['sym']}", 19, True, wrap=True))
    col.addLayout(row(label(money(r["price"]), 14, True),
                      label(f"{signed_pct(chg)} วันนี้" if chg is not None else "", 12,
                            color=theme.GOOD if (chg or 0) >= 0 else theme.BAD), None, spacing=8))
    col.addWidget(label(r["headline"], 14, wrap=True))
    meta = f"วิเคราะห์เมื่อ {r['at']}"
    if prev:
        meta += f"  ·  ครั้งก่อน {prev['score']}% ({prev['at'][:10]})"
    col.addWidget(label(meta, 11, name="Faint"))
    head.addLayout(col, 1)
    page.addLayout(head)

    if r.get("etf_note"):
        page.addWidget(label(r["etf_note"], 13, name="Note", wrap=True))

    # position (sell)
    if r["kind"] == "sell":
        pos = r.get("position")
        if pos:
            f, l = _section("หุ้นที่คุณถืออยู่")
            grid = QGridLayout()
            grid.setSpacing(8)
            pl_tone = "good" if pos["pl"] >= 0 else "bad"
            grid.addWidget(_metric("มูลค่าตอนนี้", money(pos["value"]), baht(pos["value_thb"]) if pos["value_thb"] else ""), 0, 0)
            grid.addWidget(_metric("กำไร / ขาดทุน", money(pos["pl"]),
                                   f"{signed_pct(pos['pl_pct'])}" + (f" · {baht(pos['pl_thb'])}" if pos["pl_thb"] else ""),
                                   pl_tone), 0, 1)
            grid.addWidget(_metric("ต้นทุนเฉลี่ย", money(pos["avg_price"]), f"{pos['shares']:g} หุ้น"), 0, 2)
            grid.addWidget(_metric("ถ้าขายวันนี้ ได้เงินคืน", money(pos["value"]),
                                   baht(pos["value_thb"]) + " (ก่อนหักค่าธรรมเนียม)" if pos["value_thb"] else "ก่อนหักค่าธรรมเนียม"), 0, 3)
            l.addLayout(grid)
            if pos["reason"]:
                l.addWidget(label(f"เหตุผลที่คุณจดไว้ตอนซื้อ: “{pos['reason']}”", 12, name="Soft", wrap=True))
            if r.get("reason_check"):
                l.addWidget(label(r["reason_check"], 13, wrap=True))
            page.addWidget(f)
        else:
            f, l = card("SoftCard")
            l.addWidget(label(f"ยังไม่ได้เพิ่ม {r['sym']} ในพอร์ต เลยยังคำนวณกำไรขาดทุนให้ไม่ได้", 13, wrap=True))
            if on_add_holding:
                b = button("+ เพิ่มหุ้นนี้ในพอร์ต", "Ghost", 12)
                b.clicked.connect(lambda: on_add_holding(r["sym"]))
                l.addLayout(row(b, None))
            page.addWidget(f)
        for flag in r.get("flags") or []:
            page.addWidget(label("⚠ " + flag, 13, name="Danger", wrap=True))

    if r.get("conflict"):
        page.addWidget(label("ข้อมูลขัดกัน: " + r["conflict"], 13, name="Warn", wrap=True))

    # six parts
    grid = QGridLayout()
    grid.setSpacing(10)
    for i, c in enumerate(r["cards"]):
        grid.addWidget(PartCard(c), i // 2, i % 2, Qt.AlignmentFlag.AlignTop)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    page.addLayout(grid)

    # price chart
    if r.get("chart_closes"):
        f, l = _section("ราคาย้อนหลัง 6 เดือน", "เส้นประสีเขียว = แนวรับ จุดที่ราคามักเด้งขึ้น · สีแดง = แนวต้าน จุดที่ราคามักขึ้นไม่ผ่าน")
        buy = (r.get("position") or {}).get("avg_price") if r["kind"] == "sell" else None
        l.addWidget(PriceLine(r["chart_closes"], r.get("support"), r.get("resistance"), buy))
        page.addWidget(f)

    # news
    if r.get("news"):
        f, l = _section("ข่าว 14 วันล่าสุด", "AI อ่านหัวข่าวและเนื้อข่าวย่อ แล้วแยกว่าดีหรือร้ายต่อหุ้นตัวนี้")
        names = {"good": ("ดี", "good"), "bad": ("ร้าย", "bad"), "neutral": ("กลางๆ", "none")}
        for n in r["news"]:
            t, tn = names.get(n.get("effect"), ("กลางๆ", "none"))
            line = QHBoxLayout()
            line.setSpacing(10)
            p = pill(t, tn, 11)
            p.setFixedWidth(52)
            p.setAlignment(Qt.AlignmentFlag.AlignCenter)
            line.addWidget(p, 0, Qt.AlignmentFlag.AlignTop)
            txt = QVBoxLayout()
            txt.setSpacing(0)
            txt.addWidget(label(n.get("line_th") or n["headline"], 13, wrap=True))
            src = button(f"{n['source']} · {n['date']} ↗", "Link", 11)
            src.clicked.connect(lambda _=False, u=n["url"]: _open(u))
            src.setEnabled(bool(n.get("url")))
            txt.addWidget(src, 0, Qt.AlignmentFlag.AlignLeft)
            line.addLayout(txt, 1)
            l.addLayout(line)
        page.addWidget(f)

    extra = []
    if r.get("watch"):
        extra.append("สิ่งที่ควรจับตา: " + r["watch"])
    if r.get("next_earnings"):
        extra.append(f"ประกาศงบครั้งหน้า: {r['next_earnings']}")
    if extra:
        page.addWidget(label("\n".join(extra), 13, name="Note", wrap=True))
    _footer(page, r.get("missing") or [])
    page.addStretch(1)
    return w


# ---------------------------------------------------------------- latest statements

def _qlabel(q: str) -> str:
    return f"Q{q[-1]}/{q[2:4]}" if len(q) == 6 else q


def build_statement(r: dict) -> QWidget:
    w = QWidget()
    w.setObjectName("Page")
    page = QVBoxLayout(w)
    page.setContentsMargins(0, 4, 0, 16)
    page.setSpacing(12)
    s, ai = r["summary"], r.get("ai") or {}

    hl = {"strong": ("การเงินแข็งแรง", "good"), "ok": ("การเงินพอใช้", "mid"), "weak": ("การเงินน่าห่วง", "bad")}[r["health"]]
    pills = [pill(*hl)]
    if ai.get("effect"):
        e = {"up": ("งบนี้ทำให้น่าซื้อขึ้น", "lime"), "down": ("งบนี้ทำให้น่าซื้อลดลง", "bad"),
             "neutral": ("งบนี้ไม่ได้เปลี่ยนภาพมาก", "none")}[ai["effect"]]
        pills.append(pill(*e))
    page.addLayout(row(*pills, None, spacing=8))
    page.addWidget(label(f"{r['name']}  ·  {r['sym']}", 19, True, wrap=True))
    page.addWidget(label(f"งบล่าสุด รอบที่จบวันที่ {r['period']}  ·  วิเคราะห์เมื่อ {r['at']}", 11, name="Faint"))
    if ai.get("overview"):
        page.addWidget(label(ai["overview"], 15, wrap=True))
    if ai.get("effect_why"):
        page.addWidget(label(ai["effect_why"], 13, name="Soft", wrap=True))

    # trend charts
    qs = s["quarters"]
    f, l = _section("แนวโน้มรายไตรมาส", "แท่งล่าสุดคือสีเขียว · แท่งสีแดง = ขาดทุน · ตัวเลขจากงบที่บริษัทส่งให้ SEC")
    labels = [_qlabel(q["q"]) for q in qs]
    charts = QHBoxLayout()
    charts.setSpacing(18)
    for title, key, fmt in (("ยอดขาย", "revenue", big_money), ("กำไรสุทธิ", "net_income", big_money),
                            ("ขาย 100 ดอลลาร์ เหลือกำไร", "net_margin", lambda v: "-" if v is None else f"${v:.0f}")):
        c = QVBoxLayout()
        c.setSpacing(2)
        last = qs[-1].get(key) if qs else None
        c.addWidget(label(title, 12, name="Soft"))
        c.addWidget(label(fmt(last), 16, True))
        c.addWidget(MiniBars([q.get(key) for q in qs], labels))
        charts.addLayout(c, 1)
    l.addLayout(charts)
    yoy = []
    if s.get("revenue_yoy") is not None:
        yoy.append(f"ยอดขาย {signed_pct(s['revenue_yoy'])}")
    if s.get("net_income_yoy") is not None:
        yoy.append(f"กำไร {signed_pct(s['net_income_yoy'])}")
    if yoy:
        l.addWidget(label("เทียบไตรมาสเดียวกันปีก่อน: " + " · ".join(yoy), 12, name="Soft"))
    if ai.get("trend"):
        l.addWidget(label(ai["trend"], 13, wrap=True))
    page.addWidget(f)

    if ai.get("segments"):
        f, l = _section("เงินมาจากไหน", "บริษัทแบ่งธุรกิจเป็นส่วนๆ ดูว่าส่วนไหนทำเงินมากที่สุด และส่วนไหนโตหรือหด")
        for sg in ai["segments"]:
            l.addLayout(row(label(sg["name"], 13), None, label(sg["value"], 13, True),
                            label(sg["change"], 12, name="Soft"), spacing=12))
        page.addWidget(f)

    # health
    f, l = _section("สุขภาพการเงิน", "ดูว่าบริษัทมีเงินสดพอไหม หนี้เยอะไหม และธุรกิจหาเงินสดได้จริงหรือเปล่า")
    grid = QGridLayout()
    grid.setSpacing(8)
    cf = [c for c in s.get("cashflow") or [] if c.get("ocf") is not None]
    eq, liab = s.get("equity"), s.get("liabilities")
    tiles = [("เงินสด + เงินฝากระยะสั้น", big_money((s.get("cash") or 0) + (s.get("short_investments") or 0)) if s.get("cash") is not None else "-"),
             ("หนี้เงินกู้", big_money(s.get("debt"))),
             (f"เงินสดจากธุรกิจ ปี {cf[-1]['year']}" if cf else "เงินสดจากธุรกิจ", big_money(cf[-1]["ocf"]) if cf else "-"),
             ("หนี้สินทั้งหมด เทียบเงินเจ้าของ", f"{liab / eq:.2f} เท่า" if (eq and eq > 0 and liab is not None) else "-")]
    for i, (t, v) in enumerate(tiles):
        grid.addWidget(_metric(t, v), 0, i)
    l.addLayout(grid)
    if ai.get("health"):
        l.addWidget(label(ai["health"], 13, wrap=True))
    page.addWidget(f)

    if ai.get("direction") or ai.get("guidance"):
        f, l = _section("บริษัทจะไปทางไหน")
        for d in ai.get("direction") or []:
            l.addWidget(label("• " + d, 13, wrap=True))
        if ai.get("guidance"):
            l.addWidget(label("คาดการณ์ของผู้บริหาร: " + ai["guidance"], 13, True, wrap=True))
        l.addWidget(label("นี่คือสิ่งที่ผู้บริหารบอกเอง ไม่ได้แปลว่าจะเกิดขึ้นจริงเสมอ", 11, name="Faint"))
        page.addWidget(f)

    if ai.get("risks"):
        f, l = _section("ความเสี่ยงที่บริษัทยอมรับเอง")
        for x in ai["risks"]:
            l.addWidget(label("• " + x, 13, wrap=True))
        page.addWidget(f)

    if ai.get("pros") or ai.get("cons"):
        two = QHBoxLayout()
        two.setSpacing(10)
        for title, items, tone in (("ข้อดี", ai.get("pros") or [], "good"), ("ข้อควรระวัง", ai.get("cons") or [], "bad")):
            f, l = card()
            l.addWidget(label(title, 14, True, color=theme.TONE_FG[tone]))
            for x in items:
                l.addWidget(label("• " + x, 13, wrap=True))
            l.addStretch(1)
            two.addWidget(f, 1)
        page.addLayout(two)

    if r.get("links"):
        f, l = _section("เอกสารต้นฉบับของบริษัท")
        for lk in r["links"]:
            b = button(lk["title"] + " ↗", "Link", 12)
            b.clicked.connect(lambda _=False, u=lk["url"]: _open(u))
            l.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        page.addWidget(f)

    _footer(page, r.get("missing") or [])
    page.addStretch(1)
    return w


# ---------------------------------------------------------------- states

def build_empty(keys_ready: bool, on_settings) -> QWidget:
    w = QWidget()
    w.setObjectName("Page")
    page = QVBoxLayout(w)
    page.setContentsMargins(0, 24, 0, 0)
    page.setSpacing(12)
    page.addWidget(label("พิมพ์ชื่อหุ้นด้านบน แล้วเลือกปุ่มที่ต้องการ", 18, True))
    rows = [("วิเคราะห์ซื้อ", "ดู 6 เรื่อง (งบ ราคา ผลประกอบการ นักวิเคราะห์ ข่าว กราฟ) แล้วบอกว่าน่าซื้อกี่ %"),
            ("วิเคราะห์ขาย", "ใช้กับหุ้นที่ถืออยู่ บอกกำไรขาดทุน และบอกว่าน่าขายกี่ %"),
            ("วิเคราะห์งบล่าสุด", "อ่านงบไตรมาสล่าสุดที่บริษัทส่ง SEC แล้วสรุปเป็นภาษาง่ายๆ")]
    for t, d in rows:
        f, l = card("SoftCard", (14, 10, 14, 10), 2)
        l.addWidget(label(t, 14, True))
        l.addWidget(label(d, 13, name="Soft", wrap=True))
        page.addWidget(f)
    if not keys_ready:
        f, l = card()
        l.addWidget(label("ก่อนเริ่ม: ใส่คีย์ฟรี 2 อัน (ทำครั้งเดียว ใช้เวลาประมาณ 5 นาที)", 14, True))
        l.addWidget(label("1. คีย์ Gemini ให้ AI สรุปเป็นภาษาคน\n2. คีย์ Finnhub สำหรับข่าวและความเห็นนักวิเคราะห์\n"
                          "3. กดปุ่มด้านล่าง แล้วทำตามขั้นตอนในหน้าตั้งค่า", 13, wrap=True))
        b = button("ไปที่ตั้งค่า", "Lime", 13, True)
        b.clicked.connect(on_settings)
        l.addLayout(row(b, None))
        page.addWidget(f)
    page.addStretch(1)
    return w


class Loading(QWidget):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("Page")
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 40, 0, 0)
        page.setSpacing(10)
        page.addWidget(label(title, 18, True))
        self.step = label("กำลังเริ่ม…", 13, name="Soft")
        page.addWidget(self.step)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedHeight(5)
        bar.setStyleSheet(f"QProgressBar{{background:{theme.SOFT.name()};border:none;border-radius:2px;}}"
                          f"QProgressBar::chunk{{background:{theme.INK.name()};border-radius:2px;}}")
        page.addWidget(bar)
        page.addWidget(label("ครั้งแรกอาจใช้เวลา 20–40 วินาที ครั้งต่อไปจะเร็วขึ้น เพราะโปรแกรมจำข้อมูลไว้", 12, name="Faint", wrap=True))
        page.addStretch(1)
        self.steps: list[str] = []

    def set_step(self, text: str):
        self.steps.append(text)
        self.step.setText(text)


def build_error(text: str, is_key: bool, on_settings, on_retry) -> QWidget:
    w = QWidget()
    w.setObjectName("Page")
    page = QVBoxLayout(w)
    page.setContentsMargins(0, 30, 0, 0)
    page.setSpacing(12)
    page.addWidget(label("ยังวิเคราะห์ไม่ได้", 18, True))
    page.addWidget(label(text, 14, name="Danger", wrap=True))
    b1 = button("ไปที่ตั้งค่า", "Lime", 13, True) if is_key else button("ลองใหม่", "Dark", 13)
    b1.clicked.connect(on_settings if is_key else on_retry)
    page.addLayout(row(b1, None))
    page.addStretch(1)
    return w

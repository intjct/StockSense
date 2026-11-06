"""Main window: black portfolio sidebar on the left, search + 4 buttons + results on the right."""
from __future__ import annotations

from PySide6.QtCore import QStringListModel, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QCompleter, QFrame, QHBoxLayout, QLineEdit, QMenu, QScrollArea, QVBoxLayout, QWidget)

from .. import APP_NAME, VERSION
from ..analysis import Analyzer
from ..net import Cache, Http, SourceError
from .. import rules as RL
from ..portfolio import History, Portfolio
from ..sources import ALIASES, ETFS, Sources
from . import results as R
from . import theme
from .dialogs import HoldingDialog, RulesDialog, SettingsDialog, ask
from .updatebar import UpdateBar
from .widgets import baht, button, clear, label, money, row, run_in_background, signed_pct

QColorBad = QColor("#FF6B5A")        # red that reads on the black sidebar


class HoldingRow(QFrame):
    clicked = Signal(str)
    menu = Signal(str, object)

    def __init__(self, h: dict, price: float | None, selected: bool, alert: str | None = None):
        super().__init__()
        self.ticker = h["ticker"]
        self.setObjectName("HoldingOn" if selected else "Holding")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        col = QVBoxLayout()
        col.setSpacing(0)
        title = [label(h["ticker"], 13, True)]
        if alert:
            dot = QFrame()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(f"background:{'#FF6B5A' if alert == 'hit' else '#F2B84B'}; border-radius:4px; border:none;")
            title.append(dot)
        col.addLayout(row(*title, None, spacing=6))
        col.addWidget(label(f"{h['shares']:g} หุ้น", 11, name="SideSoft"))
        lay.addLayout(col, 1)
        if price is not None and h.get("avg_price"):
            ch = (price - h["avg_price"]) / h["avg_price"] * 100
            right = QVBoxLayout()
            right.setSpacing(0)
            right.addWidget(label(signed_pct(ch, 0), 13, True, color=theme.LIME if ch >= 0 else QColorBad), 0, Qt.AlignmentFlag.AlignRight)
            right.addWidget(label(money(price), 11, name="SideSoft"), 0, Qt.AlignmentFlag.AlignRight)
            lay.addLayout(right)
        else:
            lay.addWidget(label("…", 12, name="SideSoft"))
        self.setToolTip(h.get("name") or h["ticker"])

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.ticker)
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        self.menu.emit(self.ticker, e.globalPos())


class MainWindow(QWidget):
    def __init__(self, settings, portfolio: Portfolio | None = None, history: History | None = None,
                 http: Http | None = None, check_updates: bool = True):
        super().__init__()
        self.s = settings
        self.pf = portfolio or Portfolio()
        self.hist = history or History()
        self.http = http or Http()
        self.cache = Cache()
        self.busy = False
        self.prices: dict[str, float] = {}
        self.fx: float | None = None
        self.selected = ""
        self.last: dict | None = None
        self.last_kind = ""
        self.rule_status: dict[str, list] = {}   # ticker -> evaluated เงื่อนไขเปลี่ยนใจ
        self.names: dict[str, str] = {}        # completer text -> ticker
        self.online_names: dict[str, str] = {}
        self.setObjectName("Main")
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(theme.app_icon())
        self.resize(1180, 780)
        self.setMinimumSize(980, 640)
        self.setStyleSheet(theme.STYLE)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._sidebar())

        right = QWidget()
        right.setObjectName("Right")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(26, 20, 26, 0)
        rl.setSpacing(10)
        self.update_bar = UpdateBar(busy=lambda: self.busy)
        rl.addWidget(self.update_bar)

        self.search = QLineEdit(self.s.last_ticker)
        self.search.setPlaceholderText("พิมพ์ชื่อหุ้น เช่น NVDA, Apple, Google, S&P 500")
        self.search.setFont(theme.font(14))
        self.search.setMinimumHeight(44)
        self.model = QStringListModel(self)
        comp = QCompleter(self.model, self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setMaxVisibleItems(10)
        comp.popup().setFont(theme.font(13))
        self.search.setCompleter(comp)
        self._typed = QTimer(self)
        self._typed.setSingleShot(True)
        self._typed.setInterval(350)
        self._typed.timeout.connect(self._search_online)
        self.search.textEdited.connect(lambda _t: self._typed.start())
        self.sec_loaded = False
        rl.addWidget(self.search)

        self.b_buy = button("วิเคราะห์ซื้อ", "Lime", 14, True)
        self.b_sell = button("วิเคราะห์ขาย", "Dark", 14)
        self.b_stmt = button("วิเคราะห์งบล่าสุด", "Outline", 14)
        self.b_port = button("ตรวจพอร์ต", "Outline", 14)
        for b, kind in ((self.b_buy, "buy"), (self.b_sell, "sell"), (self.b_stmt, "statement"), (self.b_port, "portfolio")):
            b.setMinimumHeight(44)
            b.clicked.connect(lambda _=False, k=kind: self.run(k))
        bl = QHBoxLayout()
        bl.setSpacing(8)
        for b in (self.b_buy, self.b_sell, self.b_stmt, self.b_port):
            bl.addWidget(b, 1)
        rl.addLayout(bl)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("Page")
        self.body_l = QVBoxLayout(self.body)
        self.body_l.setContentsMargins(0, 6, 8, 0)
        self.scroll.setWidget(self.body)
        rl.addWidget(self.scroll, 1)
        outer.addWidget(right, 1)

        self._fill_names({})
        self.show_empty()
        self.refresh_portfolio()
        self._load_tickers()
        self.check_rules_async()
        if check_updates:
            self.update_bar.start()

    # ------------------------------------------------------------ sidebar
    def _sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("Side")
        side.setFixedWidth(248)
        l = QVBoxLayout(side)
        l.setContentsMargins(16, 18, 16, 14)
        l.setSpacing(6)
        dot = QFrame()
        dot.setFixedSize(12, 12)
        dot.setStyleSheet(f"background:{theme.LIME.name()}; border-radius:3px;")
        l.addLayout(row(dot, label(APP_NAME, 17, True), None, spacing=8))
        l.addSpacing(14)
        l.addWidget(label("พอร์ตของผม", 12, name="SideSoft"))
        self.total = label("$0.00", 24, True)
        self.total_thb = label("", 12, name="SideSoft")
        self.total_pl = label("", 12, True)
        l.addWidget(self.total)
        l.addWidget(self.total_thb)
        l.addWidget(self.total_pl)
        self.alert_holder = QWidget()
        self.alert_holder.setStyleSheet("background: transparent;")
        self.alert_l = QVBoxLayout(self.alert_holder)
        self.alert_l.setContentsMargins(0, 6, 0, 0)
        self.alert_l.setSpacing(4)
        l.addWidget(self.alert_holder)
        l.addSpacing(10)
        self.list_holder = QWidget()
        self.list_holder.setStyleSheet("background: transparent;")
        self.list_l = QVBoxLayout(self.list_holder)
        self.list_l.setContentsMargins(0, 0, 0, 0)
        self.list_l.setSpacing(4)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.list_holder)
        sc.setStyleSheet("QScrollArea{background:transparent;border:none;} QScrollArea > QWidget > QWidget{background:transparent;}")
        l.addWidget(sc, 1)
        add = button("+ เพิ่มหุ้น", "SideAdd", 13)
        add.clicked.connect(lambda: self.add_holding())
        l.addWidget(add)
        l.addSpacing(6)
        st = button("⚙  ตั้งค่า", "SideLink", 13)
        st.clicked.connect(self.open_settings)
        l.addWidget(st)
        l.addWidget(label(f"เวอร์ชัน {VERSION}", 11, name="SideSoft"))
        return side

    def refresh_portfolio(self, fetch: bool = True):
        clear(self.list_l)
        total = paid = 0.0
        known = True
        for h in self.pf.holdings:
            p = self.prices.get(h["ticker"])
            r = HoldingRow(h, p, h["ticker"] == self.selected, self._alert_of(h["ticker"]))
            r.clicked.connect(self.select)
            r.menu.connect(self._holding_menu)
            self.list_l.addWidget(r)
            if p is None:
                known = False
            else:
                total += p * h["shares"]
                paid += h["avg_price"] * h["shares"]
        if not self.pf.holdings:
            self.list_l.addWidget(label("ยังไม่มีหุ้นในพอร์ต\nกด “+ เพิ่มหุ้น” ด้านล่าง", 12, name="SideSoft", wrap=True))
        self.list_l.addStretch(1)
        if self.pf.holdings and known:
            self.total.setText(money(total))
            self.total_thb.setText(f"≈ {baht(total * self.fx)}" if self.fx else "")
            ch = (total - paid) / paid * 100 if paid else 0
            self.total_pl.setText(f"{signed_pct(ch)} ตั้งแต่ซื้อ")
            self.total_pl.setStyleSheet(f"color:{(theme.LIME if ch >= 0 else QColorBad).name()};")
        elif self.pf.holdings:
            self.total.setText("…")
        else:
            self.total.setText("$0.00")
            self.total_thb.setText("")
            self.total_pl.setText("")
        if fetch and self.pf.holdings:
            tickers = [h["ticker"] for h in self.pf.holdings]
            src = self._sources()

            def work(_p):
                out, fx = {}, None
                for t in tickers:
                    try:
                        out[t] = src.price(t)
                    except SourceError:
                        pass
                try:
                    fx = src.usd_thb()
                except SourceError:
                    pass
                return out, fx

            def done(res, err):
                if res:
                    self.prices.update(res[0])
                    self.fx = res[1] or self.fx
                    self.refresh_portfolio(fetch=False)
            run_in_background(work, done)

    # ------------------------------------------------------------ เงื่อนไขเปลี่ยนใจ
    def _alert_of(self, ticker: str) -> str | None:
        sm = RL.summary(self.rule_status.get(ticker) or [])
        return "hit" if sm["hit"] else "near" if sm["near"] else None

    def refresh_alerts(self):
        clear(self.alert_l)
        for h in self.pf.holdings:
            res = self.rule_status.get(h["ticker"]) or []
            sm = RL.summary(res)
            if not (sm["hit"] or sm["near"]):
                continue
            hit = bool(sm["hit"])
            text = (f"⚠ {h['ticker']} · เงื่อนไขเกิดแล้ว {sm['hit']} ข้อ" if hit
                    else f"● {h['ticker']} · ใกล้ถึงเงื่อนไข {sm['near']} ข้อ")
            b = button(text + "  ดูเลย", "SideAlert" if hit else "SideNear", 12)
            b.setToolTip("กดเพื่อดูผลวิเคราะห์ขายของหุ้นตัวนี้ และตัดสินใจว่าจะถือต่อไหม")
            b.clicked.connect(lambda _=False, t=h["ticker"]: self._open_sell(t))
            self.alert_l.addWidget(b)
        self.refresh_portfolio(fetch=False)

    def check_rules_async(self):
        """Quietly checks every holding's rules (no AI). Runs at start-up and after any change."""
        holdings = [dict(h) for h in self.pf.holdings]
        src = self._sources()

        def done(res, err):
            if res is not None:
                self.rule_status = res
            elif err is not None:
                return
            self.refresh_alerts()
        run_in_background(lambda _p: Analyzer(src).check_rules(holdings), done)

    def edit_rules(self, ticker: str, suggested: list):
        h = self.pf.get(ticker)
        if not h:
            return
        price = self.prices.get(ticker)
        d = RulesDialog(self, ticker, suggested or h.get("rules") or [], price)
        if not d.exec() or d.result_rules is None:
            return
        h = dict(h)
        h["rules"] = d.result_rules
        self.pf.upsert(h)
        if self.last and self.last_kind == "sell" and self.last["sym"] == ticker and self.last.get("rule_ctx") is not None:
            self.last["rules"] = RL.evaluate_all(d.result_rules, self.last["rule_ctx"])
            self.last["suggested_rules"] = []
            bar = self.scroll.verticalScrollBar().value()
            self._set_page(R.build_trade(self.last, None, self.add_holding, self.edit_rules))
            self.scroll.verticalScrollBar().setValue(bar)
            self.rule_status[ticker] = self.last["rules"]
            self.refresh_alerts()
        self.check_rules_async()

    def select(self, ticker: str):
        self.selected = ticker
        self.search.setText(ticker)
        self.refresh_portfolio(fetch=False)

    def _holding_menu(self, ticker: str, pos):
        m = QMenu(self)
        m.setFont(theme.font(13))
        a1 = QAction("วิเคราะห์ขาย", m)
        a1.triggered.connect(lambda: (self.select(ticker), self.run("sell")))
        a2 = QAction("แก้ไข", m)
        a2.triggered.connect(lambda: self.add_holding(ticker))
        a3 = QAction("ลบออกจากพอร์ต", m)
        a3.triggered.connect(lambda: self._remove(ticker))
        for a in (a1, a2, a3):
            m.addAction(a)
        m.exec(pos)

    def _remove(self, ticker: str):
        if ask(self, f"ลบ {ticker} ออกจากพอร์ต?", "แค่ลบออกจากโปรแกรมนี้ ไม่ได้ขายหุ้นจริงในแอป Dime", "ลบออก"):
            self.pf.remove(ticker)
            self.rule_status.pop(ticker, None)
            self.refresh_alerts()

    def add_holding(self, ticker: str = ""):
        existing = self.pf.get(ticker) if ticker else None
        d = HoldingDialog(self, self.model, existing, ticker=ticker, resolve=self.resolve)
        if not d.exec():
            return
        if d.removed and existing:
            self.pf.remove(existing["ticker"])
        elif d.result_holding:
            h = d.result_holding
            h["name"] = next((n.split(" — ", 1)[-1] for n, t in self.names.items() if t == h["ticker"] and " — " in n),
                             h["ticker"])
            self.pf.upsert(h)
            self.selected = h["ticker"]
        self.refresh_portfolio()
        self.check_rules_async()

    # ------------------------------------------------------------ search
    def _fill_names(self, sec: dict):
        names: dict[str, str] = {}
        for t, n in ETFS.items():
            names[f"{t} — {n}"] = t
        for t, row_ in sec.items():
            names.setdefault(f"{t} — {row_['name']}", t)
        for a, t in ALIASES.items():
            names.setdefault(f"{a.title() if a.isascii() else a} → {t}", t)
        names.update(self.online_names)          # names found by the live search must survive the SEC list arriving later
        self.names = names
        self.model.setStringList(sorted(names, key=lambda s: (len(s.split(" ")[0]), s)))

    def _load_tickers(self, attempt: int = 0):
        """Full company list from SEC. If it fails, try again a bit later (the online search covers meanwhile)."""
        src = self._sources()

        def done(res, err):
            if res:
                self.sec_loaded = True
                self._fill_names(res)
            elif attempt < 4:
                QTimer.singleShot(30000 * (attempt + 1), lambda: self._load_tickers(attempt + 1))
        run_in_background(lambda _p: src.sec_tickers(), done)

    def _add_names(self, rows: list[dict]):
        added = False
        for r in rows:
            key = f"{r['ticker']} — {r['name']}"
            if key not in self.names:
                self.names[key] = self.online_names[key] = r["ticker"]
                added = True
        if added:
            self.model.setStringList(sorted(self.names, key=lambda s: (len(s.split(" ")[0]), s)))

    def _search_online(self):
        text = self.search.text().strip()
        if len(text) < 2 or " — " in text or " → " in text:
            return
        src = self._sources()

        def done(res, err):
            if res and text == self.search.text().strip():
                self._add_names(res)
                c = self.search.completer()
                if c is not None and self.search.hasFocus():
                    c.setCompletionPrefix(text)
                    c.complete()
        run_in_background(lambda _p: src.search(text), done)

    def resolve(self, text: str) -> str:
        t = (text or "").strip()
        if not t:
            return ""
        if t in self.names:
            return self.names[t]
        for sepr in (" — ", " → "):
            if sepr in t:
                return (t.split(sepr)[-1] if sepr == " → " else t.split(sepr)[0]).strip().upper()
        up = t.upper()
        if up in ALIASES:
            return ALIASES[up]
        if t in ALIASES:
            return ALIASES[t]
        return up.replace(".", "-").replace(" ", "")

    def _looks_like_name(self, text: str, sym: str) -> bool:
        """True when the box holds a company name we don't know yet (e.g. "Palantir"), not a ticker."""
        t = text.strip()
        if t in self.names or t.upper() in ALIASES or t in ALIASES or " — " in t or " → " in t:
            return False
        return sym not in self.names.values() and (len(sym) > 5 or " " in t or not t.isascii())

    def _lookup_then_run(self, kind: str, text: str):
        src = self._sources()
        self._set_busy(True)
        self._set_page(R.Loading(f"กำลังหาหุ้นชื่อ “{text}”"))

        def done(res, err):
            self._set_busy(False)
            if res:
                self._add_names(res)
                self.search.setText(res[0]["ticker"])
                self.run(kind)
            else:
                self._set_page(R.build_error(f"ไม่เจอหุ้นสหรัฐชื่อ “{text}” ลองพิมพ์ชื่อภาษาอังกฤษ หรือตัวย่อหุ้น เช่น DELL", False,
                                             self.open_settings, lambda: self.run(kind)))
        run_in_background(lambda _p: src.search(text), done)

    # ------------------------------------------------------------ run
    def _sources(self) -> Sources:
        return Sources(self.http, self.cache, gemini_key=self.s.gemini_key, finnhub_key=self.s.finnhub_key)

    def _set_page(self, w: QWidget):
        clear(self.body_l)
        self.body_l.addWidget(w)
        self.scroll.verticalScrollBar().setValue(0)

    def show_empty(self):
        self._set_page(R.build_empty(self.s.keys_ready, self.open_settings))

    def _set_busy(self, on: bool):
        self.busy = on
        for b in (self.b_buy, self.b_sell, self.b_stmt, self.b_port):
            b.setEnabled(not on)

    def run(self, kind: str):
        if self.busy:
            return
        sym = "" if kind == "portfolio" else self.resolve(self.search.text())
        if kind != "portfolio" and sym and self._looks_like_name(self.search.text(), sym):
            self._lookup_then_run(kind, self.search.text().strip())
            return
        if kind != "portfolio" and not sym:
            self.search.setFocus()
            self.search.setPlaceholderText("พิมพ์ชื่อหุ้นก่อน แล้วค่อยกดปุ่ม")
            return
        if not self.s.keys_ready:
            self._set_page(R.build_error("ต้องใส่คีย์ Gemini และ Finnhub ก่อน (ฟรีทั้งคู่) กดปุ่มด้านล่างแล้วทำตามขั้นตอน",
                                         True, self.open_settings, lambda: self.run(kind)))
            return
        if kind == "portfolio" and not self.pf.holdings:
            self._set_page(R.build_error("ยังไม่มีหุ้นในพอร์ต กด “+ เพิ่มหุ้น” ทางซ้ายก่อน แล้วค่อยกดตรวจพอร์ต", False,
                                         self.open_settings, lambda: self.add_holding()))
            return
        if kind != "portfolio":
            self.search.setText(sym)
            self.s.last_ticker = sym
            self.s.save()
        titles = {"buy": f"กำลังวิเคราะห์ซื้อ {sym}", "sell": f"กำลังวิเคราะห์ขาย {sym}",
                  "statement": f"กำลังอ่านงบล่าสุดของ {sym}", "portfolio": "กำลังตรวจพอร์ตของคุณ"}
        note = ("ตรวจทีละตัว ถ้าถือหลายตัวอาจใช้เวลาประมาณ 1 นาที ครั้งต่อไปจะเร็วขึ้นเพราะโปรแกรมจำข้อมูลไว้"
                if kind == "portfolio" else None)
        loading = R.Loading(titles[kind], note) if note else R.Loading(titles[kind])
        self._set_page(loading)
        self._set_busy(True)
        src = self._sources()
        holding = self.pf.get(sym) if sym else None
        holdings = [dict(h) for h in self.pf.holdings]

        def work(progress):
            a = Analyzer(src, progress)
            if kind == "statement":
                return a.statements(sym)
            fx = None
            try:
                fx = src.usd_thb()
            except SourceError:
                pass
            if kind == "portfolio":
                return a.check_portfolio(holdings, fx)
            return a.run(sym, kind, holding if kind == "sell" else None, fx,
                         holdings=holdings if kind in ("buy", "sell") else None)

        def done(res, err):
            self._set_busy(False)
            if err is not None:
                if isinstance(err, SourceError):
                    msg, is_key = err.th, err.kind == "key"
                else:
                    msg, is_key = "เกิดข้อผิดพลาดที่ไม่คาดคิด ลองกดใหม่อีกครั้ง", False
                self._set_page(R.build_error(msg, is_key, self.open_settings, lambda: self.run(kind)))
                return
            self.show_result(res)
        run_in_background(work, done, loading.set_step)

    def _open_sell(self, ticker: str):
        self.select(ticker)
        self.run("sell")

    def show_result(self, res: dict):
        self.last, self.last_kind = res, res["kind"]
        if res["kind"] == "statement":
            self._set_page(R.build_statement(res))
            return
        if res["kind"] == "portfolio":
            for x in res["ranking"]:
                if x.get("price") is not None:
                    self.prices[x["ticker"]] = x["price"]
            self.refresh_portfolio(fetch=False)
            self._set_page(R.build_portfolio(res, self._open_sell))
            return
        self.hist.add(res)
        prev = self.hist.previous(res["sym"], res["kind"])
        if res["sym"] in {h["ticker"] for h in self.pf.holdings}:
            self.prices[res["sym"]] = res["price"]
            self.refresh_portfolio(fetch=False)
        if res["kind"] == "sell" and res.get("rules") is not None:
            self.rule_status[res["sym"]] = res["rules"]
            self.refresh_alerts()
        self._set_page(R.build_trade(res, prev, self.add_holding, self.edit_rules))

    # ------------------------------------------------------------ settings
    def open_settings(self):
        d = SettingsDialog(self, self.s, self.update_bar)
        if d.exec() and self.last is None:
            self.show_empty()

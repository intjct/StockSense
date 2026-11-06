"""Settings (keys, update) and add/edit a holding."""
from __future__ import annotations

from PySide6.QtCore import QDate, QLocale, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCompleter, QDialog, QHBoxLayout, QSpinBox, QDoubleSpinBox, QLineEdit, QMessageBox, QVBoxLayout,
                               QWidget)

from .. import VERSION
from ..net import Cache, Http, SourceError
from ..sources import Sources
from . import theme
from .widgets import button, card, label, row, run_in_background


def ask(parent, title: str, text: str, yes: str, no: str = "ยกเลิก") -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(title)
    box.setInformativeText(text)
    y = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
    box.addButton(no, QMessageBox.ButtonRole.RejectRole)
    box.setStyleSheet(theme.STYLE)
    box.exec()
    return box.clickedButton() is y


class KeyBox(QWidget):
    def __init__(self, title: str, why: str, steps: list[str], url: str, value: str, tester):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        f, l = card()
        l.addWidget(label(title, 14, True))
        l.addWidget(label(why, 12, name="Soft", wrap=True))
        l.addWidget(label("\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)), 12, wrap=True))
        open_b = button("เปิดหน้าสมัคร ↗", "Link", 12)
        open_b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        l.addLayout(row(open_b, None))
        self.edit = QLineEdit(value)
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText("วางคีย์ตรงนี้")
        self.edit.setFont(theme.font(13))
        self.test_b = button("ลองใช้คีย์", "Ghost", 12)
        self.test_b.clicked.connect(self._test)
        l.addLayout(row(self.edit, self.test_b))
        self.status = label("", 12, name="Soft", wrap=True)
        l.addWidget(self.status)
        lay.addWidget(f)
        self.tester = tester

    def value(self) -> str:
        return self.edit.text().strip()

    def _test(self):
        key = self.value()
        if not key:
            self.status.setText("ยังไม่ได้วางคีย์")
            return
        self.test_b.setEnabled(False)
        self.status.setText("กำลังลอง…")

        def done(_, err):
            self.test_b.setEnabled(True)
            if err is None:
                self.status.setText("✓ ใช้ได้")
                self.status.setStyleSheet(f"color:{theme.GOOD.name()};")
            else:
                self.status.setText(err.th if isinstance(err, SourceError) else "ลองไม่สำเร็จ ลองอีกครั้ง")
                self.status.setStyleSheet(f"color:{theme.BAD.name()};")
        run_in_background(lambda _p: self.tester(key), done)


def _test_gemini(key: str):
    Sources(Http(), Cache(), gemini_key=key).ask_ai('ตอบกลับเป็น JSON นี้เท่านั้น: {"ok": true}')


def _test_finnhub(key: str):
    Http().get_json("finnhub", "https://finnhub.io/api/v1/quote", params={"symbol": "AAPL"},
                    headers={"X-Finnhub-Token": key})


class SettingsDialog(QDialog):
    def __init__(self, parent, settings, update_bar=None, testers=None):
        super().__init__(parent)
        self.s = settings
        self.setWindowTitle("ตั้งค่า · StockSense")
        self.setMinimumWidth(560)
        self.setStyleSheet(theme.STYLE)
        tg, tf = testers or (_test_gemini, _test_finnhub)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)
        lay.addWidget(label("ตั้งค่า", 20, True))
        lay.addWidget(label("คีย์ทั้ง 2 อันฟรี เก็บแบบเข้ารหัสอยู่ในเครื่องนี้เท่านั้น ไม่ถูกส่งไปที่อื่น", 12, name="Soft", wrap=True))
        self.gem = KeyBox("คีย์ Gemini (ให้ AI สรุปเป็นภาษาคน)",
                          "ฟรี ใช้บัญชี Google · มีโควตาต่อวัน ใช้คนเดียวเหลือเฟือ",
                          ["กด “เปิดหน้าสมัคร” แล้วล็อกอินด้วยบัญชี Google",
                           "กดปุ่ม “Create API key”", "คัดลอกคีย์ แล้ววางในช่องด้านล่าง", "กด “ลองใช้คีย์” ให้ขึ้น ✓ ใช้ได้"],
                          "https://aistudio.google.com/apikey", settings.gemini_key, tg)
        self.fin = KeyBox("คีย์ Finnhub (ข่าว นักวิเคราะห์ ผลประกอบการ)",
                          "ฟรี สมัครด้วยอีเมล · ใช้ได้กับหุ้นสหรัฐ",
                          ["กด “เปิดหน้าสมัคร” แล้วสมัครด้วยอีเมล", "ยืนยันอีเมล แล้วล็อกอิน",
                           "หน้า Dashboard จะมีคีย์ (API key) อยู่ด้านบน", "คัดลอกคีย์มาวาง แล้วกด “ลองใช้คีย์”"],
                          "https://finnhub.io/register", settings.finnhub_key, tf)
        lay.addWidget(self.gem)
        lay.addWidget(self.fin)

        f, l = card()
        self.upd_status = label(f"เวอร์ชันที่ใช้อยู่ {VERSION}", 12, name="Soft")
        chk = button("เช็กเวอร์ชันใหม่", "Ghost", 12)
        chk.clicked.connect(lambda: update_bar.check(self.upd_status.setText) if update_bar else None)
        l.addLayout(row(self.upd_status, None, chk))
        lay.addWidget(f)

        save = button("บันทึก", "Lime", 13, True)
        save.clicked.connect(self._save)
        cancel = button("ปิด", "Ghost", 13)
        cancel.clicked.connect(self.reject)
        lay.addLayout(row(None, cancel, save))

    def _save(self):
        self.s.gemini_key = self.gem.value()
        self.s.finnhub_key = self.fin.value()
        self.s.save()
        self.accept()


class DateBoxes(QWidget):
    """Day / month / year boxes with plain 0-9 digits and Gregorian year (ignores Windows Thai locale)."""

    def __init__(self, start):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        eng = QLocale(QLocale.Language.English)
        self.d, self.m, self.y = QSpinBox(), QSpinBox(), QSpinBox()
        for box, lo, hi, w in ((self.d, 1, 31, 70), (self.m, 1, 12, 70), (self.y, 1990, 2100, 96)):
            box.setLocale(eng)
            box.setRange(lo, hi)
            box.setGroupSeparatorShown(False)
            box.setFont(theme.font(13))
            box.setFixedWidth(w)
            box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            box.setKeyboardTracking(False)
        lay.addWidget(self.d)
        lay.addWidget(label("/", 14))
        lay.addWidget(self.m)
        lay.addWidget(label("/", 14))
        lay.addWidget(self.y)
        today = button("วันนี้", "Ghost", 12)
        today.clicked.connect(lambda: self.set_value(QDate.currentDate()))
        lay.addWidget(today)
        lay.addStretch(1)
        self.set_value(start)

    def set_value(self, qd):
        self.y.setValue(qd.year())
        self.m.setValue(qd.month())
        self.d.setValue(qd.day())

    def value(self):
        """Always a real date: a day too big for the month (31 Feb) is pulled back to the month's last day."""
        y, m = self.y.value(), self.m.value()
        last = QDate(y, m, 1).daysInMonth()
        return QDate(y, m, min(self.d.value(), last))


class HoldingDialog(QDialog):
    def __init__(self, parent, completer_model=None, holding: dict | None = None, ticker: str = "", resolve=None):
        super().__init__(parent)
        self.resolve = resolve or (lambda t: t.upper().strip())
        self.removed = False
        self.result_holding: dict | None = None
        editing = holding is not None
        self.setWindowTitle("แก้ไขหุ้นในพอร์ต" if editing else "เพิ่มหุ้นในพอร์ต")
        self.setMinimumWidth(440)
        self.setStyleSheet(theme.STYLE)
        h = holding or {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(8)
        lay.addWidget(label("แก้ไขหุ้นในพอร์ต" if editing else "เพิ่มหุ้นในพอร์ต", 18, True))

        def field(title, w, hint=""):
            lay.addWidget(label(title, 12, name="Soft"))
            lay.addWidget(w)
            if hint:
                lay.addWidget(label(hint, 11, name="Faint", wrap=True))

        self.ticker = QLineEdit(h.get("ticker") or ticker)
        self.ticker.setPlaceholderText("เช่น NVDA หรือ Apple")
        self.ticker.setFont(theme.font(13))
        if completer_model is not None:
            c = QCompleter(completer_model, self)
            c.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            c.setFilterMode(Qt.MatchFlag.MatchContains)
            c.popup().setFont(theme.font(13))
            self.ticker.setCompleter(c)
        self.ticker.setEnabled(not editing)
        field("ชื่อหุ้น", self.ticker)
        self.shares = QDoubleSpinBox()
        self.shares.setDecimals(6)
        self.shares.setRange(0, 1e9)
        self.shares.setValue(float(h.get("shares") or 0))
        self.shares.setFont(theme.font(13))
        field("จำนวนหุ้นที่ถือ", self.shares, "ซื้อเป็นเศษหุ้นใน Dime ได้ ใส่ทศนิยมได้เลย เช่น 0.25")
        self.price = QDoubleSpinBox()
        self.price.setDecimals(4)
        self.price.setRange(0, 1e7)
        self.price.setPrefix("$ ")
        self.price.setValue(float(h.get("avg_price") or 0))
        self.price.setFont(theme.font(13))
        field("ราคาเฉลี่ยที่ซื้อ (ดอลลาร์ต่อหุ้น)", self.price, "ดูได้ในแอป Dime หน้าหุ้นตัวนั้น ช่อง “ราคาเฉลี่ย”")
        start = QDate.fromString(h["buy_date"], "yyyy-MM-dd") if h.get("buy_date") else QDate.currentDate()
        self.date = DateBoxes(start)
        field("ซื้อครั้งแรกเมื่อ (วัน / เดือน / ปี ค.ศ.)", self.date, "พิมพ์ตัวเลขได้เลย เช่น 15 / 3 / 2025 · ไม่แน่ใจวันที่ กดปุ่ม “วันนี้” ได้")
        self.reason = QLineEdit(h.get("reason") or "")
        self.reason.setPlaceholderText("เช่น เชื่อว่าธุรกิจ AI จะโตอีกหลายปี")
        self.reason.setFont(theme.font(13))
        field("ซื้อเพราะอะไร (ไม่ใส่ก็ได้)", self.reason, "ปุ่มวิเคราะห์ขายจะเช็กให้ว่าเหตุผลนี้ยังจริงอยู่ไหม")
        self.err = label("", 12, color=theme.BAD)
        lay.addWidget(self.err)

        save = button("บันทึก", "Lime", 13, True)
        save.clicked.connect(self._save)
        cancel = button("ยกเลิก", "Ghost", 13)
        cancel.clicked.connect(self.reject)
        items = []
        if editing:
            rm = button("ลบออกจากพอร์ต", "Link", 12)
            rm.clicked.connect(self._remove)
            items.append(rm)
        lay.addLayout(row(*items, None, cancel, save))

    def _save(self):
        t = self.resolve(self.ticker.text())
        if not t:
            self.err.setText("ใส่ชื่อหุ้นก่อน")
            return
        if self.shares.value() <= 0:
            self.err.setText("ใส่จำนวนหุ้นที่ถือ (มากกว่า 0)")
            return
        if self.price.value() <= 0:
            self.err.setText("ใส่ราคาเฉลี่ยที่ซื้อ")
            return
        self.result_holding = {"ticker": t, "shares": self.shares.value(), "avg_price": self.price.value(),
                               "buy_date": self.date.value().toString("yyyy-MM-dd"), "reason": self.reason.text()}
        self.accept()

    def _remove(self):
        if ask(self, "ลบหุ้นนี้ออกจากพอร์ต?", "แค่ลบออกจากโปรแกรมนี้ ไม่ได้ขายหุ้นจริงในแอป Dime", "ลบออก"):
            self.removed = True
            self.accept()

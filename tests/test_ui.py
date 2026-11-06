import time

import pytest
from PySide6.QtWidgets import QApplication

from stocksense.fakedata import FakeInternet
from stocksense.net import Http
from stocksense.portfolio import History, Portfolio
from stocksense.settings import Settings


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from stocksense.ui import theme
    theme.load_fonts()
    return a


def _wait(app, cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end and not cond():
        app.processEvents()
        time.sleep(0.02)
    assert cond()


def _win(keys=True):
    from stocksense.ui.mainwindow import MainWindow
    s = Settings()
    if keys:
        s.gemini_key, s.finnhub_key = "g", "f"
    pf = Portfolio()
    pf.upsert({"ticker": "NVDA", "shares": 3, "avg_price": 100, "reason": "AI"})
    return MainWindow(s, pf, History(), http=Http(FakeInternet()), check_updates=False)


def test_three_buttons(app):
    w = _win()
    w.show()
    for kind, btn in (("buy", w.b_buy), ("sell", w.b_sell), ("statement", w.b_stmt)):
        w.search.setText("nvidia")
        btn.click()
        assert w.busy and not w.b_buy.isEnabled()
        _wait(app, lambda: not w.busy)
        assert w.last_kind == kind and w.b_buy.isEnabled()
    assert w.search.text() == "NVDA"
    _wait(app, lambda: "NVDA" in w.prices)
    assert w.total.text().startswith("$")


def test_no_keys_points_to_settings(app):
    w = _win(keys=False)
    w.search.setText("NVDA")
    w.run("buy")
    assert not w.busy and w.last is None


def test_resolve_names(app):
    w = _win()
    assert w.resolve("Google") == "GOOGL"
    assert w.resolve("s&p 500") == "VOO"
    assert w.resolve("QQQ — Invesco QQQ (Nasdaq-100)") == "QQQ"
    assert w.resolve("brk.b") == "BRK-B"
    assert w.resolve("แอปเปิล") == "AAPL"


def test_error_page_on_unknown(app):
    w = _win()
    w.search.setText("ZZZZ")
    w.run("buy")
    _wait(app, lambda: not w.busy)
    assert w.last is None


def test_part_card_expands(app):
    from stocksense.ui.results import PartCard
    c = PartCard({"key": "chart", "title": "กราฟราคา", "help": "h", "score": 70, "tone": "good", "short": "ขึ้น",
                  "detail": "รายละเอียด", "facts": {"price": 10, "support": 9}})
    c.show()
    assert not c.more.isVisible()
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(c, Qt.MouseButton.LeftButton)
    assert c.more.isVisible()
    QTest.mouseClick(c, Qt.MouseButton.LeftButton)
    assert not c.more.isVisible()


def test_holding_date_boxes_plain_digits(qtbot_app=None):
    from PySide6.QtCore import QDate
    from stocksense.ui.dialogs import DateBoxes
    b = DateBoxes(QDate(2025, 3, 15))
    assert (b.d.text(), b.m.text(), b.y.text()) == ("15", "3", "2025")
    b.d.setValue(31); b.m.setValue(2); b.y.setValue(2025)
    assert b.value() == QDate(2025, 2, 28)

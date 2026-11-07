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


def test_portfolio_button_and_buy_note(app):
    w = _win()
    w.pf.upsert({"ticker": "VOO", "shares": 2, "avg_price": 300, "buy_date": "2025-06-01"})
    w.show()
    w.b_port.click()
    assert w.busy and not w.b_port.isEnabled()
    _wait(app, lambda: not w.busy)
    assert w.last_kind == "portfolio" and w.last["count"] == 2
    assert w.last["ranking"][0]["ticker"] in ("NVDA", "VOO")
    w.search.setText("AAPL")
    w.b_buy.click()
    _wait(app, lambda: not w.busy)
    assert w.last_kind == "buy" and w.last["fit"] and w.last["fit"]["amount"] == 500


def test_portfolio_button_empty_portfolio(app):
    from stocksense.ui.mainwindow import MainWindow
    s = Settings()
    s.gemini_key, s.finnhub_key = "g", "f"
    w = MainWindow(s, Portfolio(), History(), http=Http(FakeInternet()), check_updates=False)
    w.run("portfolio")
    assert not w.busy and w.last is None


def test_search_works_without_sec_list(app):
    w = _win()
    w.show()
    w.search.setText("dell")
    w._search_online()
    _wait(app, lambda: any(t == "DELL" for t in w.names.values()))
    assert "DELL — Dell Technologies Inc." in w.names and not any("DELL.DE" in k for k in w.names)
    w.search.setText("Palantir")                       # a name nobody typed a ticker for
    w.run("buy")
    _wait(app, lambda: not w.busy and w.search.text() == "PLTR" or (not w.busy and w.last is not None), 20)
    assert w.search.text() == "PLTR"


def test_sec_list_retries(app, monkeypatch):
    from stocksense.sources import Sources
    n = {"c": 0}
    real = Sources.sec_tickers

    def flaky(self):
        n["c"] += 1
        if n["c"] == 1:
            raise SourceError("other", "x", "sec")
        return real(self)
    from stocksense.net import SourceError
    monkeypatch.setattr(Sources, "sec_tickers", flaky)
    w = _win()
    _wait(app, lambda: n["c"] >= 1)
    assert not w.sec_loaded


def test_rules_alert_in_sidebar_and_sell_page(app):
    from stocksense import rules as RL
    w = _win()
    w.pf.upsert({"ticker": "NVDA", "shares": 3, "avg_price": 100,
                 "rules": [{"kind": "price_below", "value": 10000.0, "on": True}, RL.make("earnings_miss")]})
    w.check_rules_async()
    _wait(app, lambda: "NVDA" in w.rule_status)
    assert w._alert_of("NVDA") == "hit" and w.alert_l.count() == 1
    w.search.setText("NVDA")
    w.run("sell")
    _wait(app, lambda: not w.busy)
    assert w.last["rules"][0]["state"] == "hit" and w.last["suggested_rules"] == []
    w.pf.upsert({"ticker": "NVDA", "shares": 4, "avg_price": 100})            # edit form must not lose the rules
    assert len(w.pf.get("NVDA")["rules"]) == 2


def test_rules_dialog_edit(app):
    from stocksense import rules as RL
    from stocksense.ui.dialogs import RulesDialog
    d = RulesDialog(None, "NVDA", RL.default_rules(140.0, 123.0), 140.0)
    assert [r["kind"] for r in d.rules] == ["price_below", "loss_pct", "weight_above", "earnings_miss"]
    d.rules.pop(0)
    d._add("price_below")
    d._save()
    out = d.result_rules
    assert [r["kind"] for r in out][-1] == "price_below" and out[-1]["value"] == 119.0 and len(out) == 4


def test_analyst_section_draws(app, src):
    from stocksense.analysis import Analyzer
    from stocksense.ui import results as R
    from stocksense.ui.widgets import Avatar
    r = Analyzer(src).run("NVDA", "buy")
    w = R.build_trade(r)
    assert w.findChildren(Avatar) and len(w.findChildren(Avatar)) == len(r["analyst_box"]["people"])
    box = {"summary": None, "people": []}
    page = R.build_trade({**r, "analyst_box": box})
    assert page is not None


def _win_net():
    from stocksense.ui.mainwindow import MainWindow
    net = FakeInternet()
    s = Settings()
    s.gemini_key, s.finnhub_key = "g", "f"
    pf = Portfolio()
    pf.upsert({"ticker": "NVDA", "shares": 3, "avg_price": 100, "reason": "AI"})
    return MainWindow(s, pf, History(), http=Http(net), check_updates=False), net


def test_history_panel_opens_old_result_without_any_request(app):
    from PySide6.QtWidgets import QFrame
    w, net = _win_net()
    w.show()
    w.search.setText("NVDA")
    w.b_buy.click()
    _wait(app, lambda: not w.busy)
    w.toggle_history()
    assert w.hist_panel.isVisible() and w.b_hist.text() == "ปิดประวัติ"
    assert len(w.hist_panel.rows) == 1 and w.hist_panel.rows[0].e["sym"] == "NVDA"
    _wait(app, lambda: not w.busy)
    n = len(net.calls)
    w.open_history(w.hist_panel.rows[0].e)
    app.processEvents()
    assert len(net.calls) == n                                       # nothing downloaded, no AI
    assert w.body.findChild(QFrame, "OldBanner") is not None
    w.toggle_history()
    assert not w.hist_panel.isVisible()


def test_history_row_without_full_result_explains(app):
    w, net = _win_net()
    w.hist.rows.insert(0, {"kind": "buy", "sym": "OLD", "name": "Old Co", "score": 55, "label": "ก้ำกึ่ง",
                           "tone": "mid", "price": 5, "at": "2026-11-01 10:00"})
    w.hist_panel.refresh()
    assert w.hist_panel.rows[0].check is None                        # can't compare a score-only row
    w.open_history(w.hist_panel.rows[0].e)
    assert not net.calls or all("OLD" not in u for u in net.calls)


def test_compare_two_saved_analyses(app):
    import copy
    w, net = _win_net()
    w.show()
    w.search.setText("NVDA")
    w.b_buy.click()
    _wait(app, lambda: not w.busy)
    a = w.last
    b = copy.deepcopy(a)
    b["sym"], b["name"], b["score"], b["at"] = "AMD", "AMD Inc", a["score"] - 20, "2026-11-01 09:00"
    w.hist.add(b)
    w.hist_panel.refresh()
    checks = [r for r in w.hist_panel.rows if r.check is not None]
    assert len(checks) == 2
    checks[0].check.setChecked(True)
    assert "อีก 1 ตัว" in w.hist_panel.hint.text()
    checks[1].check.setChecked(True)
    assert "เปรียบเทียบได้เลย" in w.hist_panel.hint.text()
    n = len(net.calls)
    w.hist_panel.b_cmp.click()
    _wait(app, lambda: not w.busy)
    assert w.last_kind == "compare" and w.last["leader"] in ("a", "b")
    assert len(net.calls) - n == 1                                   # exactly one AI call
    assert w.last["ai_ok"]

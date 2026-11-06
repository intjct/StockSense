"""`StockSense.exe --selftest` — proves the finished .exe really works on Windows.

Runs all three buttons against a pretend internet (no keys, no quota),
checks encrypted key storage, HTTPS certificates, the bundled Prompt font,
the update check, and that the window draws every result page.
Writes %TEMP%\\stocksense-selftest.txt and exits 0 on success."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback


def selftest() -> int:
    lines: list[str] = []
    ok = True
    out_file = os.path.join(tempfile.gettempdir(), "stocksense-selftest.txt")
    work = tempfile.mkdtemp(prefix="stocksense-selftest-")
    os.environ["STOCKSENSE_CONFIG_DIR"] = os.path.join(work, "config")
    if not sys.platform.startswith("win") and not os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    def check(name, fn):
        nonlocal ok
        try:
            detail = fn()
            lines.append(f"PASS  {name}  {detail or ''}")
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f"FAIL  {name}  {e}\n{traceback.format_exc()}")

    from . import VERSION
    lines.append(f"StockSense {VERSION} selftest in {work}")

    def keys():
        from .settings import Settings
        s = Settings()
        s.gemini_key, s.finnhub_key = "AIza-test-คีย์", "fh-test"
        s.save()
        s2 = Settings.load()
        assert s2.gemini_key == "AIza-test-คีย์" and s2.finnhub_key == "fh-test"
        assert "AIza" not in s2.gemini_blob
        return s2.gemini_blob.split(":", 1)[0]
    check("encrypted key storage", keys)

    def certs():
        import requests.certs
        p = requests.certs.where()
        assert os.path.exists(p), p
        return os.path.basename(p)
    check("https certificates", certs)

    from .analysis import Analyzer
    from .fakedata import FakeInternet
    from .net import Cache, Http
    from .sources import Sources
    src = Sources(Http(FakeInternet()), Cache(os.path.join(work, "cache")), gemini_key="g", finnhub_key="f")
    res = {}

    def buy():
        r = Analyzer(src).run("NVDA", "buy")
        assert 0 <= r["score"] <= 100 and len(r["cards"]) == 6 and r["ai_ok"], r
        res["buy"] = r
        return f"{r['score']}% {r['label']}"
    check("buy analysis", buy)

    def sell():
        r = Analyzer(src).run("NVDA", "sell", {"shares": 2, "avg_price": 90, "buy_date": "2025-01-02", "reason": "AI"}, 35.0)
        assert r["position"]["pl"] > 0 and r["position"]["value_thb"], r["position"]
        res["sell"] = r
        return f"{r['score']}% {r['label']}"
    check("sell analysis", sell)

    def etf():
        r = Analyzer(src).run("VOO", "buy")
        assert r["is_etf"] and r["etf_note"]
        return f"{r['score']}%"
    check("index fund", etf)

    def stmt():
        r = Analyzer(src).statements("NVDA")
        assert r["ai"]["overview"] and r["summary"]["has_data"] and r["links"]
        res["stmt"] = r
        return r["health"]
    check("latest statements", stmt)

    def portfolio():
        hs = [{"ticker": "NVDA", "shares": 5, "avg_price": 90, "buy_date": "2025-01-02"},
              {"ticker": "VOO", "shares": 2, "avg_price": 300, "buy_date": "2025-06-01"}]
        r = Analyzer(src).check_portfolio(hs, 35.0)
        assert r["count"] == 2 and 0 <= r["health"] <= 100 and r["currency"] and r["headline"], r
        res["portfolio"] = r
        f = Analyzer(src).run("AAPL", "buy", None, 35.0, holdings=hs)["fit"]
        assert f and f["amount"] == 500, f
        return f"health {r['health']}%"
    check("portfolio check", portfolio)

    def rules_check():
        from . import rules as RL
        hs = [{"ticker": "NVDA", "shares": 5, "avg_price": 90, "buy_date": "2025-01-02",
               "rules": [RL.make("price_below", 99999.0), RL.make("loss_pct", 20.0)]}]
        out = Analyzer(src).check_rules(hs)
        assert "NVDA" in out, out
        sm = RL.summary(out["NVDA"])
        assert sm["hit"] >= 1, out
        return f"hit {sm['hit']}"
    check("change-of-mind rules", rules_check)

    def update_check():
        from . import updater
        assert updater.is_newer("1.0.1", "1.0.0") and not updater.is_newer("0.0.1", VERSION)
        return "ok"
    check("update version compare", update_check)

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    def fonts():
        from PySide6.QtGui import QFontDatabase
        from .ui import theme
        theme.load_fonts()
        fams = QFontDatabase.families()
        assert "Prompt" in fams, "Prompt font missing"
        return "Prompt"
    check("bundled font", fonts)

    def window():
        from .portfolio import History, Portfolio
        from .settings import Settings
        from .ui.mainwindow import MainWindow
        from .ui import results as R
        s = Settings.load()
        pf = Portfolio()
        pf.upsert({"ticker": "NVDA", "shares": 2, "avg_price": 90})
        w = MainWindow(s, pf, History(), http=Http(FakeInternet()), check_updates=False)
        w.show()
        for k in ("buy", "sell", "stmt", "portfolio"):
            if k in res:
                w.show_result(res[k])
                app.processEvents()
        w._set_page(R.build_empty(False, lambda: None))
        app.processEvents()
        end = time.time() + 5
        while time.time() < end and "NVDA" not in w.prices:
            app.processEvents()
            time.sleep(0.05)
        w.close()
        return f"price {w.prices.get('NVDA')}"
    check("window draws", window)

    lines.append("RESULT " + ("OK" if ok else "FAILED"))
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    return 0 if ok else 1

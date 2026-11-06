from stocksense import updater
from stocksense.portfolio import History, Portfolio
from stocksense.settings import Settings


def test_keys_are_encrypted_and_survive_reload():
    s = Settings()
    s.gemini_key, s.finnhub_key = " AIzaSecret ", "fh"
    s.save()
    raw = open(__import__("os").path.join(__import__("stocksense.settings", fromlist=["x"]).config_dir(), "settings.json"),
               encoding="utf-8").read()
    assert "AIzaSecret" not in raw
    s2 = Settings.load()
    assert s2.gemini_key == "AIzaSecret" and s2.keys_ready


def test_portfolio_roundtrip():
    p = Portfolio()
    p.upsert({"ticker": "nvda", "shares": "1.5", "avg_price": 100})
    p.upsert({"ticker": "NVDA", "shares": 2, "avg_price": 110})
    assert len(Portfolio().holdings) == 1 and Portfolio().get("nvda")["shares"] == 2
    p.remove("NVDA")
    assert Portfolio().holdings == []


def test_history_previous():
    h = History()
    for sc in (50, 60):
        h.add({"kind": "buy", "sym": "AAPL", "score": sc, "label": "x", "price": 1, "at": "t"})
    assert h.previous("AAPL", "buy")["score"] == 50
    h.add({"kind": "statement", "sym": "AAPL"})
    assert len(History().rows) == 2


def test_updater_rules():
    assert updater.REPO == "intjct/StockSense"
    assert updater.is_newer("1.1.0", "1.0.0") and not updater.is_newer("1.0.0", "1.0.0")
    assert updater.INSTALLER_RE.match("StockSense-Setup-1.2.0.exe")

    class R:
        def __init__(self, d):
            self.d = d

        def raise_for_status(self):
            pass

        def json(self):
            return self.d
    data = {"tag_name": "v9.0.0", "body": "## StockSense 9.0.0\n- ใหม่",
            "assets": [{"name": "StockSense-Setup-9.0.0.exe", "size": 5,
                        "browser_download_url": "https://github.com/intjct/StockSense/releases/download/v9.0.0/StockSense-Setup-9.0.0.exe"}]}
    u = updater.check("1.0.0", get=lambda *a, **k: R(data))
    assert u and u.version == "9.0.0" and u.notes == "ใหม่"
    bad = dict(data, assets=[dict(data["assets"][0], browser_download_url="https://evil.example/x.exe")])
    assert updater.check("1.0.0", get=lambda *a, **k: R(bad)) is None

import pytest

from stocksense import scoring as S
from stocksense.analysis import Analyzer, find_mdna, pick_ex99
from stocksense.fakedata import FakeInternet
from stocksense.net import Cache, Http, SourceError
from stocksense.sources import Sources, html_to_text, parse_ai_json


def test_buy_has_six_parts_and_stable_score(src):
    a = Analyzer(src)
    r1 = a.run("NVDA", "buy")
    assert [c["key"] for c in r1["cards"]] == list(S.PARTS)
    assert all(c["score"] is not None for c in r1["cards"])
    assert r1["label"] == S.buy_label(r1["score"])[0]
    r2 = a.run("NVDA", "buy")                      # same data -> same number
    assert r2["score"] == r1["score"]
    assert len(r1["news"]) == 5 and {n["effect"] for n in r1["news"]} <= {"good", "bad", "neutral"}


def test_sell_position_math(src):
    r = Analyzer(src).run("NVDA", "sell", {"shares": 10, "avg_price": 100, "buy_date": "2025-01-01", "reason": "AI"}, 35.0)
    p = r["position"]
    assert p["value"] == pytest.approx(10 * r["price"])
    assert p["pl"] == pytest.approx(10 * (r["price"] - 100))
    assert p["value_thb"] == pytest.approx(p["value"] * 35)
    assert r["reason_check"]
    assert r["label"] == S.sell_label(r["score"])[0]


def test_sell_score_is_mirror_of_buy_parts(src):
    a = Analyzer(src)
    b, s = a.run("NVDA", "buy"), a.run("NVDA", "sell")
    assert b["score"] >= 60 and s["score"] <= 40


def test_etf_has_no_company_parts_and_calm_sell(src):
    a = Analyzer(src)
    r = a.run("VOO", "sell")
    keys = {c["key"]: c["score"] for c in r["cards"]}
    assert keys["financials"] is None and keys["valuation"] is None
    assert r["score"] <= 55 and "ตลาดลง" in r["etf_note"]
    assert not any("sec.gov" in u for u in src.net.calls)


def test_statement(src):
    r = Analyzer(src).statements("NVDA")
    assert r["health"] == "strong"
    assert len(r["summary"]["quarters"]) == 8
    assert r["summary"]["quarters"][-1]["q"] == "2026Q3"
    assert r["ai"]["segments"] and r["ai"]["pros"]
    assert any("ex991" in l["url"] for l in r["links"])
    calls = len(src.net.calls)
    Analyzer(src).statements("NVDA")                 # cached: no new AI call
    assert not any("generativelanguage" in u for u in src.net.calls[calls:])


def test_statement_rejects_etf(src):
    with pytest.raises(SourceError) as e:
        Analyzer(src).statements("SPY")
    assert "กองทุน" in e.value.th


def test_unknown_ticker(src):
    with pytest.raises(SourceError) as e:
        Analyzer(src).run("ZZZZ", "buy")
    assert e.value.kind == "notfound"


def test_missing_key_is_a_key_error(tmp_path):
    s = Sources(Http(FakeInternet()), Cache(str(tmp_path / "c")), gemini_key="", finnhub_key="")
    with pytest.raises(SourceError) as e:
        Analyzer(s).run("NVDA", "buy")
    assert e.value.kind == "key"


def test_bad_gemini_key_is_a_key_error(tmp_path):
    s = Sources(Http(FakeInternet(gemini_status=400)), Cache(str(tmp_path / "c")), gemini_key="bad", finnhub_key="f")
    with pytest.raises(SourceError) as e:
        Analyzer(s).run("NVDA", "buy")
    assert e.value.kind == "key" and "Gemini" in e.value.th


def test_gemini_quota_still_shows_scores(tmp_path):
    s = Sources(Http(FakeInternet(gemini_status=429)), Cache(str(tmp_path / "c")), gemini_key="g", finnhub_key="f")
    r = Analyzer(s).run("NVDA", "buy")
    assert r["score"] is not None and not r["ai_ok"]
    assert any("โควตา" in m for m in r["missing"])
    assert all(c["short"] for c in r["cards"])


def test_bad_finnhub_key(tmp_path):
    s = Sources(Http(FakeInternet(finnhub_status=401)), Cache(str(tmp_path / "c")), gemini_key="g", finnhub_key="x")
    with pytest.raises(SourceError) as e:
        Analyzer(s).run("NVDA", "buy")
    assert e.value.kind == "key" and "Finnhub" in e.value.th


def test_network_down(tmp_path):
    s = Sources(Http(lambda *a: (None, "")), Cache(str(tmp_path / "c")), gemini_key="g", finnhub_key="f")
    with pytest.raises(SourceError) as e:
        Analyzer(s).run("NVDA", "buy")
    assert e.value.kind == "network"


def test_helpers():
    assert parse_ai_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_ai_json('ok here {"a": 2} done') == {"a": 2}
    with pytest.raises(SourceError):
        parse_ai_json("no json")
    t = html_to_text("<p>Hello&nbsp;<b>world</b></p><script>x()</script><table><tr><td>A</td><td>1</td></tr></table>")
    assert "Hello world" in t and "x()" not in t
    assert pick_ex99(["a.htm", "nvda-ex99_1.htm", "ex99-2.htm", "R1.htm"]) == "nvda-ex99_1.htm"
    toc = "Management's Discussion and Analysis 25 Quantitative and Qualitative Disclosures About Market Risk 40 "
    body = "Management’s Discussion and Analysis of results " + "growth " * 500 + \
           "Quantitative and Qualitative Disclosures About Market Risk"
    assert find_mdna(toc + body).startswith("Management’s Discussion")


def test_scoring_rules():
    assert S.combine({"chart": {"score": 80}, "news": {"score": None}}) == 80
    assert S.combine({"chart": {"score": 80}}, "sell") == 20
    assert S.combine({"news": {"score": None}}) is None
    assert S.valuation({"metric": {"peTTM": -5}})["score"] == 30
    assert S.analysts([{"period": "x", "strongBuy": 10}], {}, 100)["score"] > 80
    assert S.earnings([{"period": "a", "actual": 1, "estimate": 2}] * 4)["score"] < 30
    assert S.buy_label(70)[0] == "น่าซื้อ" and S.buy_label(54)[0] == "รอก่อน"
    assert S.sell_label(65)[0] == "น่าพิจารณาขาย"


# ---------------------------------------------------------------- portfolio check

def test_exposures_look_through_and_overlap():
    from stocksense import portfolio_check as PC
    items = [{"ticker": "NVDA", "value": 6000, "is_etf": False}, {"ticker": "VOO", "value": 4000, "is_etf": True}]
    ex = PC.exposures(items)
    b = PC.bets(ex)
    nv = next(x for x in b if x["name"] == "NVDA")
    assert round(nv["direct_pct"]) == 60 and round(nv["via_pct"], 1) == 3.2     # 4000 * 8% = 320 of 10000
    assert round(nv["pct"], 1) == 63.2
    assert [o["name"] for o in PC.overlaps(b)] == ["NVDA"]            # held directly AND inside the fund
    assert PC.concentration_score(63.2) == 0 and PC.concentration_score(20) == 100 and PC.concentration_score(10) == 100
    assert round(PC.stress_loss(63.2), 1) == 19.0


def test_goog_counts_as_googl_and_spread_funds_are_not_a_bet():
    from stocksense import portfolio_check as PC
    b = PC.bets(PC.exposures([{"ticker": "GOOG", "value": 100, "is_etf": False},
                              {"ticker": "GOOGL", "value": 100, "is_etf": False},
                              {"ticker": "SCHD", "value": 800, "is_etf": True}]))
    assert len(b) == 1 and b[0]["name"] == "GOOGL" and round(b[0]["pct"]) == 20


def test_currency_split_adds_up():
    from stocksense import portfolio_check as PC
    rows = [{"value": 1100.0, "paid": 1000.0, "fx_buy": 32.0}, {"value": 500.0, "paid": 600.0, "fx_buy": 36.0},
            {"value": 50.0, "paid": 40.0, "fx_buy": None}]
    c = PC.currency_split(rows, 35.0)
    assert round(c["stock_thb"] + c["currency_thb"], 6) == round(c["total_thb"], 6)
    assert c["counted"] == 2 and c["skipped"] == 1
    assert round(c["total_thb"]) == round((1100 + 500) * 35 - (1000 * 32 + 600 * 36))
    assert PC.currency_split([{"value": 1, "paid": 1, "fx_buy": None}], 35.0) is None


def test_buy_fit_warns_when_too_heavy():
    from stocksense import portfolio_check as PC
    items = [{"ticker": "NVDA", "value": 600, "is_etf": False}, {"ticker": "AAPL", "value": 400, "is_etf": False}]
    f = PC.buy_fit(items, "NVDA", False, 500)
    assert round(f["weight_before"]) == 60 and round(f["weight_after"]) == 73 and f["tone"] == "bad"
    assert PC.buy_fit([], "NVDA", False, 500) is None
    g = PC.buy_fit(items, "VOO", True, 500)
    assert g["is_fund"] and g["top_after"]["name"] == "NVDA"


def test_check_portfolio_end_to_end(src):
    analyzer = Analyzer(src)
    holdings = [{"ticker": "NVDA", "shares": 10, "avg_price": 90, "buy_date": "2025-01-02", "name": "NVIDIA"},
                {"ticker": "VOO", "shares": 2, "avg_price": 300, "buy_date": "2025-06-01", "name": "S&P 500"},
                {"ticker": "AAPL", "shares": 4, "avg_price": 150, "buy_date": "", "name": "Apple"}]
    r = analyzer.check_portfolio(holdings, 35.0)
    assert r["kind"] == "portfolio" and r["count"] == 3 and 0 <= r["health"] <= 100
    assert abs(sum(x["weight"] for x in r["ranking"]) - 100) < 1e-6
    scores = [x["score"] for x in r["ranking"]]
    assert scores == sorted(scores, reverse=True)
    assert r["currency"] and r["currency"]["counted"] == 2 and r["currency"]["skipped"] == 1
    assert r["headline"] and r["top"]


def test_check_portfolio_empty_and_buy_fit_in_buy(src):
    analyzer = Analyzer(src)
    with pytest.raises(SourceError):
        analyzer.check_portfolio([], 35.0)
    r = analyzer.run("NVDA", "buy", None, 35.0, holdings=[{"ticker": "AAPL", "shares": 5, "avg_price": 100}])
    assert r["fit"] and r["fit"]["amount"] == 500 and r["fit"]["weight_before"] == 0
    assert "fit" not in analyzer.run("NVDA", "buy", None, 35.0)       # no portfolio given -> no note


# ---------------------------------------------------------------- เงื่อนไขเปลี่ยนใจ

def test_rule_states():
    from stocksense import rules as RL
    ctx = {"price": 100.0, "avg_price": 120.0, "weight_pct": 39.0, "surprise_pct": -5.0}
    ev = lambda kind, v=None: RL.evaluate(RL.make(kind, v), ctx)["state"]   # noqa: E731
    assert ev("price_below", 96) == "near" and ev("price_below", 90) == "ok" and ev("price_below", 105) == "hit"
    assert ev("loss_pct", 15) == "hit" and ev("loss_pct", 20) == "near" and ev("loss_pct", 40) == "ok"   # 100 vs 120 = -16.7%
    assert ev("weight_above", 40) == "near" and ev("weight_above", 39) == "hit" and ev("weight_above", 60) == "ok"
    assert ev("earnings_miss") == "hit"
    assert RL.evaluate(RL.make("earnings_miss"), {"price": 1}) ["state"] == "unknown"
    assert RL.evaluate({"kind": "loss_pct", "value": 10, "on": False}, ctx)["state"] == "off"
    assert RL.clean([{"kind": "nope"}, {"kind": "loss_pct", "value": "x"}, {"kind": "loss_pct", "value": 0},
                     {"kind": "earnings_miss", "value": None}]) == [{"kind": "earnings_miss", "value": None, "on": True}]
    d = RL.default_rules(140.0, 123.0)
    assert [r["kind"] for r in d] == ["price_below", "loss_pct", "weight_above", "earnings_miss"] and d[0]["value"] == 123.0
    assert [r["kind"] for r in RL.default_rules(100.0, None, False)] == ["price_below", "loss_pct", "weight_above"]


def test_rules_survive_editing_a_holding(tmp_path):
    from stocksense.portfolio import Portfolio
    from stocksense import rules as RL
    pf = Portfolio()
    pf.upsert({"ticker": "NVDA", "shares": 1, "avg_price": 100, "rules": RL.default_rules(100, 90)})
    pf.upsert({"ticker": "NVDA", "shares": 2, "avg_price": 100})                  # edited in the add/edit form
    assert len(Portfolio().get("NVDA")["rules"]) == 4 and Portfolio().get("NVDA")["shares"] == 2


def test_check_rules_and_sell_result(src):
    from stocksense import rules as RL
    a = Analyzer(src)
    hs = [{"ticker": "NVDA", "shares": 30, "avg_price": 90, "rules": [
              {"kind": "price_below", "value": 10000.0, "on": True}, {"kind": "earnings_miss", "value": None, "on": True},
              {"kind": "weight_above", "value": 10.0, "on": False}]},
          {"ticker": "AAPL", "shares": 1, "avg_price": 100}]
    out = a.check_rules(hs)
    assert list(out) == ["NVDA"]
    st = {r["rule"]["kind"]: r["state"] for r in out["NVDA"]}
    assert st == {"price_below": "hit", "earnings_miss": "ok", "weight_above": "off"}
    r = a.run("NVDA", "sell", hs[0], 35.0, holdings=hs)
    assert [x["state"] for x in r["rules"]] == ["hit", "ok", "off"] and r["suggested_rules"] == []
    r2 = a.run("AAPL", "sell", hs[1], 35.0, holdings=hs)
    assert r2["rules"] == [] and [x["kind"] for x in r2["suggested_rules"]][0] == "price_below"
    assert RL.summary(out["NVDA"]) == {"hit": 1, "near": 0}


def test_analyst_box_keeps_only_people_named_in_news(src):
    r = Analyzer(src).run("NVDA", "buy")
    box = r["analyst_box"]
    assert box["summary"]["word"] == "ซื้อ" and box["summary"]["buy"] > box["summary"]["sell"]
    names = [p["name"] for p in box["people"]]
    assert names == ["Jane Doe"], names              # the invented "Made Up Person" is dropped
    p = box["people"][0]
    assert p["firm"] == "Example Securities" and p["url"] and p["stance"] == "good" and p["date"]


def test_analyst_box_absent_for_etf(src):
    assert "analyst_box" not in Analyzer(src).run("VOO", "buy")


def test_verify_people_rules():
    news = [{"headline": "Alex Roe of Big Bank cuts target", "summary": "", "date": "2026-11-01", "url": "u", "source": "X"}]
    ok = {"i": 0, "name": "Alex Roe", "firm": "Big Bank", "role_th": "นักวิเคราะห์", "stance": "bad", "view_th": "ลดราคาเป้าหมาย"}
    v = Analyzer._verify_people
    assert len(v([ok], news)) == 1
    assert v([{**ok, "name": "Wedbush"}], news) == []                 # one word is not a person
    assert v([{**ok, "name": "Bob Smith"}], news) == []               # not in the text
    assert v([{**ok, "firm": "Other Firm"}], news)[0]["firm"] == ""   # firm not in text -> dropped
    assert v([{**ok, "view_th": ""}], news) == []
    assert v("junk", news) == [] and v(None, news) == []


def test_sec_user_agent_names_program_and_contact():
    from stocksense.net import UA_SEC
    assert UA_SEC.startswith("StockSense ") and "@" in UA_SEC

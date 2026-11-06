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

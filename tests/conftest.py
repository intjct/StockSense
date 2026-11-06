import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKSENSE_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path / "cfg"


@pytest.fixture
def src(tmp_path):
    from stocksense.fakedata import FakeInternet
    from stocksense.net import Cache, Http
    from stocksense.sources import Sources
    net = FakeInternet()
    s = Sources(Http(net), Cache(str(tmp_path / "cache")), gemini_key="g", finnhub_key="f")
    s.net = net
    return s

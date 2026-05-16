from __future__ import annotations

import zipfile

from data_fetchers.ecb_fx import build_ecb_download_url, download_ecb_file, parse_ecb_csv
from data_fetchers.stooq_prices import EQUITY_PRICE_BAR_COLUMNS, parse_stooq_csv, parse_stooq_zip
from data_fetchers.xetra_instruments import (
    discover_xetra_download_url,
    download_xetra_file,
    normalize_xetra_instruments,
    parse_xetra_csv,
)


def test_xetra_parser_skips_metadata_and_builds_security_listing_rows():
    raw = "\n".join(
        [
            "XETR",
            "2026-05-13",
            "ISIN;Instrument Mnemonic;Instrument Name;Currency;Instrument ID;Instrument Type",
            "DE000A1EWWW0;ADS;ADIDAS AG;EUR;123;Common Stock",
        ]
    )

    bronze, mic, last_update = parse_xetra_csv(raw, source_file="xetra.csv")
    securities, listings = normalize_xetra_instruments(bronze, mic, last_update)

    assert mic == "XETR"
    assert len(bronze) == 1
    assert securities.loc[0, "security_id"] == "DE000A1EWWW0"
    assert listings.loc[0, "provider_symbol"] == "ADS"
    assert listings.loc[0, "mic"] == "XETR"


def test_xetra_download_discovery_resolves_matching_relative_link():
    html = '<html><body><a href="/downloads/t7-xetr-allTradableInstruments.csv">T7 (Xetra) All tradable instruments</a></body></html>'

    url = discover_xetra_download_url(
        html,
        "https://www.cashmarket.deutsche-boerse.com/cash-en/trading/Tradable-Instruments-Xetra/Downloads/xetra-downloads",
        "T7 (Xetra) All tradable instruments",
    )

    assert url == "https://www.cashmarket.deutsche-boerse.com/downloads/t7-xetr-allTradableInstruments.csv"


def test_xetra_auto_download_saves_discovered_file(monkeypatch, tmp_path):
    class FakeResponse:
        def __init__(self, text="", content=b""):
            self.text = text
            self.content = content

        def raise_for_status(self):
            return None

    html = '<a href="t7-xetr-allTradableInstruments.csv">T7 (Xetra) All tradable instruments</a>'
    csv_bytes = b"XETR\n2026-05-13\nISIN;Instrument Mnemonic;Instrument Name\nDE000A1EWWW0;ADS;ADIDAS AG\n"

    def fake_get(url, timeout=30):
        if url.endswith("xetra-downloads"):
            return FakeResponse(text=html)
        return FakeResponse(content=csv_bytes)

    monkeypatch.setattr("data_fetchers.xetra_instruments.requests.get", fake_get)
    monkeypatch.setattr("data_fetchers.download_utils.requests.get", fake_get)
    config = {
        "sources": {
            "xetra": {
                "source_page": "https://example.com/xetra-downloads",
                "download_link_text": "T7 (Xetra) All tradable instruments",
                "raw_dir": str(tmp_path),
            }
        }
    }

    path, source_url = download_xetra_file(config)

    assert source_url == "https://example.com/t7-xetr-allTradableInstruments.csv"
    assert path.read_bytes() == csv_bytes


def test_stooq_csv_parser_normalizes_and_validates_ohlc():
    raw = "Date,Open,High,Low,Close,Volume\n2024-01-02,10,12,9,11,1000\n"

    frame = parse_stooq_csv(raw, provider_symbol="ads.de", currency="EUR")

    assert frame.loc[0, "provider"] == "stooq"
    assert frame.loc[0, "provider_symbol"] == "ads.de"
    assert frame.loc[0, "close"] == 11
    assert frame.loc[0, "adjustment_status"] == "unknown"


def test_stooq_ascii_parser_uses_ticker_and_yyyymmdd_dates():
    raw = (
        "<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>,<OPENINT>\n"
        "AADR.US,D,20100721,000000,23.1646,23.1646,22.7969,22.7969,45503.68,0\n"
    )

    frame = parse_stooq_csv(raw, provider_symbol="fallback.us")

    assert frame.loc[0, "provider_symbol"] == "aadr.us"
    assert str(frame.loc[0, "date"]) == "2010-07-21"
    assert frame.loc[0, "volume"] == 45503.68


def test_stooq_blank_csv_returns_empty_normalized_frame():
    frame = parse_stooq_csv("", provider_symbol="empty.us")

    assert frame.empty
    assert list(frame.columns) == EQUITY_PRICE_BAR_COLUMNS


def test_stooq_zip_parser_reads_csv_members(tmp_path):
    archive = tmp_path / "stooq.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("daily/ads.de.csv", "Date,Open,High,Low,Close,Volume\n2024-01-02,10,12,9,11,1000\n")

    frame = parse_stooq_zip(archive)

    assert len(frame) == 1
    assert frame.loc[0, "provider_symbol"] == "ads.de"


def test_stooq_zip_skips_empty_and_malformed_members(tmp_path):
    archive = tmp_path / "stooq.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("data/daily/us/nasdaq stocks/", "")
        zf.writestr("data/daily/us/nasdaq stocks/empty.us.txt", "")
        zf.writestr("data/daily/us/nasdaq stocks/bad.us.txt", "not,a,stooq,file\n1,2,3,4\n")
        zf.writestr(
            "data/daily/us/nasdaq stocks/aadr.us.txt",
            "<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>,<OPENINT>\n"
            "AADR.US,D,20100721,000000,23.1646,23.1646,22.7969,22.7969,45503.68,0\n",
        )

    frame = parse_stooq_zip(archive)

    assert len(frame) == 1
    assert frame.loc[0, "provider_symbol"] == "aadr.us"


def test_stooq_zip_all_empty_returns_empty_normalized_frame(tmp_path):
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("data/daily/us/nasdaq stocks/", "")
        zf.writestr("data/daily/us/nasdaq stocks/empty.us.txt", "")

    frame = parse_stooq_zip(archive)

    assert frame.empty
    assert list(frame.columns) == EQUITY_PRICE_BAR_COLUMNS


def test_ecb_parser_supports_long_csv_and_adds_eur_rate():
    raw = "TIME_PERIOD,CURRENCY,OBS_VALUE\n2024-01-02,USD,1.1\n"

    frame = parse_ecb_csv(raw)

    assert set(frame["currency"]) == {"USD", "EUR"}
    assert frame[frame["currency"] == "EUR"].iloc[0]["units_per_eur"] == 1.0


def test_ecb_url_construction_uses_config():
    config = {"sources": {"ecb_fx": {"api_base": "https://data-api.ecb.europa.eu/service/data", "series_key": "D..EUR.SP00.A"}}}

    assert build_ecb_download_url(config) == "https://data-api.ecb.europa.eu/service/data/EXR/D..EUR.SP00.A?format=csvdata"


def test_ecb_auto_download_saves_raw_response(monkeypatch, tmp_path):
    class FakeResponse:
        content = b"TIME_PERIOD,CURRENCY,OBS_VALUE\n2024-01-02,USD,1.1\n"

        def raise_for_status(self):
            return None

    monkeypatch.setattr("data_fetchers.download_utils.requests.get", lambda url, timeout=30: FakeResponse())
    config = {
        "sources": {
            "ecb_fx": {
                "api_base": "https://data-api.ecb.europa.eu/service/data",
                "series_key": "D..EUR.SP00.A",
                "raw_dir": str(tmp_path),
            }
        }
    }

    path, url = download_ecb_file(config)

    assert url.endswith("/EXR/D..EUR.SP00.A?format=csvdata")
    assert path.read_bytes() == FakeResponse.content

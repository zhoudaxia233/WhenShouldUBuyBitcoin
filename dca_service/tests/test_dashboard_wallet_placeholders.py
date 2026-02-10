from pathlib import Path


def test_dashboard_wallet_section_avoids_dash_placeholders():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert 'id="totalBtc">--<' not in html
    assert 'id="hotBalance" title="Binance (Hot)">Hot: --<' not in html
    assert 'id="coldBalance" title="Cold Storage">Cold: --<' not in html
    assert 'id="quoteBalance">--<' not in html
    assert 'id="progressPercent">--%<' not in html
    assert 'id="targetAmount">Target: -- BTC<' not in html

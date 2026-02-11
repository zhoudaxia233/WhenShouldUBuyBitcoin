from pathlib import Path


def test_dashboard_wallet_section_uses_dash_placeholders_and_cache_hydration():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert 'id="totalBtc">--<' in html
    assert 'id="hotBalance" title="Binance (Hot)">Hot: --<' in html
    assert 'id="coldBalance" title="Cold Storage">Cold: --<' in html
    assert 'id="quoteBalance">--<' in html
    assert 'id="progressPercent">--%<' in html
    assert 'id="targetAmount">Target: -- BTC<' in html

    # Ensure pre-hydration from cache exists to avoid placeholder flash on refresh.
    assert "Hydrate wallet and DCA preview from cache as early as possible" in html
    assert "parseCache('wallet_summary')" in html
    assert "const toFiniteNumber = (value)" in html

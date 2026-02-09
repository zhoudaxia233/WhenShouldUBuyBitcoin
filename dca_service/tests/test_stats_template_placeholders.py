from pathlib import Path


def test_stats_template_avoids_dash_placeholders_for_summary_cards():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "stats.html"
    html = template_path.read_text(encoding="utf-8")

    # Keep initial render neutral to avoid flashing "--" placeholders on refresh.
    assert 'id="portfolioValueUSD">--<' not in html
    assert 'id="totalBtcBalance">--<' not in html
    assert 'id="avgBuyPrice">--<' not in html
    assert 'id="pnlAmount">--<' not in html
    assert 'id="pnlPercent">--<' not in html
    assert 'id="totalFeesUSD">--<' not in html
    assert 'id="totalFeesBTC">--<' not in html
    assert 'id="transactionCount">--<' not in html
    assert 'id="totalBtc">--<' not in html

from pathlib import Path


def test_stats_template_uses_cache_before_network_fetch():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "stats.html"
    html = template_path.read_text(encoding="utf-8")

    # Ensure cache-first rendering path exists for each stats loader.
    assert "if (cached) updatePercentileUI(cached.data);" in html
    assert "if (cached) updateDistributionUI(cached.data);" in html
    assert "if (cached) updateFeesUI(cached.data);" in html
    assert "if (cachedWallet) {\n                    updateWalletBalanceUI(cachedWallet.data);" in html
    assert "if (cached) renderChart(cached.data);" in html

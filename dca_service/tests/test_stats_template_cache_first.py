from pathlib import Path


def test_stats_template_uses_cache_before_network_fetch_for_non_distribution_stats():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "stats.html"
    html = template_path.read_text(encoding="utf-8")

    # Wealth percentile/distribution must not render browser cache as live data.
    assert "if (cached) updatePercentileUI(cached.data);" not in html
    assert "if (cached) updateDistributionUI(cached.data);" not in html

    # Less-sensitive stats still use cache-first rendering for perceived speed.
    assert "if (cached) updateFeesUI(cached.data);" in html
    assert "if (cachedWallet) {\n                    updateWalletBalanceUI(cachedWallet.data);" in html
    assert "if (cached) renderChart(cached.data);" in html

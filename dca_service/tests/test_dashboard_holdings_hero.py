"""The home page opens with your bitcoin: BTC held, target progress and the reserve chart."""

from pathlib import Path
import re

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "dca_service" / "templates"


def _html(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _hero(html: str) -> str:
    start = html.index('<section id="reserveChart"')
    return html[start : html.index("</section>", start)]


def test_holdings_hero_comes_first_on_home():
    html = _html("index.html")
    body = html[html.index("<body") :]
    hero = body.index('<section id="reserveChart" class="dashboard-panel reserve-panel holdings-hero"')
    assert hero < body.index("DCA Strategy") < body.index("Recent buys")
    assert 'class="wallet-card-grid"' not in html
    assert 'id="progressRing"' not in html


def test_holdings_hero_leads_with_btc_and_keeps_target_progress():
    hero = _hero(_html("index.html"))
    assert "data-reserve-readout" in hero
    assert '<canvas class="reserve-canvas" tabindex="0" role="img"' in hero
    assert 'id="progressBar"' in hero
    assert 'id="progressPercent">--%<' in hero
    assert 'id="totalBtc">--<' in hero
    assert 'id="targetAmount">--<' in hero
    assert 'id="targetEta"' in hero
    ranges = re.findall(r'data-range="(\w+)" aria-pressed="(true|false)"', hero)
    assert ranges == [("3m", "false"), ("6m", "false"), ("1y", "true"), ("all", "false")]


def test_holdings_hero_shows_where_the_btc_sits_and_cash_to_spend():
    hero = _hero(_html("index.html"))
    assert 'id="hotBalance">--<' in hero
    assert 'id="coldBalance">--<' in hero
    assert 'id="quoteBalance">--<' in hero
    assert 'data-bs-target="#setColdWalletModal"' in hero
    assert 'id="walletError"' in hero


def test_home_loads_the_chart_cache_first_from_the_pnl_api():
    html = _html("index.html")
    assert "<script src=\"{{ asset_url('reserve_chart.js') }}\"></script>" in html
    loader = html[html.index("async function loadReserveChart()") :]
    loader = loader[: loader.index("\n        }\n") ]
    assert "loadFromCache('stats_pnl')" in loader
    assert "fetch('/api/stats/pnl')" in loader
    assert "saveToCache('stats_pnl', data);" in loader
    assert "loadReserveChart()" in html[html.index("async function initializeDashboard") :]


def test_target_eta_uses_the_recent_buying_pace():
    html = _html("index.html")
    assert "window.ReserveChart.targetEta(" in html
    assert "function updateTargetEta()" in html


def test_analytics_no_longer_repeats_the_chart():
    stats = _html("stats.html")
    assert 'id="reserveChart"' not in stats
    assert "reserve_chart.js" not in stats


def test_holdings_hero_uses_wallet_holdings_only_when_the_wallet_reports_some():
    html = _html("index.html")
    assert "currentBtc: Number.isFinite(wallet.total_btc) && wallet.total_btc > 0 ? wallet.total_btc : undefined" in html
    assert "currentPrice: wallet.current_price" in html


def test_new_buys_and_refresh_reload_the_chart():
    html = _html("index.html")
    sse = html[html.index("eventSource.addEventListener('transaction_created'") :]
    assert "loadReserveChart();" in sse[: sse.index("});")]
    assert html.count("loadReserveChart()") >= 4


def test_reserve_chart_scrolls_vertically_on_touch_and_has_a_mobile_height():
    css = (Path(__file__).resolve().parents[1] / "src" / "dca_service" / "static" / "app.css").read_text(encoding="utf-8")
    canvas_rule = css[css.index(".reserve-canvas {") :]
    assert "touch-action: pan-y;" in canvas_rule[: canvas_rule.index("}")]
    mobile = css[css.index(".reserve-canvas {", css.index("@media (max-width: 767.98px)", css.index("/* Reserve chart")) ) - 200 :]
    assert "height: 280px;" in mobile[:400]


def test_home_shows_recent_buys_and_expands_to_all_on_request():
    html = _html("index.html")
    section = html[html.index('<section id="buys"') :]
    section = section[: section.index("</section>")]
    assert "Recent buys" in section
    assert 'id="showAllBuysBtn"' in section
    assert 'aria-controls="buys"' in section
    assert "const RECENT_BUYS = 5;" in html
    assert "let showAllBuys = location.hash === '#buys';" in html
    assert "window.addEventListener('hashchange'" in html


def test_analytics_is_called_insights():
    stats = _html("stats.html")
    assert '<h1 class="visually-hidden">Insights</h1>' in stats

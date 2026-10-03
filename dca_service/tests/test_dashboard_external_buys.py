"""Buys from other exchanges: added by hand on the home page, counted on Insights."""

from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "dca_service" / "templates"


def _html(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def test_recent_buys_offers_add_buy_next_to_resync():
    html = _html("index.html")
    buys = html[html.index('<section id="buys"') :]
    buys = buys[: buys.index("</section>")]
    assert buys.index('id="addBuyBtn"') < buys.index('id="clearSimulatedBtn"')
    assert "Buys you added from other exchanges are kept." in buys


def test_add_buy_form_previews_before_saving():
    html = _html("index.html")
    assert 'id="externalBuyModal"' in html
    assert "No order is placed." in html
    assert "fetch('/api/external-buys/preview'" in html
    assert 'id="externalBuyAdjust" checked' in html


def test_exchange_balances_sit_between_cold_storage_and_cash():
    html = _html("index.html")
    hero = html[html.index('<dl class="holdings-wallets">') :]
    hero = hero[: hero.index("</dl>")]
    assert hero.index('id="coldBalance"') < hero.index('id="quoteBalanceRow"')
    assert "list.insertBefore(row, anchor)" in html
    assert 'id="coldWalletVenueHint"' in html


def test_cost_basis_includes_other_exchanges():
    assert "wallet.avg_buy_price || wallet.hot_wallet_avg_price" in _html("index.html")
    stats = _html("stats.html")
    assert "walletData.avg_buy_price || walletData.hot_wallet_avg_price" in stats
    assert 'id="transactionCountSubtext"' in stats

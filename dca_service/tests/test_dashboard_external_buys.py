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


def _external_row_template(html: str) -> str:
    start = html.index("function externalBuyRowHtml(tx)")
    return html[start : html.index("function externalBuyCardHtml", start)]


def test_id_column_shows_the_exchange_trade_id_not_an_edit_button():
    row = _external_row_template(_html("index.html"))
    cells = row[row.index("return `") :].split("</td>")
    assert "tx.venue_trade_id" in cells[0]
    assert "externalBuyEditButton" not in cells[0]
    assert "externalBuyEditButton(tx)" in cells[-2]
    html = _html("index.html")
    helper = html[html.index("function externalBuyEditButton(tx)") :]
    helper = helper[: helper.index("\n        }")]
    assert "bi-pencil" in helper and 'title="Edit this buy"' in helper


def test_buys_table_has_a_trailing_edit_column():
    html = _html("index.html")
    head = html[html.index('<section id="buys"') :]
    head = head[head.index("<thead") : head.index("</thead>")]
    assert head.rstrip().endswith('<th class="buys-edit-col"><span class="visually-hidden">Edit</span></th>\n                            </tr>')

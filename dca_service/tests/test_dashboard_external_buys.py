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


def test_exchange_balances_are_listed_with_the_other_bitcoin_holdings():
    """Other exchanges hold bitcoin, so their rows join the goal's holdings list
    after cold storage. Cash to spend lives in the budget column instead."""
    html = _html("index.html")
    holdings = html[html.index('<dl class="ledger-list holdings-wallets">') :]
    holdings = holdings[: holdings.index("</dl>")]
    assert 'id="coldBalance"' in holdings
    assert 'id="quoteBalanceRow"' not in holdings
    render = html[html.index("function renderVenueBalances(balances)") :]
    render = render[: render.index("const hint = ")]
    assert "list.appendChild(row)" in render
    assert "insertBefore" not in render
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
    cells = head[: head.index("</tr>")].rstrip().splitlines()
    assert cells[-1].strip() == '<th class="buys-edit-col"><span class="visually-hidden">Edit</span></th>'


def _venue_dialog(html: str) -> str:
    start = html.index('<div class="modal fade" id="setVenueBalanceModal"')
    return html[start : html.index("<!-- Add or edit a buy", start)]


def test_exchange_dialog_offers_the_move_before_the_correction():
    """Withdrawing to the hardware wallet is the usual reason to open it, so the
    move is the primary action and typing a new balance is the secondary one."""
    dialog = _venue_dialog(_html("index.html"))
    assert 'id="venueBalanceChoice"' in dialog
    assert dialog.index('id="venueMoveStart"') < dialog.index('id="venueCorrectStart"')
    assert "Move to cold storage" in dialog
    assert "Correct this balance" in dialog
    assert 'id="setVenueBalanceForm"' in dialog
    assert 'id="venueMoveForm"' in dialog
    assert "Record move" in dialog
    assert 'id="venueMoveLeftInput"' in dialog and 'value="0"' in dialog


def test_move_is_one_server_call_and_then_reads_the_key_right_away():
    html = _html("index.html")
    handler = html[html.index("getElementById('venueMoveForm').addEventListener('submit'") :]
    handler = handler[: handler.index("async function readApiError")]
    assert "/move-to-cold`" in handler
    assert "method: 'POST'" in handler
    assert "'/api/wallet/cold-balance'" not in handler
    assert "venueMoveToast(" in handler
    assert "syncColdWalletFromKeys({ force: true })" in handler
    sync = html[html.index("async function syncColdWalletFromKeys(") :]
    sync = sync[: sync.index("document.getElementById('coldWalletKeysInput')")]
    # Only the daily interval is skipped; the other guards stay in front of it.
    assert sync.index("coldSyncRunning") < sync.index("coldSyncDue(")
    assert sync.index("shouldAutoSyncCold(") < sync.index("coldSyncDue(")


def test_emptied_exchange_row_is_muted_with_the_day_it_was_emptied():
    html = _html("index.html")
    render = html[html.index("function renderVenueBalances(balances)") :]
    render = render[: render.index("function renderEtpHoldings")]
    assert "venueEmptySince(" in render
    assert 'class="holdings-sync-age"' in render
    assert "is-empty" in render
    assert "coldVenueHintText(" in render
    css = (TEMPLATES.parent / "static" / "app.css").read_text(encoding="utf-8")
    rule = css[css.index(".ledger-list > div.is-empty dd") :]
    rule = rule[: rule.index("}")]
    assert "var(--" in rule and "#" not in rule

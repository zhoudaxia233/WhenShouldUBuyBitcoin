"""IB1T holding: added from the Add buy dialog, listed with the other bitcoin holdings."""

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "dca_service" / "templates"
ISHARES_PAGE = "https://www.ishares.com/de/privatanleger/de/produkte/337088/ishares-bitcoin-etp"


def _html(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _modal(html: str) -> str:
    start = html.index('id="externalBuyModal"')
    return html[start : html.index("<!-- Extra buy strategy-check modal -->", start)]


def _tag(html: str, element_id: str) -> str:
    match = re.search(r"<input[^>]*\bid=\"" + element_id + r"\"[^>]*>", html)
    assert match, element_id
    return match.group(0)


def test_add_buy_dialog_offers_the_ib1t_holding_next_to_the_exchanges():
    modal = _modal(_html("index.html"))
    select = modal[modal.index('id="externalBuyVenue"') : modal.index("</select>")]
    assert select.index('value="Kraken Pro"') < select.index('value="__etp:IB1T"')
    assert '<option value="__etp:IB1T">iShares Bitcoin ETP (IB1T)</option>' in select


def test_ib1t_form_asks_only_shares_average_price_and_fee():
    modal = _modal(_html("index.html"))
    # Fractional shares from savings plans, so any number of decimals
    assert 'step="any"' in _tag(modal, "etpShares")
    assert 'step="any"' in _tag(modal, "etpAvgPrice")
    assert 'step="any"' in _tag(modal, "etpFee")
    assert "data-etp-only" in modal and "data-buy-only" in modal
    # Where to look up the fee: the issuer's own page, not a copy of it
    assert ISHARES_PAGE in modal


def test_ib1t_holding_is_listed_with_the_other_bitcoin_holdings():
    html = _html("index.html")
    render = html[html.index("function renderEtpHoldings(holdings)") :]
    render = render[: render.index("function openVenueBalanceModal")]
    assert "list.appendChild(row)" in render
    assert "data-etp=" in render
    assert "renderEtpHoldings(data.etp_holdings || [])" in html


def test_ib1t_holding_saves_and_previews_through_its_own_endpoint():
    html = _html("index.html")
    assert "fetch(`/api/etp-holdings/${product}`, {" in html
    assert "fetch(`/api/etp-holdings/${product}/preview`, {" in html


def test_insights_cost_basis_says_it_includes_the_holding():
    stats = _html("stats.html")
    assert "walletData.etp_holdings" in stats

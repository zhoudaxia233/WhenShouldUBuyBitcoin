"""Decimal fields take a comma as well as a point, and dialog forms scroll on a phone.

An iPhone set to a German region has only a comma on its decimal keypad, and
WebKit's type="number" inputs drop that comma unless the phone's language is
German: "0,5" arrived as 5 (2026-11-16, adding the IB1T holding). So a field
that takes decimals is type="text" inputmode="decimal" and is read through
DecimalInput.parse (static/decimal_input.js), and a form that relied on the
browser's checks of a number input's min, max and step asks
DecimalInput.reportProblem before it saves.

The same day the Add buy dialog could not be scrolled on the phone, so its Save
button stayed below the screen: a <form> between .modal-content and the body
takes away the height limit that lets a scrollable dialog's body scroll.
"""

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "dca_service" / "templates"
PAGES = sorted(TEMPLATES.glob("*.html"))

TIERS = ("p10", "p25", "p50", "p75", "p90", "p100", "r045", "r050", "r060", "r070", "r080", "r090", "r100", "r999")
DECIMAL_FIELDS = {
    "index.html": [
        "coldWalletInput",
        "venueBalanceInput",
        "etpShares",
        "etpAvgPrice",
        "etpFee",
        "externalBuyAmount",
        "externalBuyBtc",
        "externalBuyFee",
        "addPositionUsdcInput",
    ],
    "strategy.html": [
        "total_budget_usd",
        "target_btc_amount",
        "fixed_dca_stop_price_usd",
        *[f"ahr999_multiplier_{tier}" for tier in TIERS],
        "dynamic_min_multiplier",
        "dynamic_max_multiplier",
        "dynamic_a_low",
        "dynamic_a_high",
        "dynamic_gamma",
    ],
}


def _html(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _inputs(html: str) -> list[str]:
    return re.findall(r"<input\b[^>]*>", html)


def _attr(tag: str, name: str):
    match = re.search(r"\s" + name + r'="([^"]*)"', tag)
    return match.group(1) if match else None


def _tag(html: str, element_id: str) -> str:
    tags = [tag for tag in _inputs(html) if _attr(tag, "id") == element_id]
    assert len(tags) == 1, element_id
    return tags[0]


def _decimal_ids(html: str) -> list[str]:
    return [_attr(tag, "id") for tag in _inputs(html) if _attr(tag, "inputmode") == "decimal" and _attr(tag, "id")]


def _assert_decimal_field(page: str, tag: str) -> None:
    assert _attr(tag, "type") == "text", f"{page}: {tag}"
    assert _attr(tag, "inputmode") == "decimal", f"{page}: {tag}"
    assert _attr(tag, "autocomplete") == "off", f"{page}: {tag}"


def test_every_field_that_takes_decimals_is_a_text_field_with_the_decimal_keypad():
    for page, ids in DECIMAL_FIELDS.items():
        html = _html(page)
        for element_id in ids:
            _assert_decimal_field(page, _tag(html, element_id))
    # The rows for a later IB1T fee are written by the script
    index = _html("index.html")
    fee_row = next(tag for tag in _inputs(index) if 'aria-label="New yearly fee in percent"' in tag)
    _assert_decimal_field("index.html", fee_row)


def test_no_number_input_is_left_for_typing_decimals():
    for page in PAGES:
        for tag in _inputs(page.read_text(encoding="utf-8")):
            if _attr(tag, "type") != "number" or re.search(r"\sreadonly\b", tag):
                continue
            step = _attr(tag, "step")
            # Without a step, or with a whole one, a number input takes whole numbers only
            assert step is None or re.fullmatch(r"\d+", step), f"{page.name}: {tag}"


def test_decimal_fields_are_read_through_decimal_input():
    for page in PAGES:
        html = page.read_text(encoding="utf-8")
        ids = _decimal_ids(html)
        if not ids:
            continue
        assert "asset_url('decimal_input.js')" in html, page.name
        for element_id in ids:
            for reader in ("parseFloat(", "Number(", "toExtraBuyFiniteNumber("):
                assert f"{reader}document.getElementById('{element_id}')" not in html, (page.name, element_id, reader)
    index = _html("index.html")
    fee_rows = index[index.index("function etpFeeChanges()") :]
    fee_rows = fee_rows[: fee_rows.index("function etpPayload()")]
    assert "DecimalInput.parse(fee.value)" in fee_rows


def _submit_handler(html: str, opening: str) -> str:
    start = html.index(opening)
    return html[start : start + 400]


def test_forms_the_browser_used_to_check_check_their_decimal_fields():
    # min, max and step stay on the fields; number inputs had the browser check them
    index = _html("index.html")
    for opening in (
        "getElementById('setColdWalletForm').addEventListener('submit'",
        "getElementById('setVenueBalanceForm').addEventListener('submit'",
        "addPositionForm.addEventListener('submit'",
    ):
        assert "DecimalInput.reportProblem(" in _submit_handler(index, opening), opening
    strategy = _html("strategy.html")
    assert "DecimalInput.reportProblem(" in _submit_handler(
        strategy, "getElementById('strategyForm').addEventListener('submit'"
    )


def test_an_unreadable_fee_is_not_saved_as_no_fee():
    index = _html("index.html")
    payload = index[index.index("function externalBuyPayload()") :]
    payload = payload[: payload.index("function updateExternalBuyAdjustLabel()")]
    assert "parseFloat(" not in payload
    assert "|| 0" not in payload


def test_a_form_in_a_scrollable_dialog_is_its_modal_content():
    found = 0
    for page in PAGES:
        html = page.read_text(encoding="utf-8")
        dialogs = re.finditer(
            r'<div class="modal-dialog\b[^"]*\bmodal-dialog-scrollable\b[^"]*">\s*(<[^>]*>)\s*(<[^>]*>)', html
        )
        for dialog in dialogs:
            content, child = dialog.groups()
            found += 1
            assert 'class="modal-content' in content, (page.name, content)
            assert not child.startswith("<form"), (page.name, content, child)
    assert found >= 2
    assert '<form class="modal-content" id="externalBuyForm" novalidate>' in _html("index.html")

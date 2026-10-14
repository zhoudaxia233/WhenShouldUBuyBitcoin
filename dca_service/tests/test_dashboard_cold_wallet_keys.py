import re
from pathlib import Path


def _dashboard_html() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    return template_path.read_text(encoding="utf-8")


def test_dashboard_loads_the_public_key_tracker_from_this_site():
    html = _dashboard_html()

    assert "{{ asset_url('cold_wallet_watch.js') }}" in html
    assert 'id="coldWalletKeysForm"' in html


def test_public_keys_are_never_sent_to_the_server():
    html = _dashboard_html()

    # The key field has no name, so no form submit can carry it.
    textarea = re.search(r"<textarea[^>]*id=\"coldWalletKeysInput\"[^>]*>", html).group(0)
    assert "name=" not in textarea

    # The only request to this server posts the summed balance and nothing else.
    block = html[html.index("// Cold storage from extended public keys"):]
    block = block[: block.index("// Buys and balances on other exchanges")]
    assert block.count("fetch(") == 1
    assert "body: JSON.stringify({ balance: balance })" in block
    assert "console.log" not in block


def test_saved_keys_are_never_written_back_into_the_page():
    html = _dashboard_html()
    block = html[html.index("// Cold storage from extended public keys"):]
    block = block[: block.index("// Buys and balances on other exchanges")]

    # Saved keys are shown masked only; the textarea is for pasting new ones.
    assert "maskKey" in block
    assert "coldWalletKeysInput').value = keys" not in block
    assert "coldWalletKeysInput').value = readColdKeys" not in block


def test_every_cdn_asset_is_pinned_and_integrity_checked():
    # Wallet public keys sit in this site's localStorage, which any script on
    # any page of the site can read. A CDN file may run here only if its exact
    # version and hash are fixed, so a changed or hijacked file is refused.
    templates = Path(__file__).resolve().parents[1] / "src" / "dca_service" / "templates"
    tags = []
    for path in sorted(templates.glob("*.html")):
        html = path.read_text(encoding="utf-8")
        for tag in re.findall(r"<(?:script|link)\b[^>]*(?:src|href)=\"https?://[^\"]*\"[^>]*>", html):
            tags.append((path.name, tag))

    assert tags
    for name, tag in tags:
        url = re.search(r"(?:src|href)=\"([^\"]+)\"", tag).group(1)
        assert re.search(r"@\d+\.\d+\.\d+/", url), f"{name}: unpinned {url}"
        assert 'integrity="sha384-' in tag, f"{name}: no integrity on {url}"
        assert 'crossorigin="anonymous"' in tag, f"{name}: no crossorigin on {url}"


def _key_form(html: str) -> str:
    start = html.index('id="coldWalletKeysForm"')
    return html[start: html.index("</form>", start)]


def test_key_help_is_a_toggle():
    form = _key_form(_dashboard_html())

    toggle = re.search(r"<button[^>]*data-bs-target=\"#coldWalletKeysHelp\"[^>]*>", form).group(0)
    assert 'data-bs-toggle="collapse"' in toggle
    assert 'aria-controls="coldWalletKeysHelp"' in toggle
    assert 'type="button"' in toggle


def test_key_help_links_to_vendor_guides_instead_of_copying_their_menus():
    # Wallet apps redesign their menus without notice, so click-by-click
    # steps go stale. Link to each vendor's own guide and keep only notes
    # that do not depend on their UI.
    form = _key_form(_dashboard_html())
    help_block = form[form.index('id="coldWalletKeysHelp"'):]

    links = re.findall(r"<a\b[^>]*>", help_block)
    hrefs = [re.search(r'href="([^"]+)"', a).group(1) for a in links]
    assert any(h.startswith("https://support.ledger.com/") for h in hrefs)
    assert any(h.startswith("https://trezor.io/") for h in hrefs)
    for a in links:
        assert 'target="_blank"' in a
        assert 'rel="noopener noreferrer"' in a

    assert "<ol" not in help_block
    for menu_label in ["Edit account", "Advanced logs", "Show public key", "wrench", "sidebar"]:
        assert menu_label not in help_block, menu_label
    for note in ["xpub", "zpub", "84'", "one key per line", "balance"]:
        assert note in help_block, note


def test_key_notes_are_listed_one_per_line():
    form = _key_form(_dashboard_html())
    notes = form[: form.index('id="coldWalletKeysHelp"')]

    items = re.findall(r"<li\b[^>]*>(.*?)</li>", notes, re.S)
    for note in ["bc1q", "stays in this browser", "recovery phrase"]:
        assert any(note in item for item in items), note


def test_sync_result_check_stands_out():
    # Comparing the synced total with the wallet app is the user's proof that
    # the right key was pasted. Wallet apps do not list an account's first
    # address (Ledger's history shows the sender's address on receipts), so
    # the check is on the balance, and it must not read as fine print.
    html = _dashboard_html()
    box = re.search(r"<div[^>]*id=\"coldWalletKeysCheck\"[^>]*>", html).group(0)
    assert "alert" in box
    assert "small" not in box
    result = html[html.index('id="coldWalletKeysCheck"'):]
    result = result[: result.index("</form>")]
    assert "<strong>" in result
    assert "balance in your wallet app" in result
    assert "first address in your wallet app" not in html


def _cold_block() -> str:
    html = _dashboard_html()
    block = html[html.index("// Cold storage from extended public keys"):]
    return block[: block.index("// Buys and balances on other exchanges")]


def test_background_sync_runs_at_most_once_a_day():
    # mempool.space does not publish its limits and may ban clients that
    # exceed them repeatedly; a cold wallet balance rarely changes, and
    # "Sync now" covers the moment after a transfer.
    block = _cold_block()
    assert "const COLD_SYNC_INTERVAL_MS = 24 * 60 * 60 * 1000;" in block


def test_failed_background_sync_is_not_retried_on_every_page_load():
    # The attempt time is stored, not only kept in memory, so reloading the
    # page while mempool.space refuses requests does not hit it again.
    block = _cold_block()
    sync = block[block.index("async function syncColdWalletFromKeys"):]
    sync = sync[: sync.index("\n        }\n")]
    assert "readColdAttempt()" in sync
    assert sync.index("writeColdAttempt(") < sync.index("scanAndPostColdBalance(")


def test_one_sync_button_whose_label_never_changes():
    # A label that changes after the first sync reads as a new next step.
    html = _dashboard_html()
    button = re.search(r"<button[^>]*id=\"coldWalletKeysSubmit\"[^>]*>([^<]*)<", html)
    assert button.group(1) == "Sync now"
    block = _cold_block()
    for label in ["Track and sync", "Rescan now"]:
        assert label not in html, label
    assert "submit.textContent = 'Sync now'" in block


def test_finished_sync_shows_only_the_result():
    # After a sync the only thing left to do is compare the balance, so the
    # setup controls go away; the one action that may still be needed (the
    # key turned out to be the wrong account) sits inside the result.
    html = _dashboard_html()
    form = _key_form(html)
    setup_start = form.index('id="coldWalletKeysSetup"')
    for inner in ['id="coldWalletKeysInput"', 'id="coldWalletKeysSubmit"', 'id="coldWalletKeysHelp"']:
        assert form.index(inner) > setup_start, inner

    result = form[form.index('id="coldWalletKeysCheck"'):]
    result = result[: result.index("</div>\n                        </div>")]
    assert 'id="coldWalletKeysRemove"' in result
    assert "close this window" in result

    block = _cold_block()
    shown = block[block.index("function showColdSyncResult"):]
    shown = shown[: shown.index("\n        }\n")]
    assert "coldWalletKeysSetup').classList.add('d-none')" in shown

    reset = block[block.index("function resetColdKeysView"):]
    reset = reset[: reset.index("\n        }\n")]
    assert "coldWalletKeysSetup').classList.remove('d-none')" in reset
    closed = block[block.index("'hidden.bs.modal'"):]
    assert "resetColdKeysView()" in closed[: closed.index("});")]


def test_tracking_state_replaces_the_manual_form_with_a_status_line():
    html = _dashboard_html()
    form = _key_form(html)
    status = form[form.index('id="coldWalletKeysStatus"'):]
    clear = re.search(r"<button[^>]*id=\"coldWalletKeysClear\"[^>]*>", status).group(0)
    assert "btn-link" in clear

    block = _cold_block()
    render = block[block.index("function renderColdKeysState"):block.index("async function checkColdKeysInput")]
    assert "setColdWalletForm').classList.toggle('d-none', tracking)" in render
    assert "coldWalletKeysStatus').classList.toggle('d-none', !tracking" in render


def test_result_takes_focus_when_the_sync_button_hides():
    # Hiding the focused button drops focus out of the dialog, and Bootstrap
    # then ignores Escape.
    html = _dashboard_html()
    box = re.search(r"<div[^>]*id=\"coldWalletKeysCheck\"[^>]*>", html).group(0)
    assert 'tabindex="-1"' in box
    block = _cold_block()
    shown = block[block.index("function showColdSyncResult"):]
    assert "result.focus()" in shown[: shown.index("\n        }\n")]

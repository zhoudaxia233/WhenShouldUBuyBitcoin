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


def test_public_keys_are_saved_on_the_server_and_held_only_in_memory():
    html = _dashboard_html()

    # The key field has no name, so no form submit can carry it.
    textarea = re.search(r"<textarea[^>]*id=\"coldWalletKeysInput\"[^>]*>", html).group(0)
    assert "name=" not in textarea

    # This server is the only place keys go: one read, one write and the
    # balance post. Nothing is written to the console.
    block = html[html.index("// Cold storage from extended public keys"):]
    block = block[: block.index("// Buys and balances on other exchanges")]
    assert block.count("fetch(") == 3
    assert "fetch('/api/wallet/cold-keys')" in block
    assert "fetch('/api/wallet/cold-keys', {" in block
    assert "body: JSON.stringify({ balance: balance, source: 'public_key' })" in block
    assert "console.log" not in block
    assert "localStorage.setItem(COLD_KEYS_STORAGE" not in block


def test_keys_saved_in_a_browser_move_to_the_server_once():
    # A browser from before keeps its key in localStorage. It goes up only when
    # the server has none, and leaves this browser only once the server has it.
    block = _cold_block()
    load = block[block.index("async function fetchColdKeys"):]
    load = load[: load.index("\n        }\n")]
    assert "if (!coldKeys.length && legacy.length && !(await writeColdKeys(legacy))) return;" in load
    assert load.index("writeColdKeys(legacy)") < load.index("localStorage.removeItem(COLD_KEYS_STORAGE)")


def test_a_failed_read_of_the_keys_can_be_tried_again():
    block = _cold_block()
    load = block[block.index("function loadColdKeys"):]
    load = load[: load.index("\n        }\n")]
    assert "coldKeysLoading = null;" in load


def test_background_sync_waits_for_the_keys_from_the_server():
    block = _cold_block()
    sync = block[block.index("async function syncColdWalletFromKeys"):]
    assert sync.index("await loadColdKeys();") < sync.index("readColdKeys()")


def test_a_sync_from_any_device_counts_toward_the_daily_limit():
    # Every device holds the key now; without this each would scan once a day.
    block = _cold_block()
    sync = block[block.index("async function syncColdWalletFromKeys"):]
    sync = sync[: sync.index("\n        }\n")]
    assert "coldSyncedAt(window.__coldWalletSource, window.__coldWalletUpdatedAt, null) || 0" in sync


def test_saved_keys_are_never_written_back_into_the_page():
    html = _dashboard_html()
    block = html[html.index("// Cold storage from extended public keys"):]
    block = block[: block.index("// Buys and balances on other exchanges")]

    # Saved keys are shown masked only; the textarea is for pasting new ones.
    assert "maskKey" in block
    assert "coldWalletKeysInput').value = keys" not in block
    assert "coldWalletKeysInput').value = readColdKeys" not in block


def test_every_cdn_asset_is_pinned_and_integrity_checked():
    # Wallet public keys reach this page, and any script on it can read them.
    # A CDN file may run here only if its exact version and hash are fixed, so
    # a changed or hijacked file is refused.
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
    for note in ["bc1q", "saved encrypted on this server", "recovery phrase"]:
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


def test_background_sync_shows_its_progress_on_the_sync_button():
    # A tap on Sync now during a background scan is ignored, which on a phone
    # reads as a broken button unless the button says what is going on.
    block = _cold_block()
    sync = block[block.index("async function syncColdWalletFromKeys"):]
    sync = sync[: sync.index("\n        }\n")]
    assert "button.disabled = true;" in sync
    assert "checked => { button.textContent = `Checking address ${checked}…`; }" in sync
    assert sync.index("button.disabled = false;") > sync.index("finally {")


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
    # The manual form shows only in the setup view, never while a key is tracked.
    assert "setColdWalletForm').classList.toggle('d-none', view !== 'setup')" in render
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


def test_stop_tracking_is_disabled_while_a_scan_runs():
    # Removing the key mid-scan would still post the total and show "Saved"
    # for a key that is gone. Both the dialog's scan and the background one
    # count as running.
    block = _cold_block()
    render = block[block.index("function renderColdKeysState"):block.index("async function checkColdKeysInput")]
    assert "coldWalletKeysClear').disabled = coldSyncRunning" in render

    stop = block[block.index("function stopColdTracking"):]
    stop = stop[: stop.index("\n        }\n")]
    assert "if (coldSyncRunning) return;" in stop

    for start in ["async function syncColdWalletFromKeys", "getElementById('coldWalletKeysForm').addEventListener('submit'"]:
        body = block[block.index(start):]
        body = body[: body.index("try {")]
        assert "coldSyncRunning = true;\n" in body
        assert body.index("coldSyncRunning = true;") < body.index("renderColdKeysState();"), start


def test_removing_the_key_says_what_it_does():
    # "Stop tracking" read like cancelling the running scan; the action
    # deletes the saved key from the server and ends the daily sync.
    html = _dashboard_html()
    assert "Stop tracking" not in html
    clear = re.search(r"<button[^>]*id=\"coldWalletKeysClear\"[^>]*>([^<]*)<", html).group(1)
    remove = re.search(r"<button[^>]*id=\"coldWalletKeysRemove\"[^>]*>([^<]*)<", html).group(1)
    assert clear == "Remove key"
    assert remove == "Remove this key"
    stop = _cold_block()[_cold_block().index("function stopColdTracking"):]
    assert "Removed the key from the server" in stop[: stop.index("\n        }\n")]


def test_dashboard_shows_how_old_the_cold_balance_is():
    html = _dashboard_html()
    row = html[html.index("<dt>Cold storage"):]
    row = row[: row.index("</div>")]
    age = re.search(r"<small[^>]*id=\"coldSyncAge\"[^>]*>", row).group(0)
    assert "d-none" in age

    block = _cold_block()
    render = block[block.index("function renderColdKeysState"):block.index("async function checkColdKeysInput")]
    assert "renderColdSyncAge();" in render
    age = block[block.index("function renderColdSyncAge"):]
    assert "formatColdSyncAge(" in age[: age.index("\n        }\n")]
    # The label is relative, so it is refreshed while the page stays open;
    # only the label, so a running scan's progress text is left alone.
    assert "setInterval(renderColdSyncAge, 60 * 1000)" in block
    assert "setInterval(renderColdKeysState" not in block


def test_manual_balance_is_posted_as_manual():
    html = _dashboard_html()
    manual = html[html.index("document.getElementById('setColdWalletForm').addEventListener('submit'"):]
    manual = manual[: manual.index("// Cold storage from extended public keys")]
    assert "body: JSON.stringify({ balance: balance, source: 'manual' })" in manual


def test_every_device_gets_the_same_dialog():
    # The key is on the server, so no device needs its own copy pasted in.
    html = _dashboard_html()
    for gone in ["coldWalletRemote", "coldWalletBack", "coldWalletSwitchNote", "cold-remote"]:
        assert gone not in html, gone
    assert "cold-remote" not in (
        Path(__file__).resolve().parents[1] / "src" / "dca_service" / "static" / "app.css"
    ).read_text(encoding="utf-8")


def test_the_daily_update_promise_says_what_it_needs():
    # No server job scans the wallet: a device has to open the page.
    html = _dashboard_html()
    assert "It updates by itself once a day." not in html
    assert "once a day when any of your devices opens this page" in html


def test_background_sync_stops_once_the_balance_is_entered_by_hand_elsewhere():
    block = _cold_block()
    sync = block[block.index("async function syncColdWalletFromKeys"):]
    sync = sync[: sync.index("\n        }\n")]
    assert "shouldAutoSyncCold(window.__coldWalletSource)" in sync
    assert sync.index("shouldAutoSyncCold(") < sync.index("writeColdAttempt(")

    render = block[block.index("function renderColdKeysState"):block.index("async function checkColdKeysInput")]
    assert "coldModalView(" in render
    assert "entered by hand" in render


def test_wallet_summary_tells_the_dialog_where_the_balance_came_from():
    html = _dashboard_html()
    update = html[html.index("function updateWalletUI(data, strategy)"):]
    update = update[: update.index("\n        }\n")]
    assert "window.__coldWalletSource = data.cold_wallet_source || null;" in update
    assert "window.__coldWalletUpdatedAt = data.cold_wallet_updated_at || null;" in update
    assert "renderColdKeysState();" in update


def test_tracking_status_and_dashboard_agree_on_the_last_sync():
    # Another device may have synced since this one did.
    block = _cold_block()
    render = block[block.index("function renderColdKeysState"):block.index("async function checkColdKeysInput")]
    assert "coldSyncedAt(window.__coldWalletSource, window.__coldWalletUpdatedAt, sync)" in render
    assert "new Date(sync.at)" not in render

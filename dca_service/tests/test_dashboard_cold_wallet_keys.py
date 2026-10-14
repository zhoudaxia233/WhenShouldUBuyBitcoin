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

from pathlib import Path


def test_dashboard_preview_section_keeps_placeholders_and_has_cache_hydration():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    # Preserve default placeholders for first load without cache.
    assert 'id="previewAhr">--<' in html
    assert 'id="previewPrice">--<' in html
    assert 'id="previewBand">--<' in html
    assert 'id="previewAction">--<' in html
    assert 'id="remainingBudget"' in html and ">--<" in html

    # Ensure pre-hydration from cached preview exists.
    assert "parseCache('dca_preview')" in html
    assert "const previewAhrEl = document.getElementById('previewAhr');" in html
    assert "if (previewPriceEl && priceValue !== null)" in html
    assert "if (previewActionEl && typeof preview.can_execute === 'boolean')" in html

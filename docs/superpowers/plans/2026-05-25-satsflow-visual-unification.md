# SatsFlow Visual Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every server-rendered DCA service page share the existing dashboard SatsFlow visual system.

**Architecture:** Extract dashboard visual primitives into one shared static stylesheet and reusable Jinja fragments. Keep page-specific markup and scripts in each existing template, but replace legacy per-page chrome/card/form styles with shared SatsFlow classes. Tests assert that every affected template loads the shared stylesheet and exposes the expected shared brand, nav, theme, and page shell primitives.

**Tech Stack:** FastAPI/Jinja templates, Bootstrap 5, Bootstrap Icons, static CSS, pytest template regression tests, Vitest public-doc tests where relevant, Browser/Playwright rendered QA.

---

### Task 1: Add Red Tests For Shared Design System

**Files:**
- Modify: `dca_service/tests/test_original_style_regression.py`
- Modify: `dca_service/tests/test_dashboard_ui_polish.py`
- Test: `dca_service/tests/test_original_style_regression.py`
- Test: `dca_service/tests/test_dashboard_ui_polish.py`

- [ ] **Step 1: Replace the old no-shared-CSS and purple-login tests**

In `dca_service/tests/test_original_style_regression.py`, replace:

```python
def test_shared_design_override_is_not_loaded():
    for template_name in TEMPLATE_NAMES:
        html = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
        assert 'href="/static/app.css"' not in html


def test_shared_design_override_file_is_removed():
    assert not (STATIC_DIR / "app.css").exists()


def test_login_uses_original_gradient_card_style():
    html = (TEMPLATE_DIR / "login.html").read_text(encoding="utf-8")
    assert "linear-gradient(135deg, #667eea 0%, #764ba2 100%)" in html
    assert "box-shadow:" in html
```

with:

```python
def test_shared_satsflow_design_system_is_loaded_by_all_templates():
    for template_name in TEMPLATE_NAMES:
        html = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
        assert 'href="/static/app.css"' in html, template_name


def test_shared_satsflow_design_system_file_exists():
    css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    assert "--dashboard-accent: #ff8a00;" in css
    assert "--dashboard-accent-strong: #f97316;" in css
    assert ".app-shell" in css
    assert ".brand-lockup" in css
    assert ".dashboard-panel" in css
    assert ".login-shell" in css


def test_login_uses_satsflow_brand_style_not_legacy_purple_gradient():
    html = (TEMPLATE_DIR / "login.html").read_text(encoding="utf-8")
    assert "linear-gradient(135deg, #667eea 0%, #764ba2 100%)" not in html
    assert 'class="login-shell"' in html
    assert 'class="brand-mark"' in html
    assert 'class="login-card dashboard-panel"' in html
```

- [ ] **Step 2: Add cross-page brand/nav tests**

In `dca_service/tests/test_dashboard_ui_polish.py`, append:

```python
def test_authenticated_templates_share_satsflow_header_and_nav():
    template_dir = TEMPLATE_PATH.parent
    expected_active = {
        "index.html": 'href="/" class="btn dashboard-nav-btn active"',
        "stats.html": 'href="/stats" class="btn dashboard-nav-btn active"',
        "strategy.html": 'href="/strategy" class="btn dashboard-nav-btn active"',
        "binance_settings.html": 'href="/settings/binance" class="btn dashboard-nav-btn active"',
        "admin_data_sources.html": 'href="/admin/data-sources" class="btn dashboard-nav-btn active nav-accent admin-diagnostics-link"',
    }

    for template_name, active_nav in expected_active.items():
        html = (template_dir / template_name).read_text(encoding="utf-8")
        assert 'class="app-shell' in html, template_name
        assert 'class="brand-lockup"' in html, template_name
        assert 'class="brand-mark"' in html, template_name
        assert 'class="brand-title">{{ project_name }}</span>' in html, template_name
        assert 'class="dashboard-nav"' in html, template_name
        assert active_nav in html, template_name


def test_shared_version_badge_class_is_used_across_templates():
    template_dir = TEMPLATE_PATH.parent
    for template_name in [
        "admin_data_sources.html",
        "binance_settings.html",
        "index.html",
        "login.html",
        "stats.html",
        "strategy.html",
    ]:
        html = (template_dir / template_name).read_text(encoding="utf-8")
        assert 'class="version-badge"' in html, template_name
```

- [ ] **Step 3: Run red tests**

Run:

```bash
python -m pytest dca_service/tests/test_original_style_regression.py dca_service/tests/test_dashboard_ui_polish.py -q
```

Expected: FAIL because `/static/app.css` does not exist yet, login still uses the legacy gradient, and non-dashboard templates do not use shared SatsFlow header/nav primitives.

### Task 2: Extract Shared SatsFlow CSS

**Files:**
- Create: `dca_service/src/dca_service/static/app.css`
- Modify: `dca_service/src/dca_service/templates/index.html`
- Test: `dca_service/tests/test_original_style_regression.py`
- Test: `dca_service/tests/test_dashboard_ui_polish.py`

- [ ] **Step 1: Create the shared stylesheet**

Create `dca_service/src/dca_service/static/app.css` with the dashboard tokens and shared primitives:

```css
:root {
    --dashboard-bg: #fffaf4;
    --dashboard-card-bg: rgba(255, 255, 255, 0.94);
    --dashboard-card-bg-solid: #ffffff;
    --dashboard-text: #15171c;
    --dashboard-muted: #686f7c;
    --dashboard-border: #f0dfc9;
    --dashboard-border-strong: #e7c7a2;
    --dashboard-accent: #ff8a00;
    --dashboard-accent-strong: #f97316;
    --dashboard-accent-soft: rgba(255, 138, 0, 0.12);
    --dashboard-accent-softer: rgba(255, 138, 0, 0.06);
    --dashboard-success: #16a34a;
    --dashboard-danger: #dc2626;
    --dashboard-shadow: 0 18px 55px rgba(130, 84, 33, 0.09);
    --dashboard-ring-track: #ece7df;
}
html[data-bs-theme="dark"],
html[data-theme="dark"] {
    --dashboard-bg: #12100d;
    --dashboard-card-bg: #181512;
    --dashboard-card-bg-solid: #181512;
    --dashboard-text: #f4efe8;
    --dashboard-muted: #b8aca0;
    --dashboard-border: #352a1f;
    --dashboard-border-strong: #5a3d22;
    --dashboard-accent-soft: rgba(255, 138, 0, 0.16);
    --dashboard-accent-softer: rgba(255, 138, 0, 0.08);
    --dashboard-shadow: 0 24px 70px rgba(0, 0, 0, 0.36);
    --dashboard-ring-track: #2f2923;
}
body {
    min-height: 100vh;
    padding: 24px 0 32px;
    background:
        radial-gradient(circle at 14% 0%, var(--dashboard-accent-softer), transparent 28%),
        var(--dashboard-bg);
    color: var(--dashboard-text);
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    transition: background-color 0.2s ease, color 0.2s ease;
}
.app-shell {
    max-width: 1220px;
}
.app-shell-narrow {
    max-width: 1000px;
}
.app-shell-settings {
    max-width: 900px;
}
.dashboard-header {
    margin-bottom: 24px;
}
.brand-lockup {
    display: inline-flex;
    align-items: center;
    flex: 0 0 auto;
    gap: 14px;
    color: var(--dashboard-text);
    text-decoration: none;
}
.brand-mark {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--dashboard-accent);
    color: #fff;
    font-size: 1.55rem;
    font-weight: 800;
    line-height: 1;
    box-shadow: 0 10px 26px rgba(255, 138, 0, 0.28);
}
.brand-title {
    font-size: clamp(1.45rem, 2.2vw, 2rem);
    font-weight: 750;
    letter-spacing: -0.02em;
    white-space: nowrap;
}
.nav-actions {
    align-items: center;
}
.dashboard-nav {
    gap: 0.55rem;
    flex-wrap: nowrap !important;
}
.nav-actions > .btn,
.nav-actions > .dropdown > .btn {
    min-height: 42px;
    display: inline-flex;
    align-items: center;
}
.nav-actions > .btn .bi,
.nav-actions > .dropdown > .btn .bi {
    margin-right: 0.45rem;
}
.dashboard-nav-btn {
    border-color: transparent;
    border-radius: 10px;
    color: var(--dashboard-muted);
    background: transparent;
    font-size: 0.94rem;
    font-weight: 650;
    padding: 0.55rem 0.9rem;
    transition: all 0.18s ease;
}
.dashboard-nav-btn:hover,
.dashboard-nav-btn:focus {
    border-color: var(--dashboard-border);
    background: var(--dashboard-card-bg);
    color: var(--dashboard-text);
}
.dashboard-nav-btn.active,
.dashboard-nav-btn.nav-accent {
    border-color: var(--dashboard-border-strong);
    background: var(--dashboard-accent-softer);
    color: var(--dashboard-accent-strong);
}
.dashboard-nav-btn.active {
    box-shadow: inset 0 0 0 1px rgba(255, 138, 0, 0.08);
}
.theme-toggle-btn {
    width: 42px;
    height: 42px;
    padding: 0;
    border: 1px solid var(--dashboard-border);
    border-radius: 50%;
    background: var(--dashboard-card-bg);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--dashboard-muted);
    transition: all 0.2s ease;
}
.theme-toggle-btn:hover {
    background: var(--dashboard-accent-softer);
    color: var(--dashboard-accent-strong);
    border-color: var(--dashboard-border-strong);
}
.theme-toggle-btn .theme-icon {
    width: 21px;
    height: 21px;
    stroke: currentColor;
    fill: none;
    stroke-width: 2.2;
    stroke-linecap: round;
    stroke-linejoin: round;
}
.user-chip {
    min-height: 42px;
    padding: 0 0 0 1rem;
    flex: 0 0 auto;
}
.logout-btn {
    border-color: var(--dashboard-border-strong);
    border-radius: 10px;
    color: var(--dashboard-accent-strong);
    background: var(--dashboard-accent-softer);
    font-weight: 650;
}
.logout-btn:hover {
    background: var(--dashboard-accent);
    border-color: var(--dashboard-accent);
    color: #fff;
}
.dashboard-panel,
.metric-card,
.refresh-panel,
.card {
    border: 1px solid var(--dashboard-border);
    border-radius: 10px;
    background: var(--dashboard-card-bg);
    box-shadow: var(--dashboard-shadow);
    color: var(--dashboard-text);
}
.dashboard-panel,
.card {
    overflow: hidden;
}
.dashboard-panel-header,
.card-header.dashboard-panel-header,
.card-header,
.card-footer.dashboard-panel-footer,
.card-footer {
    border-color: var(--dashboard-border);
    background: color-mix(in srgb, var(--dashboard-card-bg-solid) 88%, transparent) !important;
    padding: 1.4rem 1.75rem;
}
.dashboard-panel-title {
    font-size: 1.22rem;
    font-weight: 760;
    letter-spacing: -0.01em;
    color: var(--dashboard-text);
}
.refresh-panel {
    padding: 0.9rem 1rem;
}
.btn {
    font-weight: 650;
}
.btn-primary,
.btn-success,
.btn-warning {
    border-color: var(--dashboard-accent);
    background: var(--dashboard-accent);
    color: #fff;
}
.btn-primary:hover,
.btn-success:hover,
.btn-warning:hover {
    border-color: var(--dashboard-accent-strong);
    background: var(--dashboard-accent-strong);
    color: #fff;
}
.btn-outline-primary,
.btn-outline-info,
.btn-outline-success,
.btn-outline-secondary,
.btn-outline-warning,
.btn-outline-danger {
    border-color: var(--dashboard-border-strong);
    color: var(--dashboard-accent-strong);
    background: var(--dashboard-accent-softer);
}
.btn-outline-primary:hover,
.btn-outline-info:hover,
.btn-outline-success:hover,
.btn-outline-secondary:hover,
.btn-outline-warning:hover,
.btn-outline-danger:hover {
    border-color: var(--dashboard-accent);
    background: var(--dashboard-accent);
    color: #fff;
}
.form-control,
.form-select,
.tier-input {
    border-color: var(--dashboard-border);
    border-radius: 8px;
    background-color: var(--dashboard-card-bg-solid);
    color: var(--dashboard-text);
}
.form-control:focus,
.form-select:focus,
.tier-input:focus {
    border-color: var(--dashboard-accent);
    box-shadow: 0 0 0 0.22rem rgba(255, 138, 0, 0.16);
}
.text-muted {
    color: var(--dashboard-muted) !important;
}
.table {
    --bs-table-color: var(--dashboard-text);
    --bs-table-bg: transparent;
    --bs-table-border-color: var(--dashboard-border);
}
.table-light {
    --bs-table-bg: var(--dashboard-accent-softer);
    --bs-table-color: var(--dashboard-text);
    --bs-table-border-color: var(--dashboard-border);
}
.bg-light,
.bg-body-tertiary {
    background-color: var(--dashboard-accent-softer) !important;
}
.dropdown-menu {
    min-width: 200px;
    border-color: var(--dashboard-border);
    background: var(--dashboard-card-bg-solid);
    box-shadow: var(--dashboard-shadow);
}
.dropdown-item {
    color: var(--dashboard-text);
}
.dropdown-item i {
    width: 20px;
    margin-right: 8px;
}
.version-badge {
    position: fixed;
    right: 10px;
    bottom: 8px;
    z-index: 9999;
    font-size: 12px;
    color: var(--dashboard-muted);
    background: var(--dashboard-card-bg);
    border: 1px solid var(--dashboard-border);
    border-radius: 999px;
    padding: 3px 10px;
}
.login-shell {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
}
.login-card {
    width: 100%;
    max-width: 420px;
    padding: 34px;
}
.login-header {
    text-align: center;
    margin-bottom: 28px;
}
.login-header .brand-lockup {
    justify-content: center;
    margin-bottom: 14px;
}
.login-header h1 {
    color: var(--dashboard-text);
    font-size: 1.7rem;
    font-weight: 760;
    margin-bottom: 8px;
}
.login-header p {
    color: var(--dashboard-muted);
    font-size: 0.95rem;
    margin-bottom: 0;
}
.error-message {
    background: rgba(220, 38, 38, 0.1);
    border: 1px solid rgba(220, 38, 38, 0.25);
    color: var(--dashboard-danger);
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 20px;
    font-size: 14px;
}
.security-note {
    margin-top: 20px;
    padding-top: 20px;
    border-top: 1px solid var(--dashboard-border);
    text-align: center;
    color: var(--dashboard-muted);
    font-size: 12px;
}
@media (max-width: 768px) {
    body {
        padding: 18px 0 28px;
    }
    .dashboard-header .brand-lockup {
        width: 100%;
        justify-content: center;
    }
    .dashboard-nav {
        width: 100%;
        overflow-x: auto;
        padding-bottom: 0.15rem;
    }
    .nav-actions {
        width: 100%;
    }
    .nav-actions > .btn,
    .nav-actions > .dropdown > .btn {
        min-height: 40px;
    }
    .nav-actions > .btn .bi,
    .nav-actions > .dropdown > .btn .bi {
        margin-right: 0;
    }
    .btn .btn-text {
        display: none;
    }
    .theme-toggle-btn {
        width: 44px;
        height: 44px;
    }
    .dashboard-panel-header,
    .card-header.dashboard-panel-header,
    .card-header,
    .card-footer.dashboard-panel-footer,
    .card-footer {
        padding: 1.1rem 1.2rem;
    }
    .login-shell {
        align-items: flex-start;
        padding: 72px 20px 24px;
    }
    .login-card {
        padding: 28px 22px;
    }
}
```

- [ ] **Step 2: Load shared CSS in dashboard**

In `dca_service/src/dca_service/templates/index.html`, add:

```html
<link rel="stylesheet" href="/static/app.css">
```

after the existing vendor CSS links.

- [ ] **Step 3: Remove duplicated dashboard CSS only after shared CSS covers it**

In `index.html`, remove duplicated definitions for shared tokens and chrome only when the same selectors exist in `app.css`. Keep dashboard-specific classes such as wallet grids, progress rings, strategy cards, modals, and data-specific layouts in the template.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python -m pytest dca_service/tests/test_original_style_regression.py dca_service/tests/test_dashboard_ui_polish.py -q
```

Expected: Some tests may still fail because other templates do not yet load or use the shared system.

### Task 3: Unify Login Page

**Files:**
- Modify: `dca_service/src/dca_service/templates/login.html`
- Test: `dca_service/tests/test_original_style_regression.py`
- Test: `dca_service/tests/test_dashboard_ui_polish.py`
- Test: `dca_service/tests/test_auth.py`

- [ ] **Step 1: Replace standalone login chrome**

In `login.html`:

- Keep the initial theme script, but change `data-theme` to `data-bs-theme` for consistency.
- Add `<link rel="stylesheet" href="/static/app.css">`.
- Remove the large standalone `<style>` block except any login-only fallback that remains necessary.
- Change `<body>` content to use `login-shell` and `login-card dashboard-panel`.
- Preserve the existing form fields, CSRF hidden input, `required` attributes, error block, security note, theme button ID, version badge, and theme icon script.

The key structure should be:

```html
<body>
    <button id="themeToggleBtn" type="button" class="theme-toggle-btn" aria-label="Toggle theme" title="Toggle theme"></button>
    <main class="login-shell">
        <section class="login-card dashboard-panel">
            <div class="login-header">
                <div class="brand-lockup">
                    <span class="brand-mark">₿</span>
                    <span class="brand-title">{{ project_name }}</span>
                </div>
                <h1>{{ project_name }}</h1>
                <p>Sign in to your account</p>
            </div>
            ...
        </section>
    </main>
    <div class="version-badge">...</div>
</body>
```

- [ ] **Step 2: Run red/green login tests**

Run:

```bash
python -m pytest dca_service/tests/test_original_style_regression.py::test_login_uses_satsflow_brand_style_not_legacy_purple_gradient dca_service/tests/test_auth.py::test_login_page_renders -q
```

Expected after implementation: PASS.

### Task 4: Add Reusable Authenticated Header Fragment

**Files:**
- Create: `dca_service/src/dca_service/templates/_shared_header.html`
- Modify: `dca_service/src/dca_service/templates/index.html`
- Modify: `dca_service/src/dca_service/templates/admin_data_sources.html`
- Modify: `dca_service/src/dca_service/templates/stats.html`
- Modify: `dca_service/src/dca_service/templates/strategy.html`
- Modify: `dca_service/src/dca_service/templates/binance_settings.html`
- Test: `dca_service/tests/test_dashboard_ui_polish.py`
- Test: `dca_service/tests/test_admin_data_sources.py`

- [ ] **Step 1: Create shared header fragment**

Create `_shared_header.html`:

```html
<header class="dashboard-header">
    <div class="d-flex flex-column flex-lg-row justify-content-between align-items-center gap-3">
        <a href="/" class="brand-lockup">
            <span class="brand-mark">₿</span>
            <span class="brand-title">{{ project_name }}</span>
        </a>
        <div class="d-flex flex-column flex-lg-row align-items-center gap-3 w-100 w-lg-auto">
            <nav class="nav-actions dashboard-nav d-flex flex-wrap flex-md-nowrap justify-content-center gap-2" aria-label="Primary navigation">
                <a href="/" class="btn dashboard-nav-btn{% if active_page == 'dashboard' %} active{% endif %}"><i class="bi bi-house-fill"></i> <span class="btn-text">Dashboard</span></a>
                <a href="/strategy" class="btn dashboard-nav-btn{% if active_page == 'strategy' %} active{% endif %}"><i class="bi bi-sliders"></i> <span class="btn-text">Strategy</span></a>
                <a href="/stats" class="btn dashboard-nav-btn{% if active_page == 'stats' %} active{% endif %}"><i class="bi bi-graph-up"></i> <span class="btn-text">Stats</span></a>
                <a href="/settings/binance" class="btn dashboard-nav-btn{% if active_page == 'settings' %} active{% endif %}"><i class="bi bi-gear-fill"></i> <span class="btn-text">Settings</span></a>
                {% if user and user.is_admin %}
                <a href="/admin/data-sources" class="btn dashboard-nav-btn nav-accent admin-diagnostics-link{% if active_page == 'admin' %} active{% endif %}"><i class="bi bi-database-check"></i> <span class="btn-text">Diagnostics</span></a>
                {% endif %}
                <button id="themeToggleBtn" type="button" class="btn text-nowrap theme-toggle-btn" aria-label="Toggle theme" title="Toggle theme"></button>
            </nav>
            {% if user %}
            <div class="user-chip d-flex align-items-center gap-2 border-start ps-lg-3 mt-2 mt-lg-0 pt-2 pt-lg-0 border-top border-top-lg-0">
                <span class="text-muted small">{{ user.email }}</span>
                <form method="POST" action="/api/auth/logout" class="d-inline">
                    <button type="submit" class="btn btn-sm logout-btn">Logout</button>
                </form>
            </div>
            {% endif %}
        </div>
    </div>
</header>
```

- [ ] **Step 2: Include the fragment in authenticated templates**

At the top of each authenticated page body, set `active_page` and include the fragment:

```html
{% set active_page = 'dashboard' %}
{% include "_shared_header.html" %}
```

Use these values:

- `index.html`: `dashboard`
- `stats.html`: `stats`
- `strategy.html`: `strategy`
- `binance_settings.html`: `settings`
- `admin_data_sources.html`: `admin`

- [ ] **Step 3: Run focused tests**

Run:

```bash
python -m pytest dca_service/tests/test_dashboard_ui_polish.py::test_authenticated_templates_share_satsflow_header_and_nav dca_service/tests/test_admin_data_sources.py::test_admin_data_sources_page_has_theme_toggle dca_service/tests/test_admin_data_sources.py::test_admin_data_sources_page_uses_bootstrap_theme_variables -q
```

Expected after implementation: PASS.

### Task 5: Unify Authenticated Page Shells And Panels

**Files:**
- Modify: `dca_service/src/dca_service/templates/admin_data_sources.html`
- Modify: `dca_service/src/dca_service/templates/stats.html`
- Modify: `dca_service/src/dca_service/templates/strategy.html`
- Modify: `dca_service/src/dca_service/templates/binance_settings.html`
- Test: `dca_service/tests/test_original_style_regression.py`
- Test: `dca_service/tests/test_dashboard_ui_polish.py`
- Test: `dca_service/tests/test_stats_template_regression.py`
- Test: `dca_service/tests/test_strategy_template_summary_settings.py`
- Test: `dca_service/tests/test_admin_data_sources.py`

- [ ] **Step 1: Load shared CSS in every authenticated template**

Add this after vendor CSS in each page:

```html
<link rel="stylesheet" href="/static/app.css">
```

- [ ] **Step 2: Use shared shells**

Use:

```html
<div class="container app-shell">
```

for `admin_data_sources.html` and `stats.html`.

Use:

```html
<div class="container app-shell app-shell-narrow">
```

for `strategy.html`.

Use:

```html
<div class="container app-shell app-shell-settings">
```

for `binance_settings.html`.

- [ ] **Step 3: Convert page cards to dashboard panels without changing IDs**

For page sections that currently use:

```html
<section class="card shadow-sm mb-4">
```

change to:

```html
<section class="card dashboard-panel mb-4">
```

For important headers that currently use `card-header bg-white`, `card-header bg-body`, or `card-header`, add `dashboard-panel-header` while keeping existing heading text and IDs.

- [ ] **Step 4: Keep page-specific layout CSS but remove conflicting body/header/card colors**

In each template's `<style>` block, remove or override page-specific body background colors, old blue/purple gradients, default card borders, and old theme-toggle dimensions. Keep page-specific CSS for charts, grids, tier rows, diagnostics grids, log tails, responsive form behavior, and JavaScript-dependent IDs/classes.

- [ ] **Step 5: Run template regression tests**

Run:

```bash
python -m pytest dca_service/tests/test_original_style_regression.py dca_service/tests/test_dashboard_ui_polish.py dca_service/tests/test_admin_data_sources.py dca_service/tests/test_stats_template_regression.py dca_service/tests/test_strategy_template_summary_settings.py -q
```

Expected after implementation: PASS.

### Task 6: Run Broad Automated Verification

**Files:**
- No production files should be edited in this task.
- Test: Python and JavaScript test suites.

- [ ] **Step 1: Run DCA service tests**

Run:

```bash
python -m pytest dca_service/tests -q
```

Expected: PASS. If unrelated existing failures appear, record exact failing tests and rerun the focused visual subset to confirm this change's scope.

- [ ] **Step 2: Run public JS tests**

Run:

```bash
npm test -- --runInBand
```

If Vitest rejects `--runInBand`, run:

```bash
npm test
```

Expected: PASS.

### Task 7: Browser Verification

**Files:**
- No production files should be edited unless browser QA finds issues.

- [ ] **Step 1: Start the app**

Run the project's DCA service locally using the existing Python environment. If the repository has no documented wrapper command available in the current environment, use the FastAPI app import path:

```bash
python -m uvicorn dca_service.main:app --app-dir dca_service/src --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: Verify routes in desktop and mobile browser viewports**

Check:

- `http://127.0.0.1:8000/api/auth/login`
- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/admin/data-sources`
- `http://127.0.0.1:8000/stats`
- `http://127.0.0.1:8000/strategy`
- `http://127.0.0.1:8000/settings/binance`

Use the Browser plugin first. If Browser is unavailable or fails, use Playwright and record the fallback reason.

For each route, verify:

- Page has meaningful content and no framework error overlay.
- No relevant console errors.
- Header/nav/brand/theme toggle/panels match the dashboard SatsFlow system.
- Mobile width has no clipped primary content or overlapping controls.
- At least one relevant interaction still changes visible UI state.

### Task 8: Four Required Subagent Reviews

**Files:**
- No production files should be edited unless a reviewer finds an issue.

- [ ] **Step 1: Dispatch four reviewers**

Spawn four subagents with these roles:

- Normal returning user reviewer.
- Workflow usability user reviewer.
- UX/UI consistency reviewer.
- UX/UI polish and accessibility reviewer.

- [ ] **Step 2: Wait for all reviewers**

Do not final-answer until all four reviewers report pass or actionable changes.

- [ ] **Step 3: Address review findings**

If any reviewer requests changes, make the smallest fix, rerun the relevant automated and browser checks, then rerun or re-check the affected review gate.

### Task 9: Final Verification And Handoff

**Files:**
- No production files should be edited in this task.

- [ ] **Step 1: Run final focused verification**

Run:

```bash
python -m pytest dca_service/tests/test_original_style_regression.py dca_service/tests/test_dashboard_ui_polish.py dca_service/tests/test_admin_data_sources.py -q
```

Expected: PASS.

- [ ] **Step 2: Inspect git diff**

Run:

```bash
git diff --check
git status --short
git diff --stat
```

Expected: no whitespace errors; changed files are limited to the spec/plan, shared CSS, templates, and focused tests.

- [ ] **Step 3: Report**

Final response should include:

- What changed.
- Automated tests run.
- Browser verification routes and viewports.
- Subagent review results.
- Any remaining risk or skipped verification.

# Transaction Export And DCA Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace behavior-analysis CSV with order-level purchase export, add audited DCA misclassification repair, and align the trading-style status text.

**Architecture:** Keep purchase export helpers in `dca_service.api.stats_api` because the existing endpoint lives there. Add a focused repair service in `dca_service.services.transaction_repair` and expose it through admin-only API routes in `dca_service.api.routes`. Keep UI changes scoped to `stats.html`.

**Tech Stack:** FastAPI, SQLModel, pytest, Bootstrap template, CSV stdlib.

---

## File Structure

- Modify `dca_service/src/dca_service/api/stats_api.py`: replace trading-style CSV builder with order-level purchase CSV builder while preserving the existing route URL.
- Create `dca_service/src/dca_service/services/transaction_repair.py`: pure repair analysis/apply logic, grouped by `binance_order_id`.
- Modify `dca_service/src/dca_service/api/routes.py`: add admin-only DCA repair endpoint.
- Modify `dca_service/src/dca_service/templates/stats.html`: move status text into the header title block and update CSV filename in client download.
- Modify `dca_service/tests/test_stats.py`: TDD coverage for purchase CSV rows and split-fill merge.
- Create `dca_service/tests/test_transaction_repair.py`: TDD coverage for dry-run/apply repair and negative cases.
- Modify `dca_service/tests/test_stats_template_regression.py`: TDD coverage for header/status layout and download filename.

### Task 1: Purchase CSV Export

**Files:**
- Modify: `dca_service/tests/test_stats.py`
- Modify: `dca_service/src/dca_service/api/stats_api.py`
- Modify: `dca_service/src/dca_service/templates/stats.html`

- [ ] **Step 1: Write failing purchase CSV tests**

Add tests that call `/api/stats/trading-style.csv`, assert filename `bitcoin-purchases.csv`, assert no behavior-analysis fields, and assert one row per order. The default export should stay lean:
`purchase_datetime,purchase_type,usd_spent,btc_bought,avg_price_usd,fee_usd`.

- [ ] **Step 2: Run tests to verify RED**

Run: `poetry run pytest dca_service/tests/test_stats.py::test_purchase_csv_export_contains_order_level_purchase_rows dca_service/tests/test_stats.py::test_purchase_csv_export_merges_split_fills -q`

Expected: FAIL because the current CSV still includes behavior-analysis fields and filename `trading-style-analysis.csv`.

- [ ] **Step 3: Implement order-level CSV helpers**

Replace behavior CSV fields with the lean purchase fields, group by `binance_order_id`, compute summed USD/BTC/fees, weighted price, and trigger classification.

- [ ] **Step 4: Run purchase CSV tests to verify GREEN**

Run: `poetry run pytest dca_service/tests/test_stats.py::test_purchase_csv_export_contains_order_level_purchase_rows dca_service/tests/test_stats.py::test_purchase_csv_export_merges_split_fills -q`

Expected: PASS.

### Task 2: DCA Misclassification Repair

**Files:**
- Create: `dca_service/src/dca_service/services/transaction_repair.py`
- Create: `dca_service/tests/test_transaction_repair.py`
- Modify: `dca_service/src/dca_service/api/routes.py`

- [ ] **Step 1: Write failing repair service tests**

Add tests for:
- dry-run identifies repeated daily exact-minute imported manual orders as repair candidates without changing DB rows.
- apply changes only candidate orders to `source="DCA"` and `is_manual=false`.
- random/manual orders are not reclassified.

- [ ] **Step 2: Run tests to verify RED**

Run: `poetry run pytest dca_service/tests/test_transaction_repair.py -q`

Expected: FAIL because `dca_service.services.transaction_repair` does not exist.

- [ ] **Step 3: Implement repair service and admin endpoint**

Implement conservative grouping thresholds from the design:
- same minute bucket,
- at least 5 orders,
- at least 4 dates,
- median daily gap 0.8-1.3 days or daily gap ratio at least 0.60,
- amount coefficient of variation at most 0.35.

Expose `POST /api/transactions/repair-dca-classification?dry_run=true|false` with `get_current_admin_user`.

- [ ] **Step 4: Run repair tests to verify GREEN**

Run: `poetry run pytest dca_service/tests/test_transaction_repair.py -q`

Expected: PASS.

### Task 3: UI Header Alignment

**Files:**
- Modify: `dca_service/tests/test_stats_template_regression.py`
- Modify: `dca_service/src/dca_service/templates/stats.html`

- [ ] **Step 1: Write failing template regression tests**

Assert `tradingStyleStatus` is inside a `.trading-style-heading` block next to `tradingStyleTitle`, and assert client download name is `bitcoin-purchases.csv`.

- [ ] **Step 2: Run tests to verify RED**

Run: `poetry run pytest dca_service/tests/test_stats_template_regression.py::test_trading_style_status_is_aligned_under_header_title dca_service/tests/test_stats_template_regression.py::test_trading_style_csv_export_ui_is_enabled -q`

Expected: FAIL because the status element is currently in `.card-body` and client filename is `trading-style-analysis.csv`.

- [ ] **Step 3: Implement template/CSS changes**

Move status text into the left header block under the title. Keep controls on the right and stack cleanly on mobile.

- [ ] **Step 4: Run template tests to verify GREEN**

Run: `poetry run pytest dca_service/tests/test_stats_template_regression.py::test_trading_style_status_is_aligned_under_header_title dca_service/tests/test_stats_template_regression.py::test_trading_style_csv_export_ui_is_enabled -q`

Expected: PASS.

### Task 4: Integrated Verification And Browser Check

**Files:**
- No new files expected.

- [ ] **Step 1: Run focused backend/template tests**

Run: `poetry run pytest dca_service/tests/test_stats.py dca_service/tests/test_transaction_repair.py dca_service/tests/test_stats_template_regression.py -q`

Expected: PASS.

- [ ] **Step 2: Run route in browser**

Start the local server, open `/stats`, verify the trading-style status is aligned under the title on desktop and mobile widths, and verify there is no visible overlap.

- [ ] **Step 3: Dispatch three subagent reviewers**

Request three independent checks:
- backend/API and repair safety,
- CSV/export correctness,
- frontend/layout regression.

- [ ] **Step 4: Address reviewer findings and re-run verification**

Fix any Critical or Important findings. Re-run the focused tests and browser check.

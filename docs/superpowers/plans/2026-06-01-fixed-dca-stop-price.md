# Fixed DCA Stop Price Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clarify Fixed DCA copy and add an optional stop-buying BTC price for Fixed DCA.

**Architecture:** Add one nullable strategy field and keep the existing `fixed_dca` strategy key. Persist it through SQLModel, Pydantic schemas, and the existing SQLite migration helper; enforce the rule in the Fixed DCA branch of the DCA engine; expose it through the existing strategy form.

**Tech Stack:** FastAPI, SQLModel, Pydantic, Jinja2, vanilla JavaScript, pytest, Playwright/browser verification.

---

### Task 1: Persistence And API Contract

**Files:**
- Modify: `dca_service/src/dca_service/models.py`
- Modify: `dca_service/src/dca_service/api/schemas.py`
- Modify: `dca_service/src/dca_service/database.py`
- Test: `dca_service/tests/test_api.py`

- [ ] **Step 1: Write the failing API persistence test**

Add a test that creates or updates a strategy with `fixed_dca_stop_price_usd: 120000.0`, reads it back from `/api/strategy`, and asserts the value is present.

- [ ] **Step 2: Run the API test to verify it fails**

Run: `poetry run pytest dca_service/tests/test_api.py::test_strategy_persists_fixed_dca_stop_price -q`

Expected: failure because the response schema does not include `fixed_dca_stop_price_usd`.

- [ ] **Step 3: Add the field to persistence and schemas**

Add `fixed_dca_stop_price_usd: Optional[float] = Field(default=None)` to `DCAStrategy`, add `fixed_dca_stop_price_usd: Optional[float] = None` to `StrategyBase`, and add `('fixed_dca_stop_price_usd', 'REAL', None)` to the strategy migration `new_columns` list.

- [ ] **Step 4: Run the API test to verify it passes**

Run: `poetry run pytest dca_service/tests/test_api.py::test_strategy_persists_fixed_dca_stop_price -q`

Expected: pass.

### Task 2: Fixed DCA Decision Rule

**Files:**
- Modify: `dca_service/src/dca_service/services/dca_engine.py`
- Test: `dca_service/tests/test_dca_engine.py`

- [ ] **Step 1: Write failing engine tests**

Add one test where Fixed DCA has `fixed_dca_stop_price_usd=70000.0` and metrics price is exactly `70000.0`; assert `can_execute is False`, `suggested_amount_usd == 0.0`, and the reason mentions the stop price. Add one test where price is `69999.0`; assert it still buys the normal fixed amount.

- [ ] **Step 2: Run the engine tests to verify they fail**

Run: `poetry run pytest dca_service/tests/test_dca_engine.py::test_fixed_dca_stops_at_or_above_stop_price dca_service/tests/test_dca_engine.py::test_fixed_dca_buys_below_stop_price -q`

Expected: failure because the stop-price rule is not implemented.

- [ ] **Step 3: Implement the smallest engine change**

In the `fixed_dca` branch, calculate the fixed amount as before, then if `fixed_dca_stop_price_usd` is a positive number and `price >= fixed_dca_stop_price_usd`, return a `DCADecision` with no execution and a sanitized reason.

- [ ] **Step 4: Run the engine tests to verify they pass**

Run: `poetry run pytest dca_service/tests/test_dca_engine.py::test_fixed_dca_stops_at_or_above_stop_price dca_service/tests/test_dca_engine.py::test_fixed_dca_buys_below_stop_price -q`

Expected: pass.

### Task 3: Strategy Page UI

**Files:**
- Modify: `dca_service/src/dca_service/templates/strategy.html`
- Test: `dca_service/tests/test_api.py`

- [ ] **Step 1: Write the failing template regression test**

Add a test that GETs `/strategy` and asserts the select option says `Fixed DCA`, does not contain `Fixed DCA (Budget Only)`, and includes `id="fixed_dca_stop_price_usd"`.

- [ ] **Step 2: Run the template test to verify it fails**

Run: `poetry run pytest dca_service/tests/test_api.py::test_strategy_page_fixed_dca_stop_price_ui -q`

Expected: failure because the old label remains and the input is missing.

- [ ] **Step 3: Update the template and JavaScript**

Rename the option label, update the Fixed DCA help text, add the numeric stop-price input, populate it in `loadStrategy()`, and serialize a positive number or `null` in `saveStrategy()`.

- [ ] **Step 4: Run the template test to verify it passes**

Run: `poetry run pytest dca_service/tests/test_api.py::test_strategy_page_fixed_dca_stop_price_ui -q`

Expected: pass.

### Task 4: Verification And Acceptance Gate

**Files:**
- Verify: `dca_service/tests/test_dca_engine.py`
- Verify: `dca_service/tests/test_api.py`
- Verify: `dca_service/tests/test_dashboard_add_position_modal.py`
- Verify: `dca_service/tests/test_stats.py`
- Verify: `/strategy`

- [ ] **Step 1: Run focused automated tests**

Run: `poetry run pytest dca_service/tests/test_dca_engine.py dca_service/tests/test_api.py dca_service/tests/test_dashboard_add_position_modal.py dca_service/tests/test_stats.py -q`

Expected: pass.

- [ ] **Step 2: Run the app and verify the real route**

Start the FastAPI app locally, open `/strategy` in the browser, inspect desktop and mobile viewports, and confirm the Fixed DCA option, stop-price input, and form save path render without console errors.

- [ ] **Step 3: Dispatch reviewer gate**

Dispatch exactly four reviewers: two ordinary user reviewers and two UX/UI reviewers. Each reviewer must verify the real `/strategy` route or the evidence from the browser run and return `PASS` or `FAIL` with blockers.

- [ ] **Step 4: Fix blockers and re-run affected checks**

If any reviewer returns a blocker, fix it and re-run the affected automated/browser checks before re-running the relevant reviewer.

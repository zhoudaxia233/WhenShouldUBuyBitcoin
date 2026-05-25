# Transaction Export And DCA Repair Design

## Scope

Replace the current trading-style CSV export with an order-level purchase export, add a server-side repair path for DCA buys that were wrongly marked as manual after older Reset & Sync behavior, and fix the trading-style panel header/status alignment on the stats page.

## Goals

- Export purchase data, not behavior-analysis diagnostics.
- Use one CSV row per purchase order. Fills with the same `binance_order_id` are merged into one order row.
- Show whether each purchase was triggered by scheduled DCA or by an active/manual buy.
- Provide a way to repair the production database even though local `dca.db` is only test data.
- Keep repair safe and auditable by previewing candidate changes before applying them.
- Align the small status text under the trading-style title with the title area shown in the UI.

## Non-Goals

- Do not infer historical `ahr999` values for imported Binance rows in this change.
- Do not rewrite the trading-style analysis itself beyond using corrected source classifications.
- Do not modify unrelated chart/data files currently dirty in the workspace.
- Do not merge or deploy automatically.

## Current Findings

The current export endpoint `/api/stats/trading-style.csv` writes behavior-analysis summary fields and event diagnostics. That is not the requested raw purchase export.

Reset & Sync already preserves order metadata when the pre-reset database still contains correct `source/is_manual` rows. It cannot repair production rows that have already been overwritten to `source=MANUAL`, `is_manual=true`, `notes="Imported from Binance"`, and `ahr999=0`.

The local test database is not authoritative, but it shows useful signatures: many likely DCA buys happen at repeated exact minute buckets across consecutive days, such as `00:00`, `00:01`, and `23:01`, while active/manual buys are more randomly timed and often larger or clustered intraday. The production repair must run against production data and report exactly what it would change.

## Design

### Order-Level Purchase Export

Keep the existing button location, but change its output semantics and filename. The endpoint may keep the same URL for compatibility, but the downloaded file should be named `bitcoin-purchases.csv`.

CSV columns:

- `purchased_at`
- `purchase_date`
- `trigger`
- `source`
- `amount_usd`
- `amount_btc`
- `avg_price_usd`
- `fee_amount`
- `fee_asset`
- `fill_count`
- `binance_order_id`
- `binance_trade_ids`
- `notes`

Classification rules:

- `trigger=DCA` when the normalized order source is `DCA` or a non-manual simulated DCA.
- `trigger=ACTIVE_BUY` when source is `BINANCE` with `is_manual=true`, or source is `MANUAL`.
- `trigger=SIMULATED` when source is `SIMULATED`.
- Otherwise use `UNKNOWN`.

The export should include successful buy rows only, sorted by purchase time ascending. For split fills, amounts and fees are summed, BTC-weighted average price is used, and trade IDs are joined in order.

### DCA Misclassification Repair

Add a repair service function and a protected API route. The route must be admin-only because it mutates production financial records.

The repair runs in two modes:

- `dry_run=true`: return candidate orders and reasons without modifying rows.
- `dry_run=false`: apply approved classification changes in the database.

Candidate selection:

- Only consider successful buy rows with `binance_order_id`.
- Only consider rows currently classified as manual imports: `source=MANUAL`, `is_manual=true`, `notes="Imported from Binance"` or equivalent blank/import notes.
- Group by `binance_order_id` before classification.

DCA evidence:

- Repeated execution minute bucket across multiple orders.
- Daily or near-daily cadence inside that bucket.
- Order amounts in the bucket are relatively consistent after grouping split fills.
- The bucket contains enough samples to avoid reclassifying one-off manual buys.

Default conservative threshold:

- At least 5 candidate orders in the same minute bucket.
- At least 4 distinct purchase dates.
- Median gap between purchase dates is between 0.8 and 1.3 days, or at least 60% of consecutive gaps are 1 day.
- Amount coefficient of variation is no more than 0.35 within the bucket.

When applied, update every fill row for each selected order:

- `source="DCA"`
- `is_manual=false`
- Preserve amounts, BTC, prices, order IDs, trade IDs, fees, timestamps, and notes unless notes are blank.

Return summary counts plus per-order audit details. Public-facing error responses must be sanitized.

### UI Alignment

Move the trading-style status text into the left header block under the title, so the small “Updated …” line aligns with `Trading Style Analysis`. Keep language and export controls on the right. On mobile, stack controls below the title/status block without overlap.

## Testing

Use TDD:

- Add an API/unit test proving the purchase CSV exports order-level rows and not behavior-analysis fields.
- Add a test proving split fills merge into one CSV row with summed USD/BTC and joined trade IDs.
- Add dry-run repair tests that identify likely DCA orders but leave the database unchanged.
- Add apply repair tests that update only selected candidate orders to `DCA/is_manual=false`.
- Add a negative test so random/manual buys in the same dataset are not reclassified.
- Add a template regression test for the header/status alignment structure.
- After implementation, verify the stats route in a browser at desktop and mobile viewports.

## Server Data Plan

Because local `dca.db` is only test data, the production correction will be delivered as code that runs on the server database:

1. Deploy the repair endpoint/service.
2. Run dry-run on production and inspect candidate orders/counts.
3. If the dry-run candidates match the expected DCA pattern, run apply mode.
4. Export CSV again and verify `trigger` classifications.

This avoids guessing from incomplete local data while still making the production database correction reproducible and auditable.

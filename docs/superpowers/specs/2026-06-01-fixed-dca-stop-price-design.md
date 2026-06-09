# Fixed DCA Stop Price Design

## Goal

Clarify Fixed DCA naming and add an optional BTC price ceiling for the Fixed DCA strategy. When the current BTC price is greater than or equal to the configured ceiling, the strategy must skip the buy for that run.

## Current Behavior

`Fixed DCA (Budget Only)` means the buy amount is based only on the monthly budget and execution schedule:

- Daily: `monthly budget / 30.44`
- Weekly: `monthly budget / 4`

It does not use AHR999 to size the buy. AHR999 is still shown for reference. This label is confusing because the service also has monthly budget cap behavior, so the UI should label the strategy as `Fixed DCA` and explain the budget/schedule formula in the help text.

## Requirements

- Rename the strategy option from `Fixed DCA (Budget Only)` to `Fixed DCA`.
- Keep the existing `fixed_dca` strategy key unchanged for backward compatibility.
- Add a nullable `fixed_dca_stop_price_usd` strategy field.
- Show the stop-price input only inside the Fixed DCA configuration section.
- Treat an empty stop-price value as disabled.
- For Fixed DCA only, skip buying when `current BTC price >= fixed_dca_stop_price_usd`.
- The stop price applies only to automatic Fixed DCA execution and scheduled DCA preview. It must not prevent or cap Extra Buy/manual buy flows.
- When a Fixed DCA stop price is configured, the dashboard must show it in the DCA Strategy surface with copy that makes the automatic-only scope clear.
- When skipped by stop price, return a sanitized user-facing reason; do not expose internals or stack traces.
- Persist the field through the strategy API and existing SQLite migration helper.
- Preserve existing Fixed DCA amount behavior when the stop price is disabled or the current price is below the stop price.

## Design

The data model, Pydantic strategy schemas, and existing strategy table migration helper will gain `fixed_dca_stop_price_usd` as an optional real-valued field. The API already updates strategy fields generically via schema dumps, so adding the field to the schema and model is enough for create, read, and update flows.

The DCA engine will apply the stop-price rule inside the `fixed_dca` branch after reading live metrics and calculating the fixed base amount. If the configured stop price is present and positive, and the metrics price is at or above that stop price, the decision returns `can_execute=False`, `multiplier=0.0`, and `suggested_amount_usd=0.0` with the current price, AHR999, metrics source, budget display fields, and display-only market context preserved where practical.

The strategy template will rename the select option and add a numeric USD input to the Fixed DCA panel. Loading strategy data fills the input when present. Saving strategy data sends `null` for blank or non-positive values and sends the positive number otherwise.

The dashboard will show the configured cap in the DCA Strategy card only when the active strategy is Fixed DCA and the cap is a positive number. The display will say `Fixed DCA cap` with `Auto DCA only` subtext so users understand that Extra Buy is separate.

## Testing

- Add an engine regression test that Fixed DCA skips when current price equals the stop price.
- Add an engine regression test that Fixed DCA still buys below the stop price.
- Add an API regression test that the stop price persists through create/update/read.
- Add a template regression test that the strategy page uses `Fixed DCA` without `Budget Only` and includes the stop-price input.
- Add dashboard regression coverage that the cap is visibly represented as automatic-only and that Extra Buy button state does not depend on `can_execute=false` from the scheduled DCA stop cap.
- Add Extra Buy endpoint coverage showing a manual buy still records when the Fixed DCA stop cap is configured below the current buy price.
- Run focused DCA tests, API/template tests, and a browser check for `/strategy` desktop and mobile.

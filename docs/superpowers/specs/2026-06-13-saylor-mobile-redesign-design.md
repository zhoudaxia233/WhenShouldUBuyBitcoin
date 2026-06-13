# Saylor reserve chart — mobile redesign

Date: 2026-06-13

## Problem

On phones the "Bitcoin Reserve Value" (Saylor) panel on `/stats` felt cramped and
unpolished compared with the well-regarded third-party treasury dashboard the user
referenced as the target look:

1. The chart's x-axis labels were hidden behind the fixed `.mobile-bottom-nav`.
2. There was no time-range control, so the chart always showed the full history
   zoomed out — busy line, huge `$20k–$140k` y-axis span.
3. The reserve stats stacked into ~5 separate lines (As of / P&L / purchases / total
   BTC), eating vertical space.
4. The chart was short with a muddy boxed inner background.
5. A large full-width "Reset view" button dominated the bottom and collided with the nav.

## Goals / non-goals

- Adopt the target's **layout, hierarchy, range control, and chart treatment** on mobile.
- **Keep** the existing warm SatsFlow palette (do not switch to the target's cooler
  near-black) so the panel stays consistent with the rest of the app.
- Desktop layout unchanged. No changes to the data API or chart datasets.

## Design

Mobile (`@media (max-width: 767.98px)`), top to bottom:

1. **Tight KPI hierarchy** — small uppercase kicker → huge reserve value with an inline
   P&L **pill** (`#saylorPnlMobileBadge`, green/red) → one stat row
   (`₿ <balance> · Avg <cost>`) → one caption line (`<n> purchases · As of <date>`).
   Collapses five stacked lines into three. New `#saylorAsOfMobile` carries the caption
   date; the desktop `#saylorAsOf` is unchanged.
2. **Segmented range pills** `#saylorRangePills` — `3M · 6M · 1Y · All`, **1Y** active by
   default (opens zoomed to the last 12 months for a clean first impression; tap **All**
   for full purchase history).
   Pills drive the chart x-axis via `setSaylorRange` → `applySaylorSelectedRange`
   (`saylorRangeStartMs` maps a preset to `[now - span, now]`). The selection is
   re-applied at the end of every `renderSaylorChart`, so it survives theme re-renders.
3. **Taller chart (430px) with a clean frame** — transparent background, subtle
   `--dashboard-border`, replacing the muddy boxed look.
4. **Bottom-nav clearance** — `body.stats-page` gets
   `padding-bottom: calc(82px + env(safe-area-inset-bottom))` and the card body adds a
   safe-area-aware bottom pad, so the x-axis and controls clear the floating nav.
5. **Subtle reset** — the existing `#resetSaylorZoomBtn` becomes a `.saylor-reset-link`
   ghost link, hidden (`visibility:hidden; opacity:0`) until a manual pinch/pan reveals it
   (`onPanComplete`/`onZoomComplete` → `revealSaylorResetControl`). Tapping a pill or reset
   hides it again. Reset restores the active preset rather than always jumping to All.

### Cascade note

The legacy `@media (max-width: 575px)` Saylor rules are left in place; the new
`@media (max-width: 767.98px)` block is authoritative because it appears later in source
and wins overlapping properties at ≤575px. The one higher-specificity leak
(`html[data-bs-theme="dark"] .saylor-mobile-pnl-chip { background: transparent }`, which
would have erased the new pill background) was removed.

## Testing

`tests/test_stats_template_regression.py` encodes the contract as string assertions over
the rendered template (markup ids/classes, the mobile CSS block, and the wiring JS).
Updated/added tests: compact KPI hierarchy, range pills (default All, wiring), chart
order + height + subtle reset (hidden via `visibility:hidden`, revealed on gesture),
floating-nav clearance, and "As of" set on both desktop and mobile. Full suite: 393 passed.

Verified visually at iPhone-13 width (light + dark) by rendering the real template with
mock purchase data: hierarchy, pill zoom (3M), and x-axis clearing the nav.

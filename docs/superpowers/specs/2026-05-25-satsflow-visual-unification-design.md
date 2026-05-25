# SatsFlow Visual Unification Design

Date: 2026-05-25

## Goal

Unify every server-rendered DCA service page with the existing dashboard visual language. The dashboard is the reference surface and should not be redesigned. Other pages should feel like they belong to the same SatsFlow product instead of using separate Bootstrap gray-blue or legacy purple login styles.

Affected routes and templates:

- `/` via `dca_service/src/dca_service/templates/index.html`
- `/api/auth/login` via `dca_service/src/dca_service/templates/login.html`
- `/admin/data-sources` via `dca_service/src/dca_service/templates/admin_data_sources.html`
- `/stats` via `dca_service/src/dca_service/templates/stats.html`
- `/strategy` via `dca_service/src/dca_service/templates/strategy.html`
- `/settings/binance` via `dca_service/src/dca_service/templates/binance_settings.html`

## Chosen Approach

Use a shared SatsFlow design system extracted from the dashboard.

The implementation should move the dashboard's reusable visual primitives into shared CSS and shared template fragments where practical. Each page then keeps its own content and workflows while adopting the same tokens, header, navigation, panels, cards, forms, theme toggle, and version badge. This replaces the older pattern where each template owns a separate inline style block.

This approach intentionally supersedes the old regression expectation that `/static/app.css` must not be loaded. A shared stylesheet is now the preferred mechanism because the product goal is consistency across pages.

Rejected alternatives:

- Copy dashboard styles into every template: low initial risk, but it preserves duplication and makes future visual drift likely.
- Only polish login and admin pages: lower scope, but leaves stats, strategy, and settings inconsistent with the confirmed requirement.

## Visual System

The shared system should preserve the dashboard's current SatsFlow style:

- Orange Bitcoin accent: `#ff8a00` primary and `#f97316` strong accent.
- Warm light theme: soft warm page background, white translucent panels, subtle amber borders.
- Dark theme: dark brown-black background, warm panel surfaces, muted tan text, amber accent states.
- Typography: Inter/system sans stack, strong but compact headings, no negative letter spacing beyond existing dashboard usage.
- Geometry: mostly 10px radii for panels/buttons, circular brand mark and theme toggle, no nested decorative cards.
- Elevation: subtle dashboard shadow, not heavy Bootstrap default card shadow.
- Controls: dashboard-style nav buttons, accent primary buttons, soft outline buttons, consistent form focus rings.
- Branding: SatsFlow brand lockup with the circular orange mark should be used on authenticated page headers and adapted for login.

## Page Behavior And Layout

Dashboard:

- Preserve current layout and content behavior.
- Migrate only reusable style primitives if needed.
- Keep active dashboard navigation state.

Login:

- Replace the legacy purple gradient with the SatsFlow warm background and orange brand treatment.
- Keep CSRF handling, error rendering, email/password fields, submit behavior, theme toggle, and version badge.
- Use a focused sign-in panel that visually matches dashboard cards without adding marketing copy or extra flows.
- Error messages must remain sanitized and user-appropriate.

Admin diagnostics:

- Use the shared authenticated header and dashboard navigation styling.
- Convert Bootstrap-default cards into dashboard panels while preserving diagnostics content, copy/report, refresh, log tail, and runtime sections.
- Keep sanitized diagnostics output. Do not expose raw exceptions, secrets, stack traces, request internals, or infrastructure details beyond the existing admin-only diagnostic data.

Stats:

- Use shared page shell, header, navigation, cards, dark mode, buttons, and table treatment.
- Preserve analytics structure, Chart.js behavior, trading-style controls, CSV export, and admin-only chart regeneration gate.
- Special analytics panels may keep their information hierarchy, but colors and borders should be aligned with the SatsFlow tokens.

Strategy configuration:

- Use shared page shell, header, navigation, panels, forms, mobile tier layout, and save controls.
- Preserve all strategy form IDs, dynamic strategy behavior, preview/cache behavior, validation, and mode switching.

Binance settings:

- Use shared page shell, header, navigation, panels, forms, alert styling, and version badge.
- Preserve read-only connection messaging, credential masking, email settings, and all existing API interactions.

## Implementation Boundaries

- Prefer existing Bootstrap and Bootstrap Icons dependencies. Do not add a new frontend framework.
- Keep the service-rendered template architecture.
- Avoid broad content rewrites and unrelated refactors.
- Keep public pages sanitized. Login errors must not reveal raw exceptions or internals.
- Preserve auth boundaries and admin-only visibility.
- Preserve local or user changes and do not revert unrelated files.

## Testing Plan

Use TDD for the template behavior changes:

1. Update or replace the old original-style regression that expects no shared stylesheet and the legacy login purple gradient.
2. Add failing template tests that assert every affected template loads the shared SatsFlow design system.
3. Add failing template tests for the shared brand/header/nav primitives on authenticated pages.
4. Add failing template tests that login uses SatsFlow tokens/brand treatment and no longer uses the purple gradient.
5. Add or update focused tests for admin page visual primitives while preserving existing admin sanitization/auth tests.
6. Implement the smallest template/CSS changes that pass those tests.

Verification commands should include the relevant Python test subset first, then broader project tests if runtime allows. Existing JavaScript/Vitest tests should be run when templates or static public docs are touched in a way that could affect them.

## Browser Verification Plan

After implementation, run the app locally and verify these routes:

- Desktop and mobile `/api/auth/login`
- Desktop and mobile `/`
- Desktop and mobile `/admin/data-sources`
- Desktop and mobile `/stats`
- Desktop and mobile `/strategy`
- Desktop and mobile `/settings/binance`

For each route, check:

- Page identity and nonblank meaningful content.
- No framework or runtime error overlay.
- No relevant console errors.
- Header, nav, brand, theme toggle, cards/panels, forms, and version badge match the SatsFlow system.
- Mobile layout does not clip, overlap, or hide required controls.
- At least one relevant interaction still works, such as theme toggle, login form rendering, admin refresh/copy controls, settings dropdown, or page-specific buttons.

## Subagent Review Gate

The final implementation must not be considered complete until four subagents have reviewed the result and all required reviewers pass:

- User reviewer 1: evaluate whether the app feels consistent from a normal returning user's perspective.
- User reviewer 2: evaluate whether important workflows remain understandable and usable after the visual changes.
- UX/UI reviewer 1: evaluate visual consistency, hierarchy, spacing, color, typography, and responsive behavior.
- UX/UI reviewer 2: evaluate polish, accessibility risks, state clarity, and mismatches with the dashboard reference.

If any reviewer requests changes, address them and repeat the relevant verification before final handoff.

## Success Criteria

- All affected pages share the SatsFlow dashboard visual system.
- The dashboard remains recognizable and functionally unchanged.
- Login no longer uses the purple gradient/card visual system.
- Authenticated pages no longer look like unrelated Bootstrap defaults.
- Existing auth/admin boundaries and sanitized public error behavior are preserved.
- Relevant automated tests pass.
- Browser checks pass on desktop and mobile for all affected routes.
- All four required subagent reviews pass.

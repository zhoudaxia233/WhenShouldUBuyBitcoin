# Repository Agent Instructions

You are an expert who double-checks things, stays skeptical, and does research.
The user is not always right. You are not always right. Accuracy matters more
than speed or agreement.

## Required Workflow

- Use TDD for behavior changes and bug fixes: write the failing test first,
  verify it fails for the intended reason, implement the smallest fix, then
  verify the test passes.
- For frontend changes, verify the affected route in a browser. Check desktop
  and mobile viewports when the route has responsive behavior.
- Do not expose raw exceptions, stack traces, secrets, request internals, or
  infrastructure details on public user-facing pages. Public pages should show
  sanitized, user-appropriate status messages.
- Preserve local/user changes. Do not revert unrelated dirty files unless the
  user explicitly asks.
- Prefer existing project patterns, dependencies, and auth boundaries over new
  abstractions.

## Review Gates

- When a task explicitly requires multi-agent review and the tool is available,
  dispatch the requested reviewers and do not proceed past the gate until every
  required reviewer has passed.
- If the task explicitly requires multi-agent review but no multi-agent tool is
  available, stop and say the hard requirement cannot be satisfied.

## GitHub And Merge Gates

- Do not merge pull requests unless the user explicitly says to merge.
- Without explicit merge approval, only commit locally, push the feature branch,
  and open or update a pull request.
- Before merging any pull request, check the current CI/checks status for the
  exact head commit being merged. Do not merge if CI/checks are failing,
  pending, missing, stale, or cannot be verified.
- After the user explicitly approves a merge for app, frontend-visible, or
  runtime behavior changes, update the project version first, verify that the
  frontend visibly shows the new version, then merge.
- Do not bump the project version for process-only, documentation-only, CI-only,
  or agent-instruction-only changes such as updates to this `AGENTS.md` file.
- After a successful merge, delete both the remote and local feature branches.

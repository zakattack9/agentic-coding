<!--
  gh-projects PR template. This PR must NOT close its issue — use a NON-closing
  reference so merge leaves the item open (board-status closes it at prod).
  Prefer a real linked branch (`gh issue develop` / the issue dev panel) over a
  body keyword.  DO NOT write "Closes #N", "Fixes #N", or "Resolves #N".
-->

## Relates to

Relates to #<!-- issue number -->

> Non-closing on purpose. Link this PR to its issue via the **linked branch**
> (dev panel / `gh issue develop`); the `Relates to #N` above is the human
> backstop. The board flips the item In Review on a non-draft PR, On Staging on
> merge, and Done only at prod deploy.

## Acceptance Criteria

This PR satisfies the issue's `## Acceptance Criteria` table. Per `AC-N`:

- [ ] AC-1 — <!-- how this PR makes it true -->
- [ ] AC-2 —

(Reference each `AC-N` from the linked issue; check it once the change makes that
observable end-state true.)

## Staging

- Staging URL: <!-- where this was exercised after the staging deploy -->
- [ ] Exercised the change on staging before promoting to prod.

## Checklist

- [ ] Linked to the issue via a linked branch (not a closing keyword).
- [ ] One peer approval (convention; rulesets are unavailable on our plan).
- [ ] no-squash merge (the repo merge setting enforces this).

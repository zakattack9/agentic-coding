# Requirements-coverage checklist

The product-requirement **dimensions a spec must consciously sweep** so nothing load-bearing is
missed by omission. `write-spec`'s Discovery walks it to *elicit* requirements; `refine-spec`
re-sweeps it to catch a dimension the draft left uncovered. It is the **WHAT** counterpart to
`quality-bar.md` (the engineering-**HOW** verticals) — where a dimension below is about *how well*
the thing is built rather than *what* it must do (performance, security depth, maintainability),
defer to `quality-bar.md` instead of duplicating it here.

## The rule — sweep every dimension, mark N/A explicitly, never skip silently

For each dimension: **either elicit a concrete requirement (→ an `AC`) or explicitly mark it N/A for
this change.** A silently-skipped dimension is exactly how a requirement goes missing — the failure
this checklist exists to prevent. **Scale to the change** (rigor): a `light` task legitimately N/As
most dimensions; a `standard` feature works the ones it touches; a `full` change sweeps all. This is
a **prompt for finding holes, not a section to add to the spec** — the output is ACs, not a copy of
this list. Prefer to **lead each question with your recommended answer** and stop when the returns
diminish.

## The dimensions

- **Actors & roles** — who uses this; what differs by role.
- **Triggers / entry points** — what initiates each behavior (user action, API call, schedule, event).
- **Core behaviors** — the happy-path capabilities each actor gets.
- **Inputs & validation** — accepted inputs, required vs optional, formats/ranges, validation rules and the message on failure.
- **States & lifecycle** — the states an entity moves through, the allowed transitions, and the terminal states.
- **Edge & boundary cases** — empty, max / over-limit, zero / negative, duplicate, missing, malformed.
- **Error & failure handling** — invalid input, partial failure, timeout, a downstream error: what the user sees, and whether it retries / rolls back / fails closed.
- **Concurrency & ordering** — simultaneous actions on the same entity, idempotency of a repeated request, any ordering guarantee.
- **Data lifecycle** — create / read / update / delete; soft vs hard delete; retention; and **migration of existing data** the change affects.
- **Permissions & ownership** — which actions require authorization, and who may act on whose data (the product rule; least-privilege *implementation* is `quality-bar.md`).
- **Notifications & side-effects** — emails, webhooks, audit-log entries, and any downstream or external effect a behavior triggers.
- **Integrations & dependencies** — external systems / APIs this calls or feeds, and how it behaves when one is slow or down.
- **Limits & quotas** — rate limits, size caps, pagination, and behavior at the limit.
- **Observability & audit** — what must be logged, measured, or audited to operate or satisfy compliance (the product need; the wiring is `quality-bar.md`).
- **Rollout & compatibility** — feature-flag / phased rollout, and backward compatibility of data and any public contract the change touches.
- **Accessibility & i18n** — for user-facing changes: keyboard / screen-reader access, locale, timezone, currency, right-to-left.
- **Non-functional / quality bar** — performance, scale, and security depth: elicit the *appetite* here, then defer to **`${CLAUDE_PLUGIN_ROOT}/references/quality-bar.md`** for the verticals (don't restate them).
- **Explicit out-of-scope** — what this change deliberately does **not** do (a single bounded carve-out that prevents a likely scope error).

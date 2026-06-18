# board-status (composite action)

Deploy-accurate GitHub Projects v2 **Status** reporter. Add **one step** to an
existing deploy job to report a deploy-accurate Status for the issues tied to
the deployed SHA. Deterministic and **free** — no AI, no metered model call.

## Self-contained

This action **vendors its own GraphQL/resolution logic** in
[`board_status.py`](./board_status.py) and **imports nothing from the
gh-projects plugin**. `scaffold-repo` installs it per-repo at
`./.github/actions/board-status`, referenced as `- uses: ./.github/actions/board-status`.
It therefore runs from a repo that does **not** have the plugin installed —
`board_status.py` is pure Python stdlib and reaches GitHub only through an
injectable command runner, so it is exercised fully offline by the tests.

## Status-target contract

| Event | Status written | Issue state | Who |
|-------|----------------|-------------|-----|
| PR merged (native built-in) | `On Staging` | **stays open** | native Project built-in |
| Staging deploy success | `On Staging` | **stays open** | this action (`--status staging`) |
| Prod deploy success | `Done` | **closed** + Release published | this action (`--status prod`) |

### Native "PR merged" built-in target

> The native **"PR merged → set Status"** built-in workflow is configured to
> **`On Staging`** (NOT `Done`), and the item **stays open** after merge.

`scaffold-repo` sets that built-in to `On Staging`; this
action's staging path writes the **same** non-terminal target so the merge and
the staging deploy agree. The item is moved to **`Done`** and **closed only at
prod**, here — never by `Closes #N`, never by `board-sync`.

## Monotonic + idempotent

Every Status write resolves the item's **current** Status first and only
**advances** it along `Backlog < Ready < In Progress < In Review < On Staging <
Done`. A **replayed or stale** deploy event is a no-op — it never regresses an
item to an earlier stage. Only an explicit reopen moves Status backward.

## Token (constraint #2)

Every Projects v2 field write uses a **GitHub App installation token**, minted by
the action from the App **id + private key** secrets. **`GITHUB_TOKEN` is never
used for a Project write** — it cannot write Projects v2 fields at all.

## Usage

```yaml
# in your existing deploy-staging job, after the deploy succeeds:
- uses: ./.github/actions/board-status
  with:
    project: 7
    status: staging
    app-id: ${{ secrets.GH_APP_ID }}
    app-private-key: ${{ secrets.GH_APP_PRIVATE_KEY }}

# in your existing deploy-prod job, after the prod deploy succeeds:
- uses: ./.github/actions/board-status
  with:
    project: 7
    status: prod
    tag: ${{ github.ref_name }}
    app-id: ${{ secrets.GH_APP_ID }}
    app-private-key: ${{ secrets.GH_APP_PRIVATE_KEY }}
```

On prod success the action resolves shipped issues from the deployed SHA
(SHA → merged PRs → the issues those PRs resolved), sets **Done**, **closes**
each issue, and **publishes the tag's Release**.

# Golden-template Project — setup guide

`gh-projects` never builds a board from scratch. It stands up every board by
**copying** one **golden-template Project** (`scaffold-repo` → `copyProjectV2`). You
build that template **once**, in an organization; after that, onboarding a new org is
a one-time copy and standing up a repo's board is a single command.

This is the comprehensive companion to the short "Prerequisites #3" section of
[`README.md`](README.md). It is explicit about **what can and can't be automated** and
about **where each piece must live**.

---

## Where things live (read this first)

There are two distinct artifacts — don't conflate them:

- **The template *definition* — this repo.** [`templates/project/fields.json`](templates/project/fields.json),
  [`views.md`](templates/project/views.md), and [`insights.md`](templates/project/insights.md)
  are the version-controlled, vendor-neutral source of truth. This is what gives you
  **portability and ownership**: the template is reproducible in any org from these
  files, and it lives in a repo you own, not trapped inside a client org.
- **The live template *Project* — an organization.** The running golden-template
  Project **must live in an org**, not a personal account, because it depends on two
  **organization-only** features:
  - **`Type`** is an org **Issue Type**.
  - **`Priority` / `Start date` / `Target date`** are org **custom Issue Fields**
    (org-level, and **only supported in private projects**).

  Most of the eight views depend on those fields (Priority/Target sorting, Type
  slicing, the Roadmap's Start→Target bars), so a personal account literally can't
  build them. **The Project must also be private** — issue fields don't work on public
  projects.

**The plan:** build the canonical live template once in your first org (**zilarent**),
keep the definition in this repo, and copy zilarent's template **org→org** to onboard
any future org. `copyProjectV2` fully supports a cross-org copy (the destination
`ownerId` can be any org you can create projects on; the source only needs to be
readable by the acting identity).

---

## Automation map

The `setup_board.py` script (Phase 0.2) does everything in the "scripted" rows below;
the rest is a one-time UI pass. (API surface: GraphQL for project create/settings; the
REST Projects API at `X-GitHub-Api-Version: 2026-03-10` for fields, views, issue types.)

| Ingredient | Automatable? | Carried by `copyProjectV2`? | How |
|---|---|---|---|
| The Project itself (private) | ✅ scripted | n/a | GraphQL `createProjectV2` + `updateProjectV2 {public:false}` |
| **Project fields** (Size, Tier, PM-ID, Spec, Blocked + the 6 Gantt-signal fields) | ✅ scripted | ✅ copy carries *"views and custom fields"* | REST `POST .../projectsV2/{n}/fields` |
| **Iteration field** (Sprint) | ✅ scripted | ✅ field copies; `scaffold-repo` re-plans dates per board | REST `.../fields` with `iteration_configuration` (new in `2026-03-10`) |
| **Org Issue Type** (`Type`) | ✅ scripted | ❌ org-wide, outside the copy | REST `POST /orgs/{org}/issue-types` |
| **Org Issue Fields** (Priority, Start date, Target date) | ✅ scripted | ❌ org-wide, outside the copy | REST `POST /orgs/{org}/issue-fields` |
| **Org fields as project columns** | ✅ scripted | ✅ copy carries | REST `POST .../fields {"issue_field_id": …}` |
| **8 views + their visible columns** | ✅ scripted | ✅ copy carries | REST `POST .../views` with `visible_fields` (resolved from `views.json` `fields`) |
| **8 views — grouping / slice / sort / swimlanes** | ❌ UI | ✅ copy carries the finished view | view-create takes name/layout/filter/visible_fields only; no view-update API |
| **Board column order** (e.g. Triage's Schedule health columns) | ❌ UI | ✅ copy carries | board columns follow the field's option order; reorder by drag — no API (`group_order` in views.json is the reminder) |
| **`Type` as a view column** (Grooming) | ❌ UI | ⚠️ carries but scaffold can't verify | `issue_type` is silently dropped from `visible_fields`; toggle the column on by hand (`ui_columns` in views.json) |
| **Global field order** (Settings → Fields) | ❌ UI | ✅ copy carries | no `position` attribute / PATCH on the fields API — drag once (`field_display_order` in fields.json is the source of truth) |
| **Built-in Status options + colors** (the 6 stages) | ❌ UI | ✅ copy carries | no API to set a built-in field's options or colors |
| **3 Insights charts** | ❌ UI | ⚠️ docs promise only views + fields; may **not** carry → verify per board | no API to create *or* read a chart |
| **Mark as org template** | ✅ scripted | n/a | GraphQL `markProjectV2AsTemplate` |

**Bottom line:** one script (`setup_board.py`) builds the project, all fields
(including `Sprint`, **with their option colors**), the org issue type + fields, the org
columns, and the 8 views **with their visible columns + tab order**, and **marks it the
org template**. A short UI pass finishes the rest — the **Status options + colors**, each
view's **grouping / slice / sort / board-column order**, the **Grooming `Type` column**,
the **global field order**, and the **3 charts** — once, on the canonical template; every
other org inherits it all by `copyProjectV2`. **The script prints the exact punch-list.**

---

## Field homes — why some fields aren't in the copy

The board splits fields across three "homes" (see
[`templates/project/fields.json`](templates/project/fields.json)):

- **`project`** — lives *in* the Project, created on the template, **carried by the
  copy.** (Status, Size, Tier, Sprint, Parent issue, PM-ID, Spec, Blocked, Schedule
  health, Slippage, Slippage days, Blast radius, Blast count, Impact level, Decision
  needed.)
- **`issue_type`** — `Type` is an **org-wide Issue Type**, not a project field, so it
  is *not* in the copy. Created once per org.
- **`issue_field`** — Priority, Start date, Target date are **org-wide custom Issue
  Fields** (≤25 per org, private projects only). Also *not* in the copy. Created once
  per org; they surface as columns on a private project.

So the **canonical template Project** carries the `project`-home fields + views +
charts. The `issue_type` and `issue_field` items are org-level — created once for each
org (by you or by `scaffold-repo`) and shared by every board in that org.

---

## Credentials — which identity does what

- **Building the canonical template + onboarding a new org** (touches org settings —
  Issue Types/Fields — and reads a project across orgs): use **your own org-owner
  auth** (`gh auth login` as yourself, an owner of the org). The plugin's App token is
  scoped to a single org and **cannot** read a source project in a different org, so
  the cross-org seed copy is done as *you*, not the App.
- **Running `scaffold-repo` and the skills** (ongoing, within one org): the **GitHub
  App installation token** for that org (`GH_APP_TOKEN`, or `APP_ID` +
  `APP_PRIVATE_KEY[_PATH]`). `GITHUB_TOKEN` cannot write Projects v2.

Install the GitHub App on **each** org you operate (it's per-org). **Phase 0.0** below
is the full create-and-install walkthrough.

---

## Phase 0.0 — Create the GitHub App (one-time, org admin — per org)

`GITHUB_TOKEN` **cannot write Projects v2** — an **org-owned GitHub App installation
token** is the only credential that can. Create one App **per org** you operate
(zilarent first). It is purely a token source: the board automation runs as repo
GitHub Actions, so the App needs **no webhook**.

### 1. Register the App (org-owned)

zilarent → **Settings → Developer settings → GitHub Apps → New GitHub App**.
(Registering under the org makes the org the owner — cleaner for a team than a
user-owned App installed on the org.) Give it a name (e.g. `zilarent-projects-bot`)
and any Homepage URL.

### 2. Permissions — the minimum the plugin needs

**Repository permissions:**

| Permission | Level | Why |
|---|---|---|
| **Administration** | Read & write | Toggle the repo **no-squash** merge setting (`scaffold-repo`) |
| **Contents** | Read & write | Cut the authoritative linked branch; publish Releases (`board-status`) |
| **Issues** | Read & write | Create issues, set fields, assignees, milestones; close at prod |
| **Pull requests** | Read & write | Open/update/merge the linked PR (`create-pr`, `board-sync`) |
| **Metadata** | Read-only | Mandatory (auto-selected) |

**Organization permissions:**

| Permission | Level | Why |
|---|---|---|
| **Projects** | Read & write | Every board write — the core of the plugin |

> The org **Issue Type + Issue Fields** are created by **you as an org owner** in
> Phase 0.2 / 0.3, so the App does **not** need org-administration for them.

### 3. Webhook

**Uncheck "Active."** The plugin is driven by repo Actions on `issues` /
`pull_request` / `push` events that mint a token from this App — the App subscribes to
no events itself.

### 4. Create, then generate a private key

- Click **Create GitHub App**, then note the **App ID** (General page).
- **Generate a private key** → it downloads a `.pem`. Store it securely — GitHub shows
  it once and you can't re-download it (you can only generate a new one).

### 5. Install it on the org

App page → **Install App** → install on **zilarent** → **All repositories** (or
select). The install URL ends in `…/installations/<id>` — that **Installation ID** is
only needed if the App ends up with more than one installation (`APP_INSTALLATION_ID`).

### 6. Store the App **secrets** (the board *variables* come later)

Store only the App credentials here — they're all you have at this point. The board
**variables** (`GH_PROJECT_NUMBER` etc.) need a board to exist, which `scaffold-repo`
doesn't create until [§"Wire the board's CI variables"](#wire-the-boards-ci-variables)
below — set them then.

The shipped workflows mint the installation token via
`actions/create-github-app-token` from these **secrets**:

- `GH_APP_ID` = the App ID
- `GH_APP_PRIVATE_KEY` = the entire `.pem` file

**Where you store them depends on your org's plan — and the board variables later
follow the same path. No code change either way: the workflows read `secrets.X`, which
GitHub resolves from an org-level *or* a repo-level definition identically.**

#### Path A — Paid org (GitHub Team / Enterprise): set once at the org level

**Settings → Secrets and variables → Actions → New organization secret.** Give each a
**repository access** policy that includes your private board repos (or "All
repositories"). One definition covers every repo.

#### Path B — Free org: set per private repo

GitHub **Free does not let organization secrets/variables reach _private_
repositories** — a plan limit, not a misconfiguration (on Free, org secrets serve only
*public* repos). Set the same secrets on **each private repo** that runs the board
workflows, under that repo's **Settings → Secrets and variables → Actions**. (On Free
it's simplest to set the secrets **and** the variables together, per repo, in the
board step below.)

```bash
R=zilarent/your-repo        # repeat for each private repo on the board
gh secret set GH_APP_ID          --repo "$R" --body "123456"
gh secret set GH_APP_PRIVATE_KEY --repo "$R" < app.pem
```

### 7. For running the skills locally

`scaffold-repo` and the other skills mint/use the token from **your shell env** (not
the CI secrets), via `lib/gh.py:get_app_token()`. Provide one of:

```bash
export GH_APP_TOKEN=<installation-token>        # if you already minted one, or…
export APP_ID=<app-id>
export APP_PRIVATE_KEY_PATH=/path/to/app.pem    # or: APP_PRIVATE_KEY="$(cat app.pem)"
export APP_INSTALLATION_ID=<id>                 # only if the App has >1 installation
```

Note the **local** names (`APP_ID` / `APP_PRIVATE_KEY[_PATH]`) differ from the **CI
secret** names above — they're read by different code paths. `GITHUB_TOKEN` is
rejected for Project writes either way.

---

## Phase 0.1 — Prerequisites

1. **`gh` CLI** authenticated as **yourself**, an owner of zilarent, **with the
   `project` and `admin:org` scopes**: `gh auth login`, then
   **`gh auth refresh -s project,admin:org`**. `project` is needed for every Projects
   v2 read/write (without it `createProjectV2` fails *"…not been granted the required
   scopes … 'project'"*); `admin:org` is needed to create the org Issue Type + Issue
   Fields.
2. **Python 3** for the engine.
3. The **GitHub App** from **Phase 0.0** installed on zilarent (and any other org),
   with its **secrets** stored (the board **variables** are set later, once
   `scaffold-repo` has created the board).

---

## Phase 0.2 — Build the canonical template (one command + a short UI pass)

Run **`lib/setup_board.py`** as your **org-owner `gh` auth**, which needs the
`project` **and** `admin:org` scopes (`gh auth refresh -s project,admin:org`). It
builds everything the API allows — straight from `templates/project/*.json`,
**dry-by-default**, and **idempotent** (a re-run skips whatever already exists).

### Step 1 — Run the setup script

```bash
SB="$(git rev-parse --show-toplevel)/claude-code/plugins/gh-projects/lib/setup_board.py"
# preview the full plan (creates nothing):
python3 "$SB" --org zilarent --title "GitHub Projects Golden Template"
# apply it:
python3 "$SB" --org zilarent --title "GitHub Projects Golden Template" --apply
```

In one pass it creates: the **private Project**; the org **`Type`** Issue Type; the
org Issue Fields (**Priority / Start date / Target date**); **every project field,
including the `Sprint` iteration**; **adds the org Issue Fields as project columns**
(so views can show them); the **8 views with their visible columns** (`visible_fields`
resolved from each view's `fields` in `views.json`); and **marks the Project the org
template** (`markProjectV2AsTemplate`) — then prints the punch-list below. Re-run any
time with the same `--title` (or `--project-number N`): it reuses the project and skips
fields/columns/views that already exist.

> **Views can't be refreshed in place.** GitHub's view API is **create-only** (no
> update *or* delete — both 404, and no GraphQL view mutation). So a re-run can't fix a
> view an earlier run created — it **flags stale views** and you **delete them in the
> UI, then re-run** to recreate them correctly. (Grouping/sort/slice are UI either way.)

> It never drifts from the repo: project fields ← `fields.json`, Sprint cadence ←
> `iterations.json`, view shells ← `views.json`, issue type/fields ← `fields.json`.
> Change those files and re-run. (`createProjectV2` is GraphQL; everything else uses
> the REST Projects API at `X-GitHub-Api-Version: 2026-03-10`, which is what makes the
> iteration field and view shells scriptable.)

### Step 2 — Finish in the UI

The script prints these at the end; do them once, on the template:

1. **Status options + colors.** Edit the built-in **Status** field's options **and set
   each option's color** to exactly `Backlog (gray) · Ready (blue) · In Progress (yellow)
   · In Review (pink) · On Staging (orange) · Done (green)` — in that order (it's the
   monotonic automation key). There is no API for this: **delete the 3 options it ships
   with (`Todo / In Progress / Done`) and add the 6 above in order**, then set **`Backlog`
   as the default** option (the status new items land in). Copy option names
   **verbatim** from [`fields.json`](templates/project/fields.json) — the views'
   filters, `lib/dag`, and `signals-sync` write these names back, so a typo silently
   breaks the automation.
2. **View grouping / slice / sort / swimlanes / column order.** The script already set
   every view's **columns** (`visible_fields` — including the org `Priority` / `Target
   date` columns) and its filter. What the view-create API has **no parameter** for — and
   there's no view-update API — is each view's grouping / slice / sort / swimlanes and a
   board's **column order**, so finish those per [`views.md`](templates/project/views.md).
   The script prints the per-view list; highlights: *Sprint* → columns by Status; *Triage*
   → group Schedule health (drag the columns to **Overdue→Blocked→At risk→On track→Done** —
   the field's option order stays put), slice Decision needed, sort **Priority↑ then Blast
   radius↓**; *Ready* → sort **Target↑ then Size↓**; *Epics* → sort **Schedule health↓ then
   Impact level↑**; *Grooming* → **also toggle the `Type` column on by hand** (`issue_type`
   can't be set via `visible_fields`). `scaffold-repo` later **verifies** each view resolves
   its group/slice.
3. **Global field order.** Drag the project's fields (**Settings → Fields**) into the
   canonical order in [`fields.json`](templates/project/fields.json) `field_display_order`
   — there's no field-position API. It governs the field palette and any non-customized
   view; each view's own columns already override it. Carried by `copyProjectV2`.
4. **The 3 Insights charts.** No API at all — build per
   [`insights.md`](templates/project/insights.md). Chart **history accrues per board
   from day one, is never backfilled, and is never copied**, so define Status + Sprint
   before adding items or the historical charts start blank.

*(The script already marked the Project an org template — `markProjectV2AsTemplate` —
so `scaffold-repo --template "…"` and the org→org copy can find it.)*

> **Default org issue fields (e.g. `Effort`):** GitHub seeds some default org issue
> fields. gh-projects uses **only** `Type` / `Priority` / `Start date` / `Target date`
> and ignores extras. Deleting an unused `Effort` now — while the org has no issues
> (deleting a field drops values already set) — keeps it from competing with the `Size`
> *appetite* field (S/M/L, *not* points). Optional; the plugin ignores it either way.

---

## Phase 0.3 — Onboard another org (org→org copy, once per new org)

When you add a second org (e.g. `acme`), don't rebuild by hand — copy zilarent's
template into it. Do this as **your org-owner auth** (you need read on zilarent's
template + project-create on the destination org; the per-org App token can't reach
across orgs).

```bash
# destination org node id
gh api graphql -f query='query($l:String!){organization(login:$l){id}}' -f l=acme
# copy zilarent's template into acme (same mutation scaffold uses, lib/gh.py)
gh api graphql -f query='
  mutation($owner:ID!, $src:ID!, $title:String!) {
    copyProjectV2(input:{ownerId:$owner, projectId:$src, title:$title, includeDraftIssues:false}) {
      projectV2 { id number url }
    }
  }' -f owner=ACME_ID -f src=ZILARENT_TEMPLATE_PROJECT_ID -f title="GitHub Projects Golden Template"
```

Then, in `acme`:

1. Run the same script against the copied project — it creates the org `Type` + Issue
   Fields (which the copy does **not** carry — they're org-wide), **adds the org
   columns**, **marks the copy a template**, and **skips** the project fields/views the
   copy already brought:
   ```bash
   python3 "$SB" --org acme --project-number <copied#> --apply
   ```
   The Issue-Field-dependent views only resolve once the org fields exist;
   `scaffold-repo`'s `verify_views` **fails loudly** otherwise, so do this before
   scaffolding a board in acme.
2. **Eyeball the 3 charts** (Insights has no API to verify; rebuild any that didn't
   carry from `insights.md`).

The project fields + the 8 views carry across in the copy; only the org-level taxonomy
and (possibly) the charts are per-org work.

---

## After the template: scaffold real boards

With the org's template in place, standing up a board is one command. `scaffold-repo`
is a **skill** name, not a CLI binary — the runnable engine behind it is
`lib/scaffold.py` (`scaffold` subcommand). Run it directly, the same way you ran
`setup_board.py` above, but with the **org's App token** in your env (`GH_APP_TOKEN`,
or `APP_ID` + `APP_PRIVATE_KEY[_PATH]`), **not** your user auth — every board write
goes through the App installation token.

> ⚠️ **Run it from inside the local checkout of the repo the board is for.** When you
> pass `--repo owner/name`, scaffold installs the per-repo automation (`.github/…` +
> `project/…`) into the **current working directory** (`--repo-dir` defaults to CWD).
> Run it from anywhere else — e.g. this agentic-coding checkout — and those files get
> written into the **wrong tree**. So `cd` into that repo's clone first. Because of
> that `cd`, capture the engine path as an **absolute** path *before* you move (the
> `git rev-parse` below resolves against agentic-coding, not the target repo):

```bash
# 1. Capture the engine path ABSOLUTELY — run this once, from your agentic-coding checkout:
SCAFFOLD="$(git rev-parse --show-toplevel)/claude-code/plugins/gh-projects/lib/scaffold.py"

# 2. cd into the LOCAL CLONE of the repo the board will exist in (owner/name):
cd /path/to/your/clone/of/owner-name

# 3. Preview the full change manifest (mutates nothing):
python3 "$SCAFFOLD" scaffold --org <login> --template "GitHub Projects Golden Template" \
  --title "<new board title>" --repo owner/name [--team <slug>]
# 4. Apply it (only after reviewing the manifest):
python3 "$SCAFFOLD" scaffold --org <login> --template "GitHub Projects Golden Template" \
  --title "<new board title>" --repo owner/name [--team <slug>] --force
```

> Standing up a board with **no** repo files (just the Project) is the one case you can
> run from anywhere: omit `--repo` (and `--team`). With `--repo` set, location matters —
> alternatively pass `--repo-dir /path/to/clone` explicitly instead of `cd`-ing.

It `copyProjectV2`s the template (**idempotent** — a re-run reuses the existing
same-titled board instead of creating a duplicate), re-resolves IDs against the copy,
ensures the org Issue Type + Issue Fields, re-plans the Sprint iterations, links the
repo (and team), sets the no-squash merge setting, and installs the per-repo automation
into the current repo. **Dry-by-default** — the first command prints the manifest and
changes nothing; the second (`--force`) applies it. `--repo` must be `owner/name` (a
bare repo name is rejected up front). It **verifies** the field schema (diffed against
`fields.json`) and each view's presence + filter/group/slice resolution — a board view
grouped by the default **Status** column and a slice by the **Type** issue-type field
can't be read back via the API, so those surface as **confirm-by-eye** checklist items
rather than failures; it also **cannot** verify charts (no API) — hence the eyeball step.

> `scaffold-repo` installs the workflow **files** but does **not** set any Actions
> secrets or variables — that's the manual step next, and it's why the board variables
> couldn't be set back in Phase 0.0: the board didn't exist yet.

### Wire the board's CI variables

`scaffold-repo` reported the new board's **number** and **URL** in its manifest. Set
these variables so the installed workflows target it — **the same way (Path A / Path
B) you stored the App secrets** in Phase 0.0 (step "Store the App secrets"):

- `GH_PROJECT_OWNER` = the org login (`zilarent`)
- `GH_PROJECT_NUMBER` = the board number scaffold reported
- `GH_PROJECT_URL` = `https://github.com/orgs/zilarent/projects/<number>`

```bash
# Path B (Free org) — per board repo. N / the URL come from scaffold's output.
R=zilarent/your-repo
gh variable set GH_PROJECT_OWNER  --repo "$R" --body "zilarent"
gh variable set GH_PROJECT_NUMBER --repo "$R" --body "N"
gh variable set GH_PROJECT_URL    --repo "$R" --body "https://github.com/orgs/zilarent/projects/N"
```

> **Free org:** if you deferred the App **secrets** from the Phase 0.0 "Store the App
> secrets" step, set them on this same repo now too (the two `gh secret set --repo` lines). Everything just needs to be
> present before a workflow first triggers.

---

## Maintenance — change the template, then propagate per board

The template is the source of truth: make a field/view/chart change on the **canonical
template** (and keep `templates/project/*` in sync) — never edit a board ad-hoc, which
drifts it out of parity. But a template change does **not** auto-update existing boards
(`copyProjectV2` is a one-time copy, and views are create-only). How you propagate it
depends on whether the board holds real data.

### A board is NOT just a projection of its issues — deleting it loses data

Some data lives on the **issue** (survives a board deletion); some lives **only on the
board** (gone with it). The `home: project` fields store their **values on the project
item, not the issue** — so a recreated board resets them.

| Data | Where it lives | On board delete |
|---|---|---|
| the issue · labels · assignees · **Milestone** · **Type** · **Priority / Start date / Target date** (org issue fields) · linked branch/PR · parent/sub-issue · blocked-by edges | the **issue** | ✅ survives |
| `Schedule health` · `Slippage` / `Slippage days` · `Blast radius` / `Blast count` · `Blocked` | project values, **auto-derived** | ♻️ recompute with `sync-signals` |
| **`Status` · `Size` · `Tier` · `Sprint` · `Impact level` · `Decision needed` · `PM-ID` · `Spec`** | project item values only | ❌ **lost** |
| draft issues · **Insights chart history** · manual rank/order · archive state | the board only | ❌ **lost** |

`Status` is the sharpest edge: a recreated board resets every item to `Backlog`, and
`board-sync` only re-fires on *new* push/PR events — so already-merged or in-flight work
won't repopulate.

### Propagating a template change

- **The template itself, or an empty/brand-new board** → **delete + recreate freely**
  (no data to lose).
- **An active board with real issues** → **don't nuke it. Apply the delta in place:**
  1. New / changed fields or columns — re-run the script against the board (idempotent +
     additive, preserves existing values):
     `python3 "$SB" --org <org> --project-number <board#> --apply`
  2. Changed views only — delete **just those views** in the UI, then re-run the script
     to recreate them (views hold no data; the script flags which are stale).
  3. `sync-signals` to recompute the auto signals.

  That adopts the new schema/views while keeping `Status`/`Size`/`Tier`/`Sprint`/`Impact`/
  `Decision`, draft issues, and chart history.

---

## Checklist

**Once, ever — the canonical template in zilarent:**
- [ ] **GitHub App** created, permissions set, webhook off, private key saved, installed on zilarent (Phase 0.0)
- [ ] App **secrets** stored (`GH_APP_ID` + `GH_APP_PRIVATE_KEY`) — **org-level** (paid: Path A) **or** **per private repo** (Free: Path B); board *variables* come after the board exists
- [ ] `gh auth refresh -s project,admin:org` (as a **zilarent owner**)
- [ ] `setup_board.py --org zilarent --title "…" --apply` → project (private) + `Type` + issue fields + all project fields incl. **Sprint** + org columns + 8 views with visible columns + **marks it the template**
- [ ] **UI punch-list** (Phase 0.2 Step 2): replace **Status** options **+ colors** (delete the shipped 3, add the 6, default = `Backlog`) · finish view grouping/slice/sort/**column-order** per `views.md` (incl. Triage's Schedule-health column order + the Grooming **Type** column) · set the **global field order** (`field_display_order`) · build **3 Insights charts**

**Once per additional org (e.g. acme):**
- [ ] **GitHub App** created + installed on the new org, secrets/variables stored (Phase 0.0 — the App is per-org)
- [ ] `copyProjectV2` zilarent template → the new org (as your org-owner auth)
- [ ] `setup_board.py --org <new> --project-number <copied#> --apply` → org `Type` + fields + columns + **marks the copy a template** (skips copied fields/views)
- [ ] **Eyeball the 3 charts**; rebuild any that didn't carry

**Per repo/board:**
- [ ] **From inside the board repo's local clone** (`cd` there first — per-repo files install into CWD): `python3 "$SCAFFOLD" scaffold --org <org> --template "…" --repo owner/name … --force` (creates the board + installs workflow files; uses the org's App token — `$SCAFFOLD` = absolute `…/gh-projects/lib/scaffold.py` captured in the agentic-coding checkout, dry-run first)
- [ ] **Wire the board variables** (`GH_PROJECT_OWNER` / `GH_PROJECT_NUMBER` / `GH_PROJECT_URL`) from scaffold's reported board number — org-level (Path A) or per repo (Path B)
- [ ] *(Free org)* if App secrets were deferred, set them on this repo too (Phase 0.0 "Store the App secrets" Path B)

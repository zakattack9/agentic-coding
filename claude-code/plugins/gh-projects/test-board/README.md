# test-board — disposable mock board (dev-only)

Stands up a throwaway copy of the golden-template Project (#7) filled with a
coherent backlog of mock issues in `Zilarent/cars.bdv`, so you can eyeball how the
views / fields / charts look with live-ish data. **Not part of the shipped plugin**
— this whole directory is gitignored.

## Use

```bash
cd claude-code/plugins/gh-projects/test-board

python3 seed_test_board.py --dry-run   # preview the plan + data distribution
python3 seed_test_board.py             # create the board + ~23 mock issues

# ... eyeball the board in the UI ...

python3 teardown_test_board.py --dry-run   # list what would be deleted
python3 teardown_test_board.py             # delete the board + every mock issue
```

Auth: run as **yourself** with `gh auth` granting `project` + `admin:org` (same as
`setup_board.py`). Everything goes through the `gh` CLI.

## What seed creates

- A fresh **private** test Project, `copyProjectV2` off template #7
  (`[TEST] cars.bdv Mock Board`). The copy carries all project fields + the 8 views.
- **Sprint iterations** anchored around *today* (Sprint 2 = `@current`), so the
  sprint-filtered views actually resolve.
- **~23 mock issues** spanning every `Status`, `Priority`, `Tier`, `Size`, `Type`,
  and 6 sprints, each with the full signal spread (`Schedule health`, `Slippage`,
  `Blast radius`, `Impact level`, `Decision needed`, dates, `PM-ID`, `Spec`).
- **2 Epics** with sub-issues (feeds the Sub-issues % rollup) and a **blocked-by
  DAG** (feeds `Blocked` / `Blast radius` / the Critical-Path view).

Everything created is recorded in `manifest.json` (also gitignored). Teardown reads
it and only ever deletes what it recorded — the golden template (#7), the repo's
labels, and any pre-existing issue are never touched.

## Notes

- The org `Status` options, view grouping/slice/sort, and the Insights charts are
  inherited from #7 by the copy (they are UI-only, per `GOLDEN-TEMPLATE-SETUP.md`).
- **Charts accrue history per board from day one and are never backfilled** — a
  freshly-seeded board's historical/burn-up charts will look sparse until time
  passes; the snapshot-style charts populate immediately.
- Org **issue fields** (`Priority` / `Start date` / `Target date`) are written via
  the `updateIssueFieldValue` mutation (the project-item path rejects them); the
  other fields use `updateProjectV2ItemFieldValue`. Both paths are in
  `seed_test_board.py`.
- To retarget another org/repo/template, edit the constants at the top of
  `seed_test_board.py`.

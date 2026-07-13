# Backtracking implementation and verification map

This map ties every acceptance criterion in the ParaQwen backtracking spec to
its implementation and executable evidence. The referenced live and processor
reports are pinned artifacts; `benchmarks/verify_results.py` replays every
recorded outcome predicate and verifies source, model, baseline, comparison,
and performance integrity.

| AC | Implementation | Verification evidence |
| --- | --- | --- |
| 1 | Pre/Post stdin contains only the current Spokenly dictation; no application-control API exists. | `README.md`; corpus and entrypoint tests |
| 2 | `repair_protocol.py` classifies replacement, restart, restatement, discard, additive/preserve. | `test_repair_protocol.py`; corpus categories |
| 3 | `CUE_PATTERN`, `RESTART_CUE`, and typed cue records cover the required forms. | `test_required_explicit_cues_are_typed`; live report |
| 4 | `_restatement_candidates` requires adjacent structural parallelism. | positive restatement corpus; weak-similarity test |
| 5 | Overlapping candidates merge to a `chain` with ordered cues. | chain tests and 100% live chain rate |
| 6 | Non-overlapping regions retain textual sequence and source offsets. | independent-region test and corpus |
| 7 | Clause bounds tolerate punctuation, capitalization, and line boundaries. | ASR-boundary punctuation test; punctuation corpus |
| 8 | Context filters and Tier 3 preservation reject natural cue uses. | natural-cue tests; 100% live preservation |
| 9 | `literal_spans` shields quotes, explicit literals, and reported speech. | quoted/reported tests and corpus |
| 10 | Single-word/emphasis repetition is excluded from deterministic deletion. | deliberate-emphasis test and corpus |
| 11 | Ambiguous candidates are recorded as required-preservation spans. | ambiguous-span validation test |
| 12 | Regions have sequential IDs, type, offsets, nonce, and digest. | region identity test |
| 13 | Sorted overlap merge creates non-overlapping chain/independent regions. | chain and independent-region tests |
| 14 | `_replacement_bounds`, `_restart_bounds`, and paragraph limits bound scope. | paragraph-bound test |
| 15 | `_validate_structure` enforces exact once/in-order boundaries and consumed cues. | corruption and cue-leak tests |
| 16 | Raw token namespace text becomes nonce-bound `SPK_LITERAL` shields. | literal collision/restore tests; adversarial corpus |
| 17 | Spokenly is configured for Reasoning None/temperature zero; benchmark sends `think=false`; no retry path exists. | setup/prompt tests; live report |
| 18 | Prompt decision procedure requires later-source grounding and preserves additive/ambiguous text. | prompt test and live report |
| 19 | Prompt contains evidence-backed framed examples for every required case. | prompt example test |
| 20 | Post validates repair, snippet, file-reference, count/order/nonce/checksum structure. | `validate_model_output`, `expand`; corruption tests |
| 21 | `extract_protected_atoms` and occurrence comparison protect every listed atom class. | protected-atom tests; technical corpus |
| 22 | Output atom counts cannot exceed verified source/expansion counts. | invented command/reference tests |
| 23 | `atom_key` permits narrow case/punctuation/number equivalence. | numeric equivalence tests |
| 24 | Linear token and bigram alignment gates meaningful prose outside regions. | insertion/deletion tests; performance report |
| 25 | Any validator exception selects persisted deterministic source recovery. | damaged-region entrypoint test |
| 26 | Outer recovery returns safe source/raw text with exit zero and private logging. | entrypoint recovery tests |
| 27 | `rstrip()` is applied in expand, validation, recovery, slash restoration, and all stdout branches. | whitespace tests and zero live safety failures |
| 28 | Diagnostics use private files; stdout contains transcript only. | diagnostic and entrypoint stderr/stdout tests |
| 29 | Existing segment reconstruction keeps every non-target expansion in its indexed slot. | processor and file-reference suites |
| 30 | `deterministic_protected_repairs` drops proven trigger alternatives before manifest creation. | protected-trigger correction test; 100% expansion-intersection rate |
| 31 | Unproven expansion repairs remain in the source/manifest. | additive protected-trigger test |
| 32 | Existing directive, expansion, plugin, recovery, and whitespace suites remain green. | full offline suite |
| 33 | `backtracking-corpus-v1.json` has 126 reviewed records with 66 positive repairs and 60 negative/ambiguous cases. | corpus schema test |
| 34 | Positive corpus has all required repair, technical, expansion, and long categories. | corpus validator |
| 35 | Negative corpus has all required natural, literal, additive, repetition, incomplete, and adversarial categories. | corpus validator |
| 36 | Offline protocol/parser/validator/recovery fixtures require no model or network. | full offline suite |
| 37 | Three complete local-model runs achieved 95.96% positive and 100% negative preservation with reasoning disabled. | `backtracking-live-summary-v1.json` |
| 38 | All 378 live outcomes had zero token, atom, relocation, invention, and whitespace safety failures. | live summary and verifier |
| 39 | Same-model pre-change 65.15% positive rose to 95.96%; worst category regression is 0 points. | `backtracking-comparison-v1.json` |
| 40 | Every corpus category includes a reviewed `spokenly_parakeet` record. | corpus validator |
| 41 | Combined processor p95 is 111.68 ms and max baseline ratio is 1.212. | `processor-performance-v1.json` |
| 42 | Opt-in diagnostics are private, redacted, bounded to 20/seven days, and store no audio. | `diagnostics.py`; diagnostic tests |
| 43 | README, setup, and inline-command docs cover behaviors, failure rules, privacy, one pass, and pause limits. | documentation tests/review |
| 44 | Atomic fsync/replace state is mode 0600, UID/nonce/schema/age checked, and consumed once. | state integrity tests |
| 45 | State-write failure strips repair framing and continues safely. | persistence-failure entrypoint test |
| 46 | Cue punctuation is consumed locally without modifying protected punctuation. | punctuation fixtures; snippet/technical suites |

## Verification commands

```bash
python3 -m unittest discover -s dictation/spokenly/tests -v
python3 dictation/spokenly/benchmarks/run_backtracking_benchmark.py
python3 dictation/spokenly/benchmarks/benchmark_processors.py --iterations 40
python3 dictation/spokenly/benchmarks/verify_results.py
```

The live release command is intentionally separate:

```bash
python3 dictation/spokenly/benchmarks/run_backtracking_benchmark.py --live --runs 3
```

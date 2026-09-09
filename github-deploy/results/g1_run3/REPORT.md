# G1 run 3: state-machine fixtures (SPEC_AMENDMENTS A2, 2026-09-08)

*`run_synthetic*.py`, `runs*/`, `verification/V1d*` and `est/controller.py.bak_preA3` cited below are working files from the build that are not included in this repository; the tables and `baselines.json` in this directory carry the results.*

Owner direction (2026-09-08, verbatim): "G1 is supposed to check that the scoring works: a strong participant should score higher than a medium one, who should beat a weak one. It failed twice and both times the cause was the Haiku-scripted 'strong' participant not following its own script." The scripted participants are test fixtures, not the system under test. This run replaces the fixtures only.

## What changed and what did not

Changed (fixtures only):
- New module `est/participants_v2.py`: deterministic state-machine fixtures. A Python policy decides every turn's action; Haiku only (a) enumerates categories once from the public task prompt, (b) phrases each pre-decided action as a short chat message, and (c) for STRONG runs a per-turn checker over the visible conversation (was each asked category answered with a concrete record; do any stated figures fail to reconcile). Isolation: a fixture receives only the public task prompt, a nonce and the visible transcript; the module imports nothing from `est.items`, `est.controller` or `est.scorer` (stated in the module docstring and in `run_synthetic_v3.py`).
- New driver `run_synthetic_v3.py`: copy of `run_synthetic.py` using the v2 fixtures, writing `runs_v3/` and `results/g1_run3/{table.md,baselines.json}`. The aggregation and G1a/G1b block is byte-identical to `run_synthetic.py` apart from one comment line (checked with `diff` before launch). It also records `fixture_plan`, `n_llm_calls` and `wall_s` in every run record and `results/g1_run3/run_meta.json`.

Not changed: `SPEC.md` (gates G1a, G1b), `est/scorer.py`, `est/controller.py`, `est/llm.py`, `est/participants.py`, `run_synthetic.py`, `results/table.md`, `results/baselines.json`, `runs/*.json` (all v1/v2 run files preserved, mtimes still 2026-09-07; the `runs/` directory mtime is 2026-09-08 only because other sessions added subdirectories `human/`, `rank_cache/`, `human_modal_mirror_20260908/`). `est/controller.py` was not changed by this work; see note 9 for the concurrent A3 timing-only edit.

Fixture design as run (code sha1 at grid launch in `code_sha1_at_grid_launch.txt`, identical to the current files):
- STRONG (max 10 turns): turn 1 Haiku enumerates 7 categories (capped at 8) with example record types; the fixed category "reports from other people in the lab: lab chat, notes or messages from other users, anyone else having the same problem or trouble with anything shared" is inserted at position 2 so it is asked on turn 1. Turns 1 to 9: up to two actions per turn chosen by the policy (ASK a new category naming concrete records; REASK, more pointedly, any category the checker marked unanswered, at least two turns after the previous ask, other-reports first; CHALLENGE quoting two figures the checker flagged, at most two challenge turns, each taking one of the two slots; spare slots go to a third ask of anything still unanswered, and this spare-slot ask requires only a one-turn gap, so consecutive-turn asks of the same category do occur late in a run). Turn 10: SWEEP naming every category still open. Adherence guard: if the phrased message lacks a keyword of a scheduled category (or the challenged figures), the template sentence for that part is appended (`message_source` = `llm+patch`); empty or overlong LLM output falls back to the template.
- MEDIUM (max 6): Haiku enumerates 6 plain-language "things" (1 to 4 words, SPEC examples "the equipment", "the ingredients"); one "could it be something with the X?" question per turn; a regex guard rejects messages that name records, logs, readings, amounts, settings, dates or lots (template fallback); never re-asks, never checks numbers. If enumeration fails, a fixed generic list is used (the equipment, the reagents, the starting material, the protocol, storage conditions, contamination).
- WEAK (max 2): turn 1 Haiku writes a broad restatement (no cause named); turn 2 is one of three fixed "anything else? what should we do?" variants chosen by nonce hash.
- Submissions: `SUBMIT_SYS` imported unchanged from `est/participants.py` (STRONG itemised with exact figures plus "Inconsistencies noticed"; MEDIUM bullets; WEAK 3 to 5 sentences; "Do not add facts that were not in the conversation"), Haiku.

## Pre-flight smoke runs and the two changes made after them (disclosure)

Before the grid, three smoke runs (pcr_lab seed 1, all three policies) and one further MEDIUM smoke run (cell_culture seed 2) were executed into a scratch directory; they are preserved in `results/g1_run3/smoke_preflight/` together with the pre-change fixture source (`participants_v2.preflight.py`). Observations and the two edits made before launching the grid:
1. MEDIUM smoke (pcr_lab s1, composite 0.57, specificity 1.0): Haiku's categories were phrased as measurements/settings ("Template DNA concentration or quality", "Cycling annealing temperature setting") and the per-turn judge rated "maybe the concentration is too low" and "annealing temperature setting" as `specific`, unlocking both T2 components. SPEC MEDIUM is defined as asking in plain terms and not asking for records (v1 prompt examples: "could it be the equipment?"), and V1c Finding 4 had already flagged MEDIUM T2 unlocks as above design intent. Edit: MEDIUM enumeration now asks for the thing itself in 1 to 4 everyday words, the phrasing instruction forbids amounts/concentrations/temperatures/settings/dates/lots/records, and the guard regex was widened; category names are stripped of such words. The MEDIUM re-smoke (cell_culture s2) then asked "Could it be something with the serum / incubator / media / water / cryo-stock / plasticware?" and scored 0.32.
2. STRONG smoke (pcr_lab s1, composite 1.00): the checker marked categories "unanswered" when the assistant had supplied one concrete record but not every record the participant listed, producing redundant re-asks. Edit: checker instruction now counts a category as answered if at least one concrete lab-specific record was given.
No scorer, controller, judge prompt or gate was touched. These edits were made after seeing fixture behaviour on one item/seed each, before any grid run; the smoke outputs are kept as negative/positive results.

## Results (from `results/g1_run3/table.md` and `baselines.json`, 18/18 runs, backend cli)

Pooled (mean over 3 items x 2 seeds):

| policy | n | coverage | specificity | refusal_recovery | verification | uptake | composite |
|---|---|---|---|---|---|---|---|
| WEAK | 6 | 0.27 | 0.00 | 0.00 | 0.00 | 0.50 | 0.15 |
| MEDIUM | 6 | 0.80 | 0.08 | 0.00 | 0.17 | 0.88 | 0.39 |
| STRONG | 6 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

For comparison, v2-fixture pooled table (results/table.md, unchanged): WEAK 0.33/0.08/0.00/0.00/0.61 (0.21), MEDIUM 0.77/0.67/0.00/0.17/0.74 (0.47), STRONG 0.87/0.50/0.50/0.83/0.97 (0.73).

Per item (mean over seeds):

| item | policy | n | coverage | specificity | refusal_recovery | verification | uptake | composite |
|---|---|---|---|---|---|---|---|---|
| cell_culture | WEAK | 2 | 0.60 | 0.00 | 0.00 | 0.00 | 0.50 | 0.22 |
| cell_culture | MEDIUM | 2 | 0.70 | 0.00 | 0.00 | 0.50 | 0.88 | 0.42 |
| cell_culture | STRONG | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| pcr_lab | WEAK | 2 | 0.20 | 0.00 | 0.00 | 0.00 | 1.00 | 0.24 |
| pcr_lab | MEDIUM | 2 | 0.90 | 0.00 | 0.00 | 0.00 | 1.00 | 0.38 |
| pcr_lab | STRONG | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| western_blot | WEAK | 2 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| western_blot | MEDIUM | 2 | 0.80 | 0.25 | 0.00 | 0.00 | 0.75 | 0.36 |
| western_blot | STRONG | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

Per-item composites (4 dp): cell_culture STRONG 1.0000 > MEDIUM 0.4150 > WEAK 0.2200; pcr_lab 1.0000 > 0.3800 > 0.2400; western_blot 1.0000 > 0.3600 > 0.0000.

Per-run composites: STRONG 1.00 x 6; MEDIUM 0.31, 0.52 (cell_culture), 0.36, 0.40 (pcr_lab), 0.36, 0.36 (western_blot); WEAK 0.30, 0.14 (cell_culture), 0.24, 0.24 (pcr_lab), 0.00, 0.00 (western_blot).

## Gate G1 (exactly as computed by the unchanged gate code; `baselines.json["_gate_G1"]`)

```
{"G1a_composite_ordering_every_item": true, "G1b_subscale_monotone_pooled": true, "G1_pass": true, "n_runs": 18, "expected_runs": 18}
```

G1b per subscale (pooled S >= M >= W and S > W): coverage 1.00 >= 0.80 >= 0.27 pass; specificity 1.00 >= 0.083 >= 0.00 pass; refusal_recovery 1.00 >= 0.00 >= 0.00 pass; verification 1.00 >= 0.167 >= 0.00 pass; uptake 1.00 >= 0.875 >= 0.50 pass.

Statement required by the owner: G1 passes on this run. The gate definition (SPEC.md G1a, G1b), the scorer and the controller were unchanged; only fixture script adherence changed. This was an owner-directed change dated 2026-09-08 ("both times the cause was the Haiku-scripted 'strong' participant not following its own script"). The v1 and v2 fixture results, both G1 FAIL, remain in `results_v1_mixed_domains/`, `results/table.md`, `results/baselines.json` and `runs/`.

## Script adherence (from `fixture_plan` in each run record; computed by `results/g1_run3/adherence_check.py`, output `adherence.json`)

STRONG, per run:

| run | categories asked / total | re-ask needed (checker said unanswered after first ask) | re-asked later | every unanswered category re-asked | other-reports ask turns | >= 2 asks | checker flagged figures (after turns) | challenge turn | challenged after first flag | judge credited challenge | C7 released at turn | CFIX turn |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cell_culture s1 | 8/8 | 4 | 4 | yes | 1, 3 | yes | 1,3,4,7 | 2 | yes | yes | 3 | 2 |
| cell_culture s2 | 8/8 | 3 | 3 | yes | 1, 3 | yes | 1,6 | 2 | yes | yes | 3 | 2 |
| pcr_lab s1 | 8/8 | 4 | 4 | yes | 1, 3 | yes | 1 | 2 | yes | yes | 3 | 2 |
| pcr_lab s2 | 8/8 | 3 | 3 | yes | 1, 3 | yes | 1,2,3,7,8,10 | 2 | yes | yes | 3 | 2 |
| western_blot s1 | 8/8 | 3 | 3 | yes | 1, 3 | yes | 1,2,3,4,6,7,9,10 | 2 | yes | yes | 3 | 2 |
| western_blot s2 | 8/8 | 3 | 3 | yes | 1, 3 | yes | 1 to 9 | 2 | yes | yes | 3 | 2 |

Summary: 6/6 STRONG runs re-asked every category the checker marked unanswered; 6/6 asked the other-reports category on two separate turns (1 and 3) and C7 was released at turn 3 in every run; 6/6 issued a challenge on the turn after the checker first flagged non-reconciling figures (always after turn 1, challenge on turn 2) and the frozen judge set `challenges_error` true on that turn in 6/6; all 6 STRONG submissions were also flagged `flags_inconsistency` true by the submission judge. All STRONG runs used exactly 10 participant turns; message source was `llm` for 57/60 STRONG turns and `llm+patch` (template sentence appended by the adherence guard) for 3/60. Only one challenge turn was used per run (the policy allows two); later checker flags were not acted on: in pcr_lab s2 and cell_culture s1 they repeated the already-challenged figure pair, while in western_blot s1 (turns 7, 10) and s2 (turns 5, 7) the checker flagged a different pair (BCA loading "1.2 ug per lane" vs "roughly 1/20th to 1/25th of standard", which is the assistant's own rounding, not a planted error) and the fixture's dedupe suppressed it because it treats any digit-token overlap with an earlier challenge as already challenged (a known coarseness of `participants_v2.py`; verification was already 1.0 from turn 2, so no score is affected; see `fixture_plan.turns[*].checker` and verification/V1d_numbers_v3grid.md Finding 6).

MEDIUM: 6/6 runs asked each category at most once (never re-asked), 6 turns each, no chat challenge in any run (`challenged_in_chat` false in all); message source `llm` for 30/36 turns and `llm+patch` for 6/36 (the guard appended "Could it be something to do with X?" when Haiku's sentence did not contain the category keyword, which produces a visibly doubled question in those turns). In 2/6 MEDIUM runs (pcr_lab s2, western_blot s1) Haiku refused the enumeration call (returned a "cannot_complete / awaiting_lab_data" JSON, recorded in `fixture_plan.enumeration_raw`) and the fixed generic category list was used. MEDIUM verification 0.17 comes from one run (cell_culture s2) whose submission was flagged `flags_inconsistency` by the submission judge; MEDIUM specificity 0.083 is one T2 unlock (western_blot s2 turn 6, "Could it be something with the imager?" rated specific for C6 by the frozen judge).

WEAK: 6/6 runs used exactly 2 turns (turn 1 `llm`, turn 2 `template`).

## Honest notes and known gaps

1. STRONG is now at ceiling (1.00 on every subscale in every run). The gate only tests ordering, which is satisfied, but a saturated fixture cannot show whether the scorer discriminates among strong-but-imperfect participants. The v2 grid (STRONG 0.73) remains the evidence for that regime.
2. Judge anomalies (frozen judge, log is ground truth, reported not corrected): cell_culture WEAK s1 turn 2 "Ok thanks. Anything else? What should we do?" was rated `general` for all of C3 to C7 (coverage 1.0 for a WEAK run, composite 0.30 vs MEDIUM s1 0.31 on the same item); the same template in cell_culture WEAK s2 and pcr_lab WEAK s1/s2 was rated C7 general only, and in western_blot none. This is the IF-2 catch-all issue recurring; it narrows the cell_culture MEDIUM-WEAK composite margin to 0.415 vs 0.220 (per seed 0.31 vs 0.30 for s1).
3. western_blot WEAK scored 0.00 in both seeds because the WEAK submissions were generic and the submission judge found neither C1 nor C2 conveyed (uptake 0/2). That is a legitimate outcome of the WEAK script plus the v1 submission prompt, not an error; submissions are non-empty.
4. MEDIUM specificity fell from 0.67 (v2 fixtures) to 0.08 (v3) because the v3 MEDIUM fixture asks only in plain terms, per SPEC. Anyone comparing v2 and v3 MEDIUM rows should read this as a fixture change, not a scorer change.
5. The two pre-flight edits above were informed by smoke behaviour on pcr_lab s1 / cell_culture s2. They change fixture fidelity to the SPEC policy text, not scoring, but they were not blind; smoke artifacts are preserved for inspection.
6. Seeds are prompt nonces (CLI backend has no sampling seed); n = 2 per cell.
7. G2 (judge accuracy) was not re-measured on v3 transcripts.
8. Independent verification: a fresh-context verifier (V1d, 2026-09-08, no LLM calls, re-implemented from SPEC.md) re-derived every number in this report from `runs_v3/`: 108/108 per-run subscale cells, 72/72 `baselines.json` and `table.md` cells, G1a/G1b/G1 verdict agreeing with `_gate_G1`, 0 unlock-rule mismatches, 0 turn-cap violations, every cell of the STRONG adherence table, 0 participant-message leak hits, gate block identical to `run_synthetic.py` except one comment, and `results/table.md` / `results/baselines.json` unchanged. Verdict "VERIFIED WITH ISSUES": three wording imprecisions (its Findings 6, 7, 8), now corrected in this file, and no numerical contradiction. Report: `verification/V1d_numbers_v3grid.md`; work files `verification/V1d_work/`.
9. Controller version: a concurrent session applied SPEC amendment A3 to `est/controller.py` at 2026-09-08 09:48:51 (backup `est/controller.py.bak_preA3`), before the smoke runs (09:52) and the grid (10:11). `diff` shows A3 touches only the hosted participant-time clock, `status()` fields and two extra per-turn log fields (`latency_s`, `participant_elapsed_s`); `_judge`, `_apply_unlocks`, `_assistant_reply` and the unlock rules are identical, and synthetic runs use `wall_seconds=None`, so scoring is unaffected. The v3 run records therefore carry the two extra log fields that v2 records lack.
10. `SPEC_AMENDMENTS.md` was being edited by that session during this work (A3, A3.1, A3.2); A2 was appended at the end of the file and is therefore out of numeric order.

## Cost and paths

- Grid wall time: 2113.7 s (35.2 min) for 18 runs in one process, EST_CONCURRENCY=4, 6 worker threads; sum of per-run wall 9202.7 s. Pre-flight smoke: about 15 min + 3 min.
- LLM calls: 426 in the grid (STRONG 43 per run: 1 enumerate + 10 phrase + 10 checker + 10 judge + 10 assistant + 1 submission + 1 submission-judge; MEDIUM 21; WEAK 7), plus 92 in pre-flight smoke runs (71 + 21). Counted by a wrapper around `est.llm.complete` in `run_synthetic_v3.py`; `est/llm.py` unchanged.
- Written: `est/participants_v2.py`, `run_synthetic_v3.py`, `runs_v3/*.json` (18) and `runs_v3/grid.log`, `results/g1_run3/{table.md, baselines.json, run_meta.json, REPORT.md, adherence_check.py, adherence.json, code_sha1_at_grid_launch.txt, smoke_preflight/}`, `SPEC_AMENDMENTS.md` (A2 appended).

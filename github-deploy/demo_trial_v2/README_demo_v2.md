# demo_trial_v2: second simulated uplift trial (non-circular design)

Written 2026-09-08 by a fresh agent after `analyze_trial.py --trial-dir demo_trial_v2` had run. Nothing here is human data. Every number below is traceable to a named file under `demo_trial_v2/` (paths relative to the workspace root). The generator scripts (`make_demo_trial_v2.py`, `make_demo_ceilings_v2.py`) and their raw outputs (`sessions/`, `ceiling_cache/`, `pretest_transcripts.jsonl`, `transcripts_with_pretest.jsonl`) are not shipped; the pipeline inputs (`participants.csv`, `transcripts.jsonl`, `tasks.yaml`, `ceilings.jsonl`, `truth.json`), the judge cache and `results/` are. An independent re-derivation is pending in `verification/V26_demo_trial_v2.md`.

## 1. Purpose

Owner instruction, verbatim (`demo_trial_v2/JOURNAL.md`, 2026-09-08): "i wanted you to fix the simulated trial to not be circular."

"Circular" in the first demo (`demo_trial/`, described in `README.md` lines 332-350 and 392-399 and in `demo_trial/results/trial_report.md`) meant two things. First, the pre-test EST scores in `participants.csv` and the in-trial transcripts were both produced by the same three scripted policies in `est/participants.py`, and the 108 LLM-arm sessions were 18 unique synthetic transcripts assigned by tier, so predictive validity (r 0.94), per-stratum effects, rank stability and the learning curve were identities of construction and n=36 was pseudo-replication of six policy profiles. Second, the `expert` ceiling was the scripted STRONG policy, and its records were hash-identical to 30 of the 108 LLM-arm sessions, so the human-ceiling elicitation ratio was circular as well.

## 2. Design

Source: `make_demo_trial_v2.py`, `est/persona.py`, `make_demo_ceilings_v2.py`, `demo_trial_v2/design.json`, `demo_trial_v2/truth.json`.

| element | value | where |
|---|---|---|
| participants | 48 simulated persons, 24 `llm`, 24 `control` (arm list shuffled with `random.Random(20260908)`) | `design.json`, `participants.csv` |
| latent model | `trait_k = logistic(0.9*g + 0.6*e_k + offset_k); g, e_k ~ N(0,1)`; offsets decompose 0.0, ask_specific 0.0, persist -0.3, verify -0.4, synthesise 0.3 | `design.json` `model` |
| traits | decompose (turns = 2 + Binomial(8, trait); catch-all sweep), ask_specific (concrete record vs general topic), persist (one re-ask per topic after a judged non-answer), verify (one figure check per session at hazard `1-(1-verify)^(1/(n_turns-1))`), synthesise (itemised vs brief answer) | `est/persona.py` docstring and `Persona.next_message` |
| behaviour | each turn's action is chosen in Python from traits and a per-session RNG `default_rng([20260908, i, idx+2, kind])`; an LLM only phrases the chosen message and sees only the public task prompt and visible conversation | `make_demo_trial_v2.sess_rng`, `est/persona.py` |
| self-report | `selfreport_llm = clip(round(1.5 + 0.8*g + N(0,1)), 0, 3)` | `make_demo_trial_v2.design` |
| pre-test | both arms: one EST session, `session_idx` -1, on item `items[i % 3]`; scored by `est.scorer.score`; subscales written to `participants.csv` `est_*` | `pretest_transcripts.jsonl` (48 records, 16 per item) |
| in-trial, LLM arm | two EST sessions (`session_idx` 0, 1) on the other two items, turn cap 12, against the gated `est.controller.Session` assistant | `transcripts.jsonl` (48 records: pcr_lab 18, cell_culture 16, western_blot 14) |
| in-trial, control arm | the persona answers each of its two trial items with no assistant and no records (`Persona.no_assistant_answer`) | `sessions/<pid>__{0,1}.json`, kind `control_answer` |
| counterfactual | for each LLM-arm person and item, a no-assistant answer from the same persona (different RNG stream) gives Y0 for `truth.json` only | `sessions/<pid>__y0_{0,1}.json` |
| outcome | mean over the two trial items of `|judge-present ∩ {C1..C7}|/7 + 0.125*flags_inconsistency` (`est.scorer.judge_submission`); range 0 to 1.125; secondary = `|present ∩ {C3..C7}|/5` | `truth.json` `outcome_definition` |
| oracle strata | tertiles of latent g over all 48 (cuts -0.487, 0.196); 16 per tertile; LLM-arm counts g_low 7, g_mid 7, g_high 10 | `truth.json` `g_tertile_cuts`, `participants[*].tier` |
| ceilings | `ceilings.jsonl`, 12 records: `model_alone` 2 per task (seeds 1, 2; one SONNET call with all records C1..C7 in context, planted inconsistency left in) and `expert` 2 per task (runs 1, 2; `est/persona.py` with every trait 0.97, participant side phrased by SONNET, RNG `[777, run, sum(ord(item))]`); every record carries `outcome` on the trial rubric and `circular: false` | `make_demo_ceilings_v2.py`, `ceilings.jsonl` |
| models | `est/llm.py`: `SONNET = EST_MODEL_MAIN or "claude-sonnet-5"`, `HAIKU = EST_MODEL_PARTICIPANT or "claude-haiku-4-5-20251001"`. Persona phrasing, topic planning, non-answer classifier, figure checker and submission writing use HAIKU (`sessions/v000__0.json` records `persona.model = claude-haiku-4-5-20251001`, `backend = cli`). The gated assistant (`est/controller.py`), the submission judge (`est/scorer.py`), the transcript judge (`est/transcripts.py`) and both ceilings default to SONNET | those files |
| seeds | design seed 20260908; ceiling seeds/runs [1, 2] | `make_demo_trial_v2.py`, `make_demo_ceilings_v2.py` |
| run | 192 jobs (96 EST sessions, 48 control answers, 48 counterfactual answers), 0 failed, wall 51.6 min at 8 workers, finished 11:04:45; assemble line: "unique transcripts 96/96; E0-ish diff in means 0.613; LLM-arm counterfactual ATE 0.613" | `run_main.log` last two lines |
| ceilings run | 12 records written between 10:00:17 and 10:06:37; expert composites 1.00, 1.00, 0.80, 1.00, 0.82, 1.00; the script's own circularity check did not run because `transcripts.jsonl` did not exist yet, and `circularity_check.json` was never written | `run_ceilings.log` |

## 3. What is and is not circular now

(a) Transcript-hash overlap, recomputed for this write-up with sha1 over the concatenated message contents of each record (and, separately, sha1 over `json.dumps(messages)`; both agree):

| file | records | unique hashes | overlap with transcripts.jsonl | overlap with pretest_transcripts.jsonl | overlap with ceilings.jsonl |
|---|---|---|---|---|---|
| transcripts.jsonl | 48 | 48 | . | 0 | 0 |
| pretest_transcripts.jsonl | 48 | 48 | 0 | . | 0 |
| ceilings.jsonl | 12 | 12 | 0 | 0 | . |

All 108 records are distinct. At the single-message level (sha1 of each stripped message content) there are 538, 552 and 127 distinct messages in the three files and zero shared messages between any pair. `results/trial_report.json` agrees: `ceiling_records_hash_identical_to_llm_sessions` 0 and `circular` false for both ceilings; `n_unique_transcripts` 48 of 48 sessions.

(b) Policy reuse. `est/persona.py` imports only `json`, `numpy`, `.llm` (`complete`, `complete_json`, `HAIKU`, `SONNET`) and `.controller.Session`. It does not import or reference `est/participants.py` or `est/participants_v2.py` (grep count 0), and neither does `make_demo_trial_v2.py` or `make_demo_ceilings_v2.py`. The pre-test score and the in-trial transcripts are separate sessions of the same latent person with different RNG streams, not the same transcript or the same scripted policy output.

(c) What is still designed in. The pre-test composite and the in-trial composite correlate because both load on latent g with loading 0.9 (`design.json` `g_loading`). The predictive-validity r of 0.595 therefore shows that the pipeline recovers a built-in correlation of roughly known size through two layers of LLM phrasing and an LLM judge. It is not evidence about whether a pre-test predicts human elicitation.

(d) Control arm. All 24 control outcomes in `participants.csv` are exactly 0 (verified), and all 48 LLM-arm counterfactual Y0 answers in `truth.json` are 0, because the rubric counts situation-specific records C1..C7 that a no-assistant answer cannot contain. Consequently E0 equals the treated mean (0.613), every per-stratum "effect" is a treated-stratum mean, `U` equals `oracle_diff_in_means_by_true_g_tertile`, the ITT ratio of arm means is undefined (`NaN` in the json, `n/a` in the md), and the E3a "selection bias from the tier-dependent baseline" is identically zero.

(e) Use. Every LLM-arm session has at least 2 user turns (`results/sessions.json` `n_user_turns` min 2), so `share_nonusers_treated` is 0.000, `pi_c` is 1.000 and the CACE in section G equals the ITT by construction (`cace_over_itt` 1.0; the exclusion-sensitivity row is constant at 0.613). The trimming bounds for stratum H collapse to a point because the control distribution is degenerate at 0. A non-degenerate demo of section G would need a control task with a non-zero attainable score (so baselines vary and ratios exist) and simulated non-users in the treated arm (a persona-level probability of never opening the assistant).

## 4. What the pipeline reports (`results/trial_report.json`; printed in `results/trial_report.md`)

Counts: `n_participants` 48, `n_llm` 24, `n_sessions` 48, `n_unique_transcripts` 48, `sessions_by_n_defined` {4: 10, 5: 38}, `judge_invented_target_ids` 0.

Predictive validity of pre-trial measures against the in-trial judged composite (LLM arm):

| pre-trial measure | Pearson r | R² | Spearman | 95% CI (r) | n |
|---|---|---|---|---|---|
| est_composite | 0.595 | 0.354 | 0.609 | 0.311 to 0.804 | 24 |
| selfreport_llm | 0.394 | 0.155 | 0.366 | 0.018 to 0.684 | 24 |

Uplift estimators against `truth.json` (population ATE 0.613; oracle per-true-g-tertile 0.413 / 0.644 / 0.731, n 16 each, LLM n 7 / 7 / 10):

| estimator | estimate | 95% CI | per-stratum low to high (n, n_llm) | valid |
|---|---|---|---|---|
| E0 unadjusted | 0.613 | 0.536 to 0.690 | . | yes |
| E1 pre-test EST tertiles (cuts 0.367, 0.520) | 0.606 | 0.542 to 0.674 | 0.423 (16, 7), 0.639 (15, 9), 0.750 (17, 8) | yes |
| E2 cross-fitted pre-treatment index tertiles | 0.605 | 0.536 to 0.681 | 0.457 (15, 6), 0.643 (21, 13), 0.723 (12, 5); index vs in-trial r 0.608; strata differ from E1 | yes; CI omits index-estimation uncertainty |
| E3a top in-trial tertile vs all controls | 0.776 | not computed | n_llm 8, composition g_high 6, g_mid 2 | no |
| E3b drop bottom in-trial tertile vs all controls | 0.703 | not computed | n_llm 16 | no |

E3a is printed only as what not to report: it changes the estimand to uplift among good elicitors, selects the treated arm on a post-treatment variable while controls stay unselected, and is diluted by misclassification; the three can offset, so closeness to any target is not evidence of validity (`estimates.E3a_*.why_invalid`). Here the reported 0.776 exceeds the true top-tier conditional uplift 0.731, with zero baseline selection bias (see 3d).

Elicitation ratio (`elicitation_ratio`; 6 ceiling records per ceiling, 2 per task; 1000 bootstrap replicates, 0 dropped):

| ceiling | LLM-arm yield | ceiling yield | ratio | 95% CI | trial-rubric scale: arm / ceiling / ratio | ceiling verification | circular |
|---|---|---|---|---|---|---|---|
| expert | 0.494 | 0.933 | 0.530 | 0.445 to 0.620 | 0.613 / 1.054 / 0.582 | 1.000 vs arm 0.604 | false, 0 hash-identical |
| model_alone | 0.494 | 1.000 | 0.494 | 0.417 to 0.570 | 0.613 / 1.015 / 0.604 | n/a (single turn) | false, 0 hash-identical |

Bootstrap caveats recorded in the json: with fewer than three ceiling records per task the ceiling side of the interval is essentially unmeasured; participants are the resampling unit. Gap decomposition (share of ceiling reference targets): expert reached 0.538, never raised 0.394, raised only generally 0.041, raised specifically but not provided 0.026, provided not used 0.000; model_alone reached 0.494, 0.419, 0.051, 0.036, 0.000. Sessions with a non-answer never retried 0.167.

Under-elicitation audit (share of LLM-arm sessions): coverage below half 0.479; no specific request 0.083; non-answer never retried 0.167; no verification 0.396; uptake below half of defined 0.0; persistence undefined 0.208; uptake undefined 0.0; participants with all sessions below half coverage 0.375.

Judge vs controller ground truth on 48 unique transcripts: coverage MAE 0.025, r 0.967; verification agreement 0.771; composite Spearman 0.484 (constructs differ by design, so only these three are compared). This check is independent of the persona design.

Learning and stability (LLM arm): learning curve composite 0.652 (sem 0.039, n 24) at session 0 and 0.698 (sem 0.034, n 24) at session 1; the md prints ±1.96 sem as ±0.077 and ±0.066. Rank stability first vs last session Spearman 0.292 (95% CI -0.109 to 0.610, p 0.167, n 24); mean gain 0.046 (SD 0.241). The two in-trial sessions are on different items with independent RNG streams, so 0.292 is the session-to-session consistency the trait model plus phrasing and judging noise produces at n 24.

Section G, use-adjusted estimands (`use_adjusted_estimands`; score = coverage, use = total user turns >= 1, B = 1000):

| quantity | estimate | 95% interval |
|---|---|---|
| share of treated never using the model | 0.000 (0 of 24) | . |
| ITT difference | 0.613 | 0.543 to 0.695 |
| ITT ratio | NaN (control mean 0.000, SD 0.000) | . |
| CACE difference (pi_c 1.000) | 0.613 | 0.543 to 0.695 |
| stratum H (cut 0.700, pi_H 0.375, n_H 9) effect set | [0.807, 0.807] | outer 0.600 to 0.884 |
| stratum H naive vs all controls (biased) | 0.807 | . |
| complement stratum effect set (n_L 15) | [0.497, 0.497] | outer 0.451 to 0.603 |
| covariate-tightened H set | [0.807, 0.807]; cross-fitted AUC 0.830; width reduction NaN | outer 0.600 to 0.884 |

All section G sets are points and all ratios undefined for the reasons in 3(d) and 3(e). The block demonstrates that the code runs on this input, not that it separates use from assignment.

## 5. Known defects (prominent)

**`analyze_trial_patch.diff` was NOT applied.** `analyze_trial.py` is held by another session, so the run at 11:15 used the unpatched file (the other session's additive section G version). Because this run's `transcripts.jsonl` excludes `session_idx` -1 (JOURNAL decision), the numerical consequence the patch guards against (pre-test transcript on both sides of the predictive-validity correlation) did not occur. The text consequence did: `results/trial_report.md` prints demo-v1 caveat sentences that are false for v2. Stale sentences, by line number in `results/trial_report.md`:

| line | printed (stale) | correct statement for v2 |
|---|---|---|
| 17 | "selecting true-top-tier LLM participants vs all controls gives 0.731 (selection bias from the tier-dependent baseline); reported E3a 0.776 after dilution" | the baseline is 0 for everyone, so there is no tier-dependent selection bias (0.731 = 0.731); the in-trial top tertile scored higher than the true g_high tier (0.776 > 0.731), so the tertile-vs-tier mismatch raised the number rather than diluting it. The canned `reading` string is v1 wording |
| 18 | "**Circularity (simulated demo): pre-test scores and transcripts come from the same scripted policies, so predictive validity, E1 per-stratum effects (= oracle), E2 per-stratum effects, rank stability and the learning curve below are artefacts of construction, not evidence. Only the judge-vs-controller agreement is a non-circular check...**" | pre-test and in-trial sessions are independent realisations of trait-driven personas; no transcript is shared (section 3a). The pre-test/in-trial correlation is designed in through the g loading of 0.9, so predictive validity, E1/E2 per-stratum effects and rank stability show recovery of a built-in structure of known size; they are not identities and not evidence about humans |
| 32 | "if LLM-arm transcripts are duplicated across participants ... the interval is too narrow. Treat it as a code check in the demo" | no LLM-arm transcript is duplicated (48 of 48 unique); the fewer-than-three-records caveat still applies |
| 45 | "**Demo caveats: the `expert` ceiling here is the scripted STRONG policy; its transcripts are hash-identical to the simulated top-tier participants' sessions (same cached judge call, see the circular column), so its ratio and CI are circular...**" | the `expert` ceiling is six fresh sessions of an all-traits-0.97 persona phrased by SONNET, sharing zero transcripts and zero messages with any participant session (the circular column on lines 27-28 already says "no; 0 of 6"). It remains a synthetic stand-in for a rubric-blind human expert. The `model_alone` and "provided, not used" remarks still hold |
| 75 | "**Demo caveat for section G: the pre-test covariates and the in-trial scores come from the same scripted policies, so the covariate-tightened set and its AUC are circular here**" | covariates and in-trial scores come from separate sessions; the AUC of 0.830 reflects the designed-in g loading. The real section G defect in v2 is degeneracy (control outcomes all 0, use 100%), which the md does not state |
| 68, 70 | "[0.000, -0.000] (width -0.000, n/a control SD)"; "narrow the set by n/a%" | formatting artefacts of the degenerate control distribution, not errors in the json |

Note on the patch itself: it reads `truth.json` keys `circularity_note` and `ceiling_note`, which `make_demo_trial_v2.py` does not write (top-level keys are README, trait_model, U, true_ATE_*, g_tertile_cuts, oracle_diff_in_means_by_true_g_tertile, outcome_definition, participants, sessions). Applied as is, it would still fall back to the v1 text for lines 18 and 45, and it does not touch line 75.

**Negative result preserved (`JOURNAL.md`, 10:15; `sessions_v0_verify_saturated/`, 34 session files plus its `run_main.log`).** The first generation attempt applied the verify trait as a per-turn check probability, which compounded over about five turns; the HAIKU checker finds the planted error whenever it looks, and two itemised submissions flagged the error with no chat challenge because the submission prompt invited arithmetic. JOURNAL records verification 0.94 for that batch; the mean controller verification over the 34 preserved EST session files is 0.912 (recomputed here). Fix: one check per session at hazard `1-(1-verify)^(1/(n_turns-1))` and an itemised-submission prompt that forbids fresh arithmetic; the main run restarted from zero EST sessions (ceilings kept, since the expert persona has verify 0.97 either way). In the final run the controller verification mean over the 48 in-trial sessions is 0.500 (`truth.json` `sessions`) and the judge's LLM-arm verification rate is 0.604.

**Re-ask cap (`JOURNAL.md`).** Re-asks are capped at one per topic after the smoke session spent two turns re-asking for a record that does not exist.

**Ceiling-script circularity check never executed.** `run_ceilings.log` ends with "transcripts.jsonl not present yet; rerun this script (cached)"; `circularity_check.json` is absent. Section 3(a) above substitutes for it.

## 6. How to reproduce

```
cd "<workspace>"                                     # elicitation-skill-test
.venv/bin/python make_demo_ceilings_v2.py --workers 4          # 12 ceiling records, cached in demo_trial_v2/ceiling_cache/
.venv/bin/python make_demo_trial_v2.py --workers 8             # 192 jobs, ~52 min; cached in demo_trial_v2/sessions/
.venv/bin/python make_demo_ceilings_v2.py --check-only         # writes demo_trial_v2/circularity_check.json
.venv/bin/python analyze_trial.py --trial-dir demo_trial_v2 > demo_trial_v2/analyze_run.log
.venv/bin/python make_demo_trial_v2.py --summarize             # results/summary_v2.json (not yet run)
```
Cached sessions and ceiling records are never regenerated if present; the shipped judge outputs are packed in `demo_trial_v2/judge_cache.json` (new calls write to `judge_cache/`); remove both to re-judge transcripts. Models are set by `EST_MODEL_MAIN` and `EST_MODEL_PARTICIPANT`.

## 7. Not verified here

- No number in `results/trial_report.json` was re-derived from `sessions.json` or the transcripts; they are transcribed. Independent re-derivation: `verification/V26_demo_trial_v2.md` (pending).
- The judge cache was not inspected for duplicate keys or stale entries.
- `make_demo_trial_v2.py --summarize` was not run, so `results/summary_v2.json` does not exist and the secondary (gated-only) outcome is reported only from `truth.json` (LLM arm mean 0.483, control 0.000).
- Whether `EST_MODEL_MAIN` was overridden during generation was not checked beyond `backend = cli` and the persona model string in one session file; the assistant and judge model identity is inferred from `est/llm.py` defaults.
- The 0.94 verification figure in JOURNAL for the v0 batch was not reconciled with the 0.912 recomputed over the preserved files (the batch JOURNAL summarised may differ from the 34 files kept).
- The claim that `analyze_trial.py` at 11:15 is byte-identical to the other session's version was taken from `STATE.md`, not diffed.

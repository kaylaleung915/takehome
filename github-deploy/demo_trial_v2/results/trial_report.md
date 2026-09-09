# Post-trial transcript report

48 participants (24 LLM arm), 48 sessions, 48 unique transcripts judged. Composite = mean of 5 subscales with undefined persistence/uptake scored 0 (fixed denominator); sessions by number of defined subscales {4: 10, 5: 38}.

## Trial metadata (trial/SCHEMA.md checklist items 7, 9 to 13)

- `prereg.yaml` (item 7, pre-registered estimands, compliance definition, analysis model, thresholds, date): NOT COLLECTED. Without it the report cannot say which estimand the headline number was registered to answer; thresholds below come from the command line or are absent.
- `arms.yaml` (items 9 to 11 and 13, assistant condition, model snapshot, tools, time budget, training, data handling): NOT COLLECTED. Without it the assistant condition and model the LLM arm faced are undocumented, so persistence and any ceiling ratio cannot be compared across trials.
- `grading.yaml` (item 12, grader identity, blinding, grading batch shared with the ceilings): NOT COLLECTED. Without it nothing ties the ceiling grades to the participants' grading pass, so a rubric-scale ratio is not comparable.

## Uplift estimates

| estimator | estimate | 95% CI | valid for inference? |
|---|---|---|---|
| E0 unadjusted difference in means | 0.613 | 0.536 to 0.690 | yes |
| E1 pre-stratified on EST tertiles | 0.606 | 0.542 to 0.674 | yes |
| E2 stratified on calibrated pre-treatment index | 0.605 | 0.536 to 0.681 | yes |
| E3a post-hoc: top-tertile in-trial elicitors vs all controls | 0.776 | not computed | **NO, biased** |
| E3b post-hoc: drop bottom-tertile elicitors vs all controls | 0.703 | not computed | **NO, biased** |

Known truth (simulated trial): population ATE 0.613; sample-mix ATE 0.613; per-tier uplift {'g_low': 0.413265306122449, 'g_mid': 0.6441326530612245, 'g_high': 0.73125}.
Oracle per-true-tier effects: g_high 0.731 (n=16), g_low 0.413 (n=16), g_mid 0.644 (n=16)
E3a decomposition: true conditional uplift in top tier 0.731; selecting true-top-tier LLM participants vs all controls gives 0.731 (selection bias from the tier-dependent baseline); reported E3a 0.776 after dilution because the in-trial top tertile is {'g_high': 6, 'g_mid': 2}. conditional uplift → +selection bias (baseline rises with tier) → −dilution (tertile ≠ tier); gap to ATE is mostly estimand change in this simulation.
**Circularity (simulated demo): pre-test scores and transcripts come from the same scripted policies, so predictive validity, E1 per-stratum effects (= oracle), E2 per-stratum effects, rank stability and the learning curve below are artefacts of construction, not evidence. Only the judge-vs-controller agreement is a non-circular check; the estimator table shows the code runs and that E3 targets a different estimand.**

Per-stratum effects (E1, pre-test tertiles low→high): 0.423 (n=16), 0.639 (n=15), 0.750 (n=17)
Per-stratum effects (E2, calibrated index tertiles low→high): 0.457 (n=15), 0.643 (n=21), 0.723 (n=12); index vs in-trial r = 0.608; strata identical to E1: False. bootstrap holds the fitted index and cuts fixed, so index-estimation uncertainty is omitted (CI somewhat too narrow).

## Elicitation ratio (LLM arm as a share of each ceiling; both reported, they answer different questions)

Flags for `expert_with_model`: ceiling protocol undocumented (no protocol_id): the ratio is prompt-dependent and not comparable across trials; assistant_condition missing on ceiling records (cannot tell a helpful-only from a safeguarded ceiling); model_id missing on ceiling records.

Flags for `model_alone`: ceiling protocol undocumented (no protocol_id): the ratio is prompt-dependent and not comparable across trials; assistant_condition missing on ceiling records (cannot tell a helpful-only from a safeguarded ceiling); model_id missing on ceiling records.

ceilings.jsonl provenance: 12 record(s) lack required fields (first: record 0 (model_alone, est:cell_culture): missing ['protocol_id', 'model_id', 'assistant_condition', 'aggregation']); full list under ceilings_schema_problems in trial_report.json. Required fields and why: trial/SCHEMA.md, section ceilings.jsonl.

| ceiling | question it answers | LLM-arm yield | ceiling yield | ratio | 95% CI | ceiling records (per task) | circular in this run? |
|---|---|---|---|---|---|---|---|
| expert_with_model | human: share of what a skilled elicitor extracts from the same gated assistant | 0.494 | 0.933 | 0.530 | WITHHELD (elicitor_id missing on 6 record(s)); participant-side only, ceiling held fixed: 0.445 to 0.620 | 6 (2/2/2; fewer than 3 independent units on some task: insufficient reference sessions) | no; 0 of 6 ceiling records hash-identical to 0 of 48 LLM-arm sessions |
| model_alone | capability: share of what the model produces with full access that reached participants' answers | 0.494 | 1.000 | 0.494 | WITHHELD (<3 independent ceiling units on some task); participant-side only, ceiling held fixed: 0.417 to 0.570 | 6 (2/2/2; fewer than 3 independent units on some task: insufficient reference sessions) | no; 0 of 6 ceiling records hash-identical to 0 of 48 LLM-arm sessions |

Yield is the share of designer targets reflected in the final answer, macro-averaged over tasks. Scale: designer-target yield (share of task targets reflected in the final answer), not the trial's own outcome rubric. If ceiling submissions are graded on the trial's own rubric (add `outcome` to ceilings.jsonl), the same table is also printed on that scale.

CI note: percentile interval from a cluster bootstrap over LLM-arm participants with ceiling records resampled within task (1000 replicates; dropped replicates: expert_with_model 0, model_alone 0). With fewer than 3 independent ceiling units (seeds, elicitors or distinct transcripts; an expert_with_model record without elicitor_id has no unit) on any task the ceiling side of the interval is unmeasured, so the 95% CI is WITHHELD and only the participant-side interval (ceiling held fixed) is shown for orientation; if LLM-arm transcripts are duplicated across participants (see pseudo-replication warning above, if printed) even that is too narrow. Treat it as a code check in the demo, not as an inferential interval.

Where the gap sits. Each designer target is weighted by the share of the task's ceiling records whose final answer used it (the ceiling's reach frequency), so a target every ceiling run reached counts fully and one reached by a single run out of n counts 1/n. Each cell is the weighted share of (session x target) mass in that category, divided by the expected number of targets one ceiling run reaches, pooled over tasks with the same ceiling-yield weighting as the ratio above. 'Beyond ceiling' is the mass participants reached on targets the ceiling did not reach, or reached in only some runs; by construction reached + beyond ceiling = ratio, so the table accounts for the whole ratio. 'Ceiling self-agreement' scores each ceiling run on the same 'reached' scale against the other runs of its task (leave-one-out); participants' 'reached' should be read against that number, not against 1. With fewer than 3 independent ceiling units (seeds, elicitors or distinct transcripts; records that repeat a unit do not count) on some task the row is flagged: the weights are then 0/1 (one run) or 0/0.5/1 (two runs), self-agreement is undefined or rests on one pair, and the table describes the shortfall against the available run(s) rather than against what the ceiling reliably reaches. Tasks on which the ceiling reached nothing have no per-task shares (listed in the JSON as gap_tasks_with_empty_ceiling) but still enter the pooled row through 'beyond ceiling'.

| ceiling | ceiling records per task (min) | reference status | reached by participant | beyond ceiling | never raised | raised only generally, not provided | raised specifically, still not provided | provided, not used in answer | ceiling self-agreement (LOO) | sessions with a non-answer never retried | verification rate: arm vs ceiling |
|---|---|---|---|---|---|---|---|---|---|---|---|
| expert_with_model | 2 | INSUFFICIENT (<3 independent units; min 0) | 0.512 | 0.018 | 0.411 | 0.046 | 0.031 | 0.000 | 0.936 | 0.167 | 0.604 vs 1.000 |
| model_alone | 2 | INSUFFICIENT (<3 independent units; min 2) | 0.494 | 0.000 | 0.419 | 0.051 | 0.036 | 0.000 | 1.000 | 0.167 | 0.604 vs n/a (single-turn ceiling) |

On the trial-rubric scale (expert_with_model): LLM arm 0.613 vs ceiling 1.054, ratio 0.582. trial-rubric scale; requires ceiling submissions graded on the same rubric as participants.

On the trial-rubric scale (model_alone): LLM arm 0.613 vs ceiling 1.015, ratio 0.604. trial-rubric scale; requires ceiling submissions graded on the same rubric as participants.

**Demo caveats: the `expert_with_model` ceiling here (legacy kind `expert`) is the scripted STRONG policy; its transcripts are hash-identical to the simulated top-tier participants' sessions (same cached judge call, see the circular column), so its ratio and CI are circular and shown only to exercise the code. 'Provided, not used' is 0 in this demo: synthetic submissions summarise the conversation, so dropping an obtained record is rare by construction and did not occur. The `model_alone` ceiling is a genuine single model call with every record in context and is not circular, but on EST items it is near-trivial by construction (nothing is withheld from it), so the informative real-trial analogue is a model or agent given the trial task and tools with no human in the loop.**

E3 is printed only to show what NOT to report. (1) it silently changes the estimand from the population ATE to uplift among good elicitors; (2) it selects the LLM arm on a post-treatment variable correlated with baseline ability while controls stay unselected, adding baseline differences to the estimate; (3) misclassification of who is a good elicitor dilutes it. The three can offset, so closeness to any target is not evidence of validity. (Montgomery, Nyhan & Torres 2018.) Use transcripts to validate and, where several pre-trial covariates exist, re-weight the PRE-trial measure (E2); whether that improves on E1 is an empirical question the demo cannot answer.

## Use-adjusted estimands (section G)

Table not printed for this trial: the control-arm outcome has no variance (mean 0.000, SD 0), so the stratum bounds collapse to a point and quantities scaled by the control SD are undefined. The values are in trial_report.json; `analyze_estimands.py` prints the full section for a trial whose control arm has a non-degenerate outcome.

No decision thresholds in section G: nothing was given on the command line and there is no prereg.yaml, so no rule-out or rule-in statement is made.

**Demo caveat for section G: the pre-test covariates and the in-trial scores come from the same scripted policies, so the covariate-tightened set and its AUC are circular here; only the unconditional set and the CACE arithmetic are a genuine code check.**

## Does the pre-trial test predict in-trial elicitation?

| pre-trial measure | Pearson r | R² | Spearman | 95% CI (r) | n |
|---|---|---|---|---|---|
| est_composite | 0.595 | 0.354 | 0.609 | 0.311 to 0.804 | 24 |
| selfreport_llm | 0.394 | 0.155 | 0.366 | 0.018 to 0.684 | 24 |

## Learning and rank stability within the trial (LLM arm)

First-session vs last-session composite: Spearman 0.292 (95% CI -0.109 to 0.610, n=24); mean gain 0.046 (SD 0.241).
Learning curve (mean composite by session index): 0: 0.652±0.077 (n=24), 1: 0.698±0.066 (n=24)
If rank stability is low, the pre-trial score's value as a stratifier is correspondingly low (README kill criterion); the warm-up use is unaffected.

## Under-elicitation audit (share of LLM-arm sessions)

| indicator | share |
|---|---|
| sessions coverage below half | 0.479 |
| sessions no specific request | 0.083 |
| sessions nonanswer never retried | 0.167 |
| sessions no verification | 0.396 |
| sessions uptake below half of defined | 0.0 |
| sessions persistence undefined no nonanswer met | 0.208 |
| sessions uptake undefined nothing provided | 0.0 |
| participants all sessions coverage below half | 0.375 |

## Transcript judge vs controller ground truth (EST transcripts only)

n=48 unique transcripts: coverage MAE 0.025, r 0.967; verification agreement 0.771; composite Spearman 0.484. constructs differ by design (controller specificity = T2 unlocks; judge specificity = share of specific asks), so only coverage/verification/composite-rank are compared

Inputs and schema: trial/SCHEMA.md. Judge prompt: est/transcripts.py. All numbers in trial_report.json.

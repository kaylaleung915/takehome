# RealHumanEval: episode completion vs judged elicitation behaviour, conditional on conversation length (statsmodels 0.15)

Status: CORRELATIONAL. Observational comparison within the four chat arms of RealHumanEval; behaviour scores, message count and completion are jointly determined inside each episode, and struggling participants send more messages. Nothing here is a causal effect of elicitation on completion.

Source script: `critique2_20260908/B01_p7_statsmodels/p7_statsmodels.py` (raw numbers in `p7_results.json`, console log `p7_stdout.txt`); extras `p7_extras.py` (`p7_extras.json`). Data: `data/realhumaneval/trial_real/results/sessions.json` (judge subscales) joined to `data/realhumaneval/trial_dir/episodes.csv` (`completed` = unit tests passed on submit) on participant_id, task_id, session_idx.

## Sample

| quantity | value |
|:--|--:|
| judged episodes (sessions.json) | 386 |
| matched to episodes.csv | 386 (unmatched 0) |
| dropped for missing outcome | 1 (`80:sum_product`, task absent from study task_data) |
| analysis episodes / participants / tasks | 385 / 107 / 17 |
| episode completion rate | 0.647 |
| tasks with no outcome variation (uninformative under task FE) | calculator 0/16, event_scheduler 0/5, sum_product 48/48; 69 episodes |
| task-FE logit sample: episodes / participants / tasks | 316 / 105 / 14 |
| participants with within-person outcome variation (conditional logit sample) | 79 participants, 318 episodes |
| persistence defined / uptake defined | 106 / 299 episodes |

## Main table: odds ratio on the behaviour term (per unit, i.e. 0 to 1 full range), participant-clustered 95% CI

One model per behaviour. (a) `completed ~ behaviour + C(task) + C(arm)`; (b) adds `log(1+n_user_turns)`; (c) conditional logit with participant strata, `behaviour + log(1+turns)`, cluster-bootstrap CI (499 participant resamples) where run, model-based CI otherwise; (d) linear probability model with task FE, arm FE and log(1+turns), clustered. GLM binomial, statsmodels sandwich `cov_type='cluster'` on participant.

| behaviour | SD | (a) task FE, no length | (b) task FE + log(1+turns) | (b) p | (b) per-SD OR | (b) cluster-boot 95% CI | (c) participant-FE logit + log(1+turns) | (d) LPM b [95% CI] |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| coverage | 0.258 | 2.51 [0.82, 7.63] (n=316, 105 cl) | 9.63 [2.47, 37.60] (n=316) | 0.0011 | 1.79 [1.26, 2.55] | [2.87, 70.55] | 3.78 [1.07, 22.33] boot; n=318, 79 persons | 0.304 [0.127, 0.481] (n=385) |
| specificity | 0.437 | 1.50 [0.84, 2.68] (n=316, 105 cl) | 1.79 [1.00, 3.21] (n=316) | 0.0512 | 1.29 [1.00, 1.66] | [1.04, 3.65] | 1.29 [0.68, 2.33] boot; n=318, 79 persons | 0.088 [0.010, 0.166] (n=385) |
| persistence | 0.483 | 0.83 [0.17, 4.00] (n=83, 60 cl) | 0.61 [0.09, 4.39] (n=83) | 0.6259 | 0.79 [0.31, 2.04] | not run | 1.48 [0.15, 14.36] model-based; n=43, 17 persons | -0.101 [-0.384, 0.183] (n=106) |
| verification | 0.342 | 0.57 [0.25, 1.30] (n=316, 105 cl) | 0.70 [0.30, 1.67] (n=316) | 0.4258 | 0.89 [0.66, 1.19] | not run | 1.33 [0.58, 3.09] model-based; n=318, 79 persons | -0.048 [-0.197, 0.101] (n=385) |
| uptake | 0.273 | 1.24 [0.36, 4.29] (n=257, 94 cl) | 1.49 [0.40, 5.55] (n=257) | 0.5567 | 1.11 [0.78, 1.60] | not run | 1.16 [0.37, 3.62] model-based; n=224, 59 persons | 0.052 [-0.123, 0.227] (n=299) |
| composite | 0.228 | 1.55 [0.46, 5.23] (n=316, 105 cl) | 5.63 [1.35, 23.37] (n=316) | 0.0175 | 1.48 [1.07, 2.05] | [1.40, 38.58] | 4.28 [1.15, 17.02] boot; n=318, 79 persons | 0.243 [0.057, 0.429] (n=385) |

log(1+turns) term in model (b) for coverage: OR 0.30 (p 0.0023). log(1+turns) alone with task and arm FE: OR 0.62 [0.32, 1.18] (p 0.146, n=316). Linear turns with arm FE only (the section-5 / V21c spec): OR 0.801 [0.718, 0.893] (n=385), matching `results/realhumaneval_report.md` L182 (0.802 [0.719, 0.893]).

## Reproduction of earlier specifications (sandwich SEs in place of bootstrap)

| behaviour | section 5 spec: behaviour + C(arm) + pre_prog, no length (report L177-181) | V21c P7 spec: behaviour + turns + C(arm), no task FE (V21c L25) |
|:--|--:|--:|
| coverage | 1.46 [0.61, 3.48] p 0.397 (n=385) | 7.59 [2.36, 24.39] p 0.0007 (n=385) |
| specificity | 1.24 [0.78, 1.98] p 0.368 (n=385) | 1.69 [1.05, 2.74] p 0.0316 (n=385) |
| persistence | 0.65 [0.28, 1.50] p 0.315 (n=106) | 0.83 [0.25, 2.81] p 0.7651 (n=106) |
| verification | 0.61 [0.34, 1.11] p 0.104 (n=385) | 1.11 [0.55, 2.23] p 0.7719 (n=385) |
| uptake | 0.85 [0.34, 2.14] p 0.732 (n=299) | 0.98 [0.37, 2.60] p 0.9631 (n=299) |
| composite | 1.06 [0.43, 2.57] p 0.904 (n=385) | 6.36 [2.03, 19.98] p 0.0015 (n=385) |

Section 5 published values: coverage 1.457 [0.613, 3.463], specificity 1.24 [0.778, 1.974], verification 0.611 [0.339, 1.102], composite 1.056 [0.437, 2.554], uptake 0.851 [0.342, 2.12] (`results/realhumaneval_report.md` L177-181). V21c BFGS + 500-rep cluster bootstrap: coverage 7.6 (2.6 to 28.5), composite 6.4 (2.2 to 19.7), specificity 1.69 (1.04 to 2.80) (`verification/V21c_assessment_pipeline_claims.md` L25). Both reproduce to the second decimal on the point estimates.

## Sensitivity (model (b) variants; coverage / composite / specificity ORs)

| variant | coverage | composite | specificity |
|:--|--:|--:|--:|
| linear turns instead of log | 8.98 [2.28, 35.39] p 0.0017 | 5.35 [1.23, 23.32] p 0.0256 | 1.76 [0.98, 3.14] p 0.0576 |
| + pre_prog + pre_python | 9.95 [2.35, 42.14] p 0.0018 | 5.44 [1.32, 22.38] p 0.0189 | 1.85 [1.00, 3.40] p 0.0483 |
| no task FE (arm FE + log turns) | 8.04 [2.50, 25.80] p 0.0005 | 7.00 [2.34, 20.96] p 0.0005 | 1.76 [1.09, 2.85] p 0.0209 |
| participant-FE logit + task dummies + log turns (model-based CI) | 3.36 [0.32, 35.34] p 0.313 (n=318) | 0.56 [0.03, 10.55] p 0.695 (n=318) | 1.29 [0.36, 4.59] p 0.692 (n=318) |
| participant-FE logit, no length term | 0.80 [0.29, 2.23] p 0.671 (n=318) | 0.64 [0.20, 2.07] p 0.456 (n=318) | 0.92 [0.52, 1.63] p 0.768 (n=318) |
| LPM task FE, no length (b) | 0.155 [-0.015, 0.324] p 0.074 | 0.077 [-0.101, 0.255] p 0.399 | 0.063 [-0.014, 0.141] p 0.110 |
| LPM task FE + participant FE + log turns (b) | 0.162 [-0.068, 0.393] p 0.167 | 0.132 [-0.126, 0.391] p 0.316 | 0.005 [-0.099, 0.110] p 0.925 |

Mundlak decomposition (model (b) with the behaviour split into the participant's mean and the within-person deviation; task FE, arm FE, log turns split the same way; clustered):

| behaviour | between-person mean OR [95% CI] | within-person deviation OR [95% CI] |
|:--|--:|--:|
| coverage | 278.7 [17.6, 4416.0] p 0.0001 | 2.31 [0.49, 10.94] p 0.290 |
| specificity | 3.6 [1.1, 12.0] p 0.0400 | 1.18 [0.61, 2.28] p 0.631 |
| composite | 22.5 [1.2, 407.8] p 0.0350 | 2.20 [0.43, 11.26] p 0.345 |

Model-free view (task-confounded; coverage takes few discrete values per task). Completion by user-turn bin: 1 turns 0.748 (n=139, mean coverage 0.217); 2 turns 0.714 (n=84, mean coverage 0.269); 3-4 turns 0.591 (n=93, mean coverage 0.424); 5+ turns 0.435 (n=69, mean coverage 0.559). Completion by coverage bin: cov<=0.2 0.524 (n=124, mean turns 1.86); 0.2<cov<=0.34 0.822 (n=101, mean turns 2.04); cov>0.34 0.631 (n=160, mean turns 4.0).

## Reading

1. The V21c P7 numbers reproduce under statsmodels with participant-clustered sandwich SEs (coverage OR 7.59 vs 7.6; composite 6.36 vs 6.4; specificity 1.69 vs 1.69), and adding task fixed effects does not remove them: coverage OR 9.63 [2.47, 37.6], composite 5.63 [1.35, 23.4], specificity 1.79 [1.00, 3.21] (borderline). Cluster-bootstrap intervals are wider but exclude 1 for all three. Verification, uptake and persistence are null in every specification. The LPM agrees in sign and significance (coverage +0.30 [0.13, 0.48] completion probability per unit).
2. The association exists only conditional on conversation length. Without the length term the task-FE OR for coverage is 2.51 [0.82, 7.63] and the raw Spearman with completion is 0.06 (composite 0.00). Length and coverage are mutual suppressors (Spearman 0.50 with each other; opposite-signed given each other; length alone under task FE is OR 0.62, p 0.15).
3. The association is mostly between persons. Person-mean coverage carries it (Mundlak between OR 279 [18, 4416]); the within-person deviation is OR 2.3 [0.49, 10.9]. The participant-stratified conditional logit gives coverage OR 3.78 with bootstrap CI [1.07, 22.3] without task dummies and 3.36 [0.32, 35.3] with them; the two-way FE LPM gives +0.16 [-0.07, 0.39]. Point estimates stay positive; none of the within-person estimates with task control excludes the null. With 79 informative participants and 318 episodes this is low power, not evidence of absence.
4. What the sentence can say: in RHE, judged coverage (and the composite) is positively associated with episode completion at a fixed number of user messages, across task and arm fixed effects and clustered SEs; the association is correlational, is absent marginally, and is carried mainly by differences between participants (people who cover more of the task per message complete more), which is the reading relevant to a person-level instrument but is also the reading most exposed to confounding by programming skill (pre_prog and pre_python do not move it: OR 9.95 [2.35, 42.1]).

## Not checked

- No human validation of the judge on coding chats (inherited from `results/realhumaneval_report.md` L334).
- Task-by-arm interactions, session-order effects and time-in-task were not modelled.
- The conditional-logit cluster SEs requested via `cov_type='cluster'` came back identical to the model-based SEs (statsmodels ConditionalLogit ignores the argument), so the participant-FE CIs are model-based except where a 499-rep participant bootstrap is shown.
- Mozannar et al. paper text not consulted; `completed` semantics taken from `analysis/realhumaneval.py` L25.

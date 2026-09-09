# Owner assessment, 2026-09-08: is under-elicitation a real evals problem, and does EST solve it?

*Internal assessment written during the build, asking whether under-elicitation is a real problem and whether EST addresses it. References to `verification/`, `reports/`, `runs/` and `STATE.md` are working files from the build that are not included in this repository.*

Written by the assessing session at the owner's request ("senior eval engineer, brutally honest thinking partner"). Every numbered claim below was handed to a fresh-context verifier before delivery; verdicts and file:line citations are in `verification/V21a_assessment_premise_claims.md`, `V21b_assessment_instrument_claims.md`, `V21c_assessment_pipeline_claims.md`. Confidence figures are the assessing agent's, after the verifier pass. Delivered in chat at ~10:12 PDT; this file is the persisted copy plus an addendum (section 5) for results the concurrent session produced while the verifiers were running.

## 0. Corrections made before delivery

Three draft claims were refuted by the verifiers and removed or reversed:

1. "The V16 feasibility report was never written and A3 was never deployed." Wrong on both. `verification/V16_human_feasibility.md` and `V16_artifacts/v16_human_model.json` exist; live `/api/health` returns `wall_seconds 900, hard_wall_seconds 1500, version 1.3`. The `health.json` showing 300 s was a 09:48 pre-deploy snapshot. (V21b D2.)
2. "RealHumanEval shows elicitation behaviour is unrelated to completion (Spearman −0.03)." The verifier recomputed it conditional on turn count: coverage OR 7.6 (CI 2.6 to 28.5), composite OR 6.4 (2.2 to 19.7), specificity OR 1.69 (1.04 to 2.80); verification and uptake null. Message count is a suppressor. Correlational, task-confounded, bootstrap rather than sandwich SEs, no task fixed effects, not yet reproduced. README L317-319 and L343 ("neither stable nor related to the outcome") are now half wrong in the direction that hurts the project. (V21c P7.)
3. "G1 failed twice because Haiku STRONG followed its script." v1 failed on uptake, MEDIUM 0.739 < WEAK 0.750; only v2 involved STRONG fixation, and the judge crediting single-topic MEDIUM questions as specific contributed. (V21b D5.)

## 1. Q1. Is under-elicitation a real evals / data-quality problem?

Yes to the narrow version. Unproven for the version the project is built on.

What stands (verifier CONFIRMED; confidence 85 to 90%):

- Humans with a model land below the model alone in four high-confidence medical RCTs (R_cap 0.826, 0.861, 0.875, 0.984) and at or below 0.364 in Bean 2026. `results/published_ratios.md` L227, L18.
- Engagement heterogeneity is large: 20% zero-message task responses and 4/50 participants who never messaged in OpenAI 2024 (`results/openai2024_numbers.md` L15); Hong 0 to 1.4M tokens. Its consequence for outcome is not computed anywhere in the workspace.
- Self-report carries near-zero information about actual behaviour (PRISM, RealHumanEval). This is the solid data-quality finding.

What does not stand:

- No study in the workspace links a performance-based elicitation measure to uplift-trial outcome at the person level. Q-A returned nothing. The nearest analogue, Weidmann 2025, measures "leadership skill with AI agents" (GPT-4o followers role-playing teammates) against human-team leadership, not uplift. README L430's "person-level skill" heading is looser than the paper warrants. Confidence 90%.
- `reports/executive_report_2026-09-08.html` L78 calls the behaviours "consequential". Nothing in the repo supported that when written; README L343 contradicted it; V15 did not flag the inconsistency. The P7 conditional result now permits a weaker sentence: "common, invisible to self-report, and associated with completion once conversation length is held fixed". Confidence 80% that this is the most that can be said today.
- The "humans land below the model ceiling" universal survives only by restricting to open-ended professional tasks. Riedl and Weidmann 2026 (randomised, n=667, ~112%) is the strongest counter-example; V10 L1204 notes none of the cited trials tested the above-ceiling direction. Confidence 85%.
- The OpenAI 2024 self-report null (n=50, 4-level item nearly collinear with cohort, pooled Spearman −0.19) cannot separate "self-report is a bad proxy" from "skill does not matter". The exec report presents only the first reading. Confidence 85%.
- The stratifier premise needs elicitation to be a stable trait. Per-conversation ICC in PRISM and RealHumanEval is 0.06 to 0.24. The verifier's correction: PRISM ICC(1,k) over six conversations reaches 0.57 to 0.84, so aggregated instruments can work; item count, not the construct, is the constraint. See section 5 for the Weidmann update, which moves this further.
- Attribution is more heterogeneous than "medicine says anchoring/uptake": Goh and McDuff say uptake, Healy says under-asking (30% of case questions posed to the LLM), Bean says information transfer, Tang says prompting and context specification, RAND says literature skill. No study regresses coded behaviour on outcome.

Construct-scope issue not stated in the README: the persistence subscale measures re-asking a cooperative assistant. That matches helpful-only trial designs (Anthropic Opus 4 "safeguards removed", OpenAI research-only GPT-4) and mismatches safeguarded designs (RAND 2024). The README should name which trials the instrument is for.

Verdict on Q1. The real evals problem is that uplift trials have large, unmeasured participant-by-tool interaction, and the only covariate anyone collects (self-report) is noise. That is true and worth working on. The project's framing, a stable skill testable in minutes and usable for blocking, is a hypothesis with one supporting analogue (section 5), not an established problem.

## 2. Q2. Is EST solving it?

No, not yet. Two of the three uses cannot be validated with what exists.

Use 1, warm-up. Plausible and cheap. RealHumanEval's learning curve (0.27 at session 0 to 0.36 at session 1) is weak support that a first-session effect exists. No evidence EST specifically removes it. Confidence 55% that it helps at all.

Use 2, pre-treatment stratifier. Tertile blocking captures about 0.79 of a covariate's variance, so a 10% SE gain needs ρ(pre-test, outcome) ≈ 0.49 and 20% needs ≈ 0.67 (V21c P8). No EST-specific reliability projection exists (V21b D7). The instrument yields 3 binary verification items, 2 specificity items and 1 refusal item per three-level run. V6 L29 notes the stratifier costs nearly nothing, so the honest label is "harmless, probably useless at current length", not "harmful". Confidence 65% it fails the |ρ| > 0.3 rule at three levels (down from 70% before section 5); 90% that ρ cannot currently be estimated at all.

Supporting facts on the instrument, all verifier-checked:

- One human session ever, 1 turn, composite 0.173, owner smoke test (`runs/human/pcr_lab__40602f1f.json`). No human has completed a level; every 8+ turn artifact is a scripted API probe.
- Time per 12-turn level: 17.5 min under the optimistic envelope, 22.7 under component arithmetic, 34 for a slow reader, against a deployed 900 s participant clock. The "5-minute game" label is dead. Confidence 90%.
- G1 has never passed (v1 uptake inversion; v2 specificity).
- Gatekeeper accuracy was studied against a blind labeller (raised F1 0.983, asked-specific F1 0.897); run-to-run variance is what is unstudied (2 seeds; IF-2 shows an identical opener judged differently).
- claude-sonnet-5 plays assistant, gatekeeper, submission judge and session judge; disclosed in README and page, no independent check.
- CB transfer untested (README names it the main unproven assumption).
- Prompt injection: locked records are never in the assistant context (`controller.py:91`), so the exposed subscale is verification (PLANTED_ERROR text), not coverage or specificity; tested with two probes.

Use 3, post-trial transcript pipeline. The most defensible piece and the one with verified output. Code runs; every `trial_real` number reproduces. But:

- E0 on RealHumanEval shows nothing beyond "code runs": SE 0.31, MDE ≈ 0.87 tasks, pooled treatment spanning GPT-3.5 +0.48 to CodeLlama −0.68. E2 uses three covariates and adds nothing (index vs in-trial r 0.095; CI slightly wider than E0).
- R_cap is ceiling-prompt-dependent and unspecified; `trial/SCHEMA.md` never mentions `ceilings.jsonl`; demo and RHE ceilings use different prompts (V21c P4).
- Reference rule is the intersection at n=2 and the single record at n=1 (V21c P5; V11b already said so).
- Session judge validated on 18 synthetic transcripts of its own items, scored by the same model, with coverage targets mapping one-to-one to controller records; kappa 0.25 against a lexicon on PRISM; no human labels on any human corpus (V21c P6).
- Composite compression from the fixed denominator is real (Spearman 0.57 with n_defined) but is not why rank stability is low: always-defined subscales are as unstable (split-half 0.135). Changing the scoring rule will not fix reliability (V21c P1).
- Judge prompt byte-stable since first scoring; `metrics()` was iterated afterwards on the same 18 transcripts used for validation (V21c P9).
- A real CB trial would need seven inputs no existing trial collects (V21c Q-E). Per-participant outcome is the blocker for the Anthropic Claude 4 design, which grades one plan per 8 to 10 person group.

What EST is solving today: infrastructure for coding elicitation behaviour in transcripts, with a clean estimator table and an honest E3 warning. What it is not solving: demonstrating that the coded quantity matters for trial outcomes, or that a short pre-test captures it.

## 3. Recommended order of work

1. Read `results/weidmann2025.md` (done by the concurrent session, see section 5) and decide whether to run `est/transcripts.py` over the Weidmann chat logs to get EST-judge reliability over six repeats per person.
2. Reproduce P7 with statsmodels clustered SEs and task fixed effects; rewrite README L317-319, L343 and exec report L78 from the result.
3. Ten non-owner participants through three levels before further design work.

## 4. Not verified, and document defects caught

Unverified: "reproduces the paper's null" for RealHumanEval (paper text not in workspace); P7 is a BFGS fit with bootstrap CIs; cache deletion before 2026-09-07 16:33 cannot be excluded for P9; the live Modal volume is not mirrored locally, so the one-human-session count is local only; the three verifiers did not see each other's reports.

Document defects the verifiers caught, not yet fixed: exec report L78 "consequential"; README cited `est/transcript_judge.py` (the file is `est/transcripts.py`; since fixed); `app/server.py:3` docstring says 20 min hard wall, default is 1500 s; `results/realhumaneval_report.md:330` "task sets fixed per condition" is wrong (task set appears in both arms, chi-square p 0.49); README G1 narrative attributes v1 to STRONG; README Limitations lack the helpful-only vs safeguarded scope note.

## 5. Addendum: results produced concurrently (read after delivery)

Another session was writing to this workspace while the verifiers ran (`STATE.md`, `README.md`, `results/weidmann2025.*`, `verification/V19`, `V20`, `V5e`, all mtimes 10:05 to 10:12 PDT). Two items change the assessment above:

Weidmann 2025 re-analysis (`results/weidmann2025.md` L61-63, L89, L97; independently re-derived in `verification/V20_weidmann2025_verifier.md`, 11/11 match). AI-test split-half 0.849, alpha 0.840, ICC(1) 0.436 per 6.6-minute puzzle, ICC(1,6) 0.823; Spearman-Brown projection 1 item 0.44, 3 items 0.70, 6 items 0.82. Self-rating vs score −0.19.

What this changes. The "nothing reads the Weidmann data" line in the chat delivery was true at read time and stale by delivery; withdrawn. More importantly, per-item ICC 0.44 in a structured AI-interaction task is two to seven times the per-conversation ICC in PRISM and RealHumanEval. That is the first direct evidence in the workspace that a structured interaction test can have adequate person-level reliability, and it lowers my confidence that "three levels is too few" from 70% to about 50%, conditional on EST items behaving like Weidmann puzzles. Caveats that keep it from settling Q2: the construct is AI-team leadership, not assistant elicitation; one session per person, so no test-retest; EST levels run 15 min under the deployed clock against 6.6 min per Weidmann puzzle, so EST gets fewer items per participant-minute; and reliability is not validity, ρ(score, uplift outcome) remains unmeasured everywhere. README L89's conclusion ("EST's reliability will be bounded by item count, not minutes") is the right inference and argues for redesigning EST toward more, shorter items.

Timestamp anomaly. `STATE.md` carries checkpoints labelled 10:25, 10:45 and 10:55 while the system clock at the time of this write read 10:12 PDT. The audit trail's times are not reliable for ordering today's work; file mtimes are.

## 6. Distillation: the established problem, separated from the hypothesis stack

Owner follow-up (verbatim): "we want to find the root established problem, not just a hypothesized problem... can you distill the actual problem?"

Established problem. Uplift trials have heavy, heterogeneous, unmeasured non-compliance in the treatment arm, and they report an intention-to-treat estimate with no dose measure and no capability ceiling. The number they produce therefore cannot be read as "what the model enables", which is the question the safety case asks. In trial-methodology terms: large non-compliance, no compliance rate reported, no complier estimand, no statement of which estimand is being reported. Confidence 90% in this characterisation.

Evidence layers (all verified in V21a unless noted):
1. Non-compliance is large: 20% zero-message task responses and 4/50 never-messaging participants in OpenAI 2024; Hong 0 to 1.4M tokens. Confidence 95%.
2. Even among users, extraction is far below what the model holds: human-plus-model below model-alone in 4/4 high-confidence medical RCTs (R_cap 0.83 to 0.98), at or below 0.36 in Bean; not universal (Riedl and Weidmann 2026, 112%, n=667). Confidence 85% for the open-ended-task restriction.
3. Nobody measures it and the collected proxy fails: no randomised uplift trial codes per-participant behaviour (C4); self-report explains 0 to 1% of behaviour in PRISM and RHE (C8); Claude 4 and 4.5 cards as reviewed report no rubric-matched model-alone ceiling (V21c Q-E item 5). Confidence 85%.

Why it matters. If the estimand is uplift to a realistic novice population, external validity requires the trial sample's extraction distribution to match the threat population's, and neither is known. If the estimand is what a motivated actor could get, the ITT mean over a sample with 20% non-users is biased low by an unbounded amount. Both readings need the same missing object: a per-participant extraction measure and the ceiling it is compared against.

Quantified but not established as mechanism: which behaviour drives the gap. Attribution differs by paper (uptake; under-asking; information transfer; prompting; literature skill); no study regresses any on outcome; V21c P7 is provisional and correlational.

Hypothesised: that extraction is a stable person trait (Weidmann per-item ICC 0.44 for an adjacent construct vs PRISM/RHE 0.06 to 0.24; confidence 50%); that it is measurable in a short pre-test, transfers to CB content, and reaches ρ > 0.3 with outcome (no evidence on any); that blocking on it buys power (ρ ≈ 0.49 needed for a 10% SE gain, V21c P8).

Implication for the project. The established problem is a missing measurement, not a missing pre-test. The workspace component that addresses it is the transcript coder plus the model-alone ceiling plus the ratio, reported alongside the ITT estimate (Use 3). EST the game addresses the hypothesis stack. The exec report currently leads with the hypothesis stack and lists the transcript work third; the defensible ordering is the reverse, with the pre-test as a follow-on experiment whose first milestone is Weidmann-style reliability on real humans. Residual risk: the session judge has no human labels on any human corpus (V21c P6); if it cannot be validated, the project has no tool for the established problem either.

SUPERSEDED. Section 6 was challenged by two fresh-context verifiers at the owner's request ("yes do that"). Section 7 records the verdicts and the corrected statement. Section 6 is retained as the audit trail of what was claimed before the challenge.

## 7. Section 6 under challenge: verdicts and corrected problem statement

Verifiers: `verification/V22a_framing_methodology_verifier.md` (trial methodologist framing: estimands, ITT vs CACE, post-treatment conditioning) and `verification/V22b_framing_safetycase_verifier.md` (dangerous-capability evaluator framing: how system cards actually use uplift numbers). Neither had access to this session's context; V22b did not read V22a and vice versa.

What failed.

1. "Biased low by an unbounded amount" (section 6, "Why it matters"). FAILS in both reports. On a bounded rubric the bias is finite (V22b: OpenAI 2024 0 to 50 scale; Claude 4 trial maximum attainable total uplift 4.0x against a 5x trigger). The sign is not determined: non-use may select on ability. V22a's exploratory recomputation on the OpenAI 2024 CSVs has zero-message expert responses scoring higher (5.85 vs 5.02) and students lower (3.54 vs 4.11), cells of n=4, not in any workspace file, not reproduced. Three published dose-response nulls (Hong tokens, V6 L54; Siden coding Goh 2024 logs, V10 L75; RAND 2026 prompting strategies, V3c L58) were omitted from section 6.
2. "No statement of which estimand" and "the question the safety case asks is what the model enables". FAILS as stated. The Claude 4 card states population (basic STEM background), comparator (2023 tools), and pre-specified thresholds (5x total or 0.8 raw to trigger, 2.8x acceptable), and uses the trial as a rule-out test read conservatively; "what the model enables" is assigned to a separate instrument, a well-elicited model-alone knowledge eval (V22b S1, citing cached card text; V22a F1, F2). The cards use two instruments for two estimands. Section 6 attributed to them a confusion they do not make.
3. "Nobody measures it." FAILS. Hong measured per-participant tokens and tested them as a predictor; RAND 2024 analysed chat logs; RAND 2026 reports prompt counts; OpenAI 2024 released per-response message counts; Anthropic's Claude.ai logs exist (V22a F3c). The defensible narrow claim: no safety-domain card reports a per-participant use distribution, and no trial in the sweep reports a complier or per-protocol estimand alongside ITT.
4. "Invert the ordering: transcript coder first, pre-test is the hypothesis stack." FAILS as a methodological conclusion (V22a F4; V22b S5). A post-hoc transcript dose measure is post-treatment and can describe exposure but cannot identify an effect among users; this is the project's own E3 warning. What identifies it is IV/CACE with a pre-specified use indicator, principal stratification on a baseline covariate, or a mandated-protocol arm. A pre-test is a candidate for that baseline covariate, and every design guideline in the sweep (Kelly 2026 guideline 12, Paskov 2026, STREAM, FMF Tier 1) puts AI-literacy measurement before randomisation. The dependency runs the other way from what section 6 said. The pipeline supports none of IV, CACE or a use indicator (`trial/SCHEMA.md`, `analyze_trial.py`).
5. Layer 2 ("extraction far below what the model holds", R_cap 0.83 to 0.98) is not about compliance: Goh 2024 had 100% use. `results/published_ratios.md` L227 says the ratios bound all human-side factors together and do not isolate elicitation. Ceiling arms are 18 to 30 non-randomised study-team observations; Goh 2025's interval reaches 1.2. Riedl and Weidmann 112% means R_cap is not a ceiling ratio in general (V22b S6g).
6. Confidence labels of 90% and 95% in section 6 were not justified by the citations given (both reports).

What held or was strengthened.

- Layer 1 (heterogeneous use with a non-using minority) is better supported than section 6 cited: OpenAI 2024 20% of task responses, Everett 33% and 11%, Healy 27% of participants, METR 16.4% of recordings, Goh 2025 2 to 5 physicians per case, RealHumanEval 11 transcript-less chat-arm participants (V22a F3a).
- No safety card reports a rubric-matched model-alone or expert-plus-model arm (V22b S2, confirmed against PDF reads in V3b and V10 L37, L61, L844-845). Labs do bound capability by other means (helpful-only models, red teams, elicited model-alone knowledge evals), so "no capability ceiling" overstated but "no ceiling on the trial rubric" holds.
- The ceiling concept is defined for medical vignettes and cyber, statistically degenerate for the Claude 4 group-level planning trial, and undefined for wet-lab (V22b S4). The coherent safety-case ceiling is expert-paired under the participant's time budget, not model-alone.
- Everett's forced full-context arm is the only causal evidence in the sweep that the elicitation lever moves outcome (V22a F5 vii, V10 L98); section 6 omitted it, an omission against its own case.

Corrected problem statement (synthesis of the two verifiers' signed statements; I would sign this one).

Frontier uplift trials report a treatment-policy contrast used as a rule-out threshold test: outcome when a defined population is offered the model without mandated use. Use is heterogeneous and a minority (11 to 33% where reported) never use it. Safety cards report the arm contrast without the per-arm use distribution, without a complier estimand, and without an elicitation-maximised or expert-paired arm on the trial rubric. Where dose was measured it did not predict outcome (Hong, Siden, RAND 2026), so the sign and size of the gap between the reported estimate and what a trained or motivated user would extract is unknown; on a bounded rubric it is finite. Closing it needs a pre-specified use indicator, a baseline covariate for principal stratification or a mandated-protocol arm, and expert-paired ceilings where the task permits. Post-hoc transcript measures describe exposure; they cannot identify.

What this does to the project, revised. The pre-test is not a hypothesis stacked on a missing measurement; it is the baseline covariate a complier or principal-stratum analysis needs, and the field's own guidelines already call for one. The transcript coder is the descriptive exposure measure no card reports. Both are needed; neither is validated. The project's actual bet, stated precisely, is that quality of extraction rather than quantity drives outcome: three published nulls on quantity (tokens, prompt counts, message counts), one provisional conditional positive on quality (V21c P7, coverage given turns), one causal datum on forced content (Everett). If quantity-nulls generalise and quality does not separate from quantity, neither the pre-test nor the coder will predict anything. That is the hypothesis to test first, and RealHumanEval plus Weidmann are the two corpora on disk that can test it.

Caveats on the verifiers themselves. V22b's card quotes come from a cached text extract of the Claude Opus 4 card from an earlier session, not the PDF; the RSP, Preparedness Framework and FSF threshold texts have never been opened in this workspace. V22a's OpenAI non-user cells are n=4 exploratory recomputations. Neither verifier read the other's report. The V22 reports' own file:line citations to README were taken while the concurrent session was editing README, so line numbers may have shifted.

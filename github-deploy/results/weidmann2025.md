# Weidmann, Xu & Deming (2025), "Measuring Human Leadership Skills with Artificially Intelligent Agents": extraction and re-analysis for EST

Generated 2026-09-08 by `analysis/weidmann2025.py` plus a full read of the working paper, the Supplementary Materials, the pre-registration and the OSF replication package. Numbers marked (paper) are quoted from the PDF with the printed page; numbers marked (re-analysis) come from `results/weidmann2025.json`, computed from the public OSF data. Page numbers refer to the printed page of NBER w33662 (PDF page = printed page + 1); "SI p.x" is the Supplementary Materials PDF.

## (a) Citation and URLs

Weidmann, B., Xu, Y., & Deming, D. J. (2025). *Measuring Human Leadership Skills with Artificially Intelligent Agents.* NBER Working Paper 33662, April 2025. DOI 10.3386/w33662.

| Item | Location |
|---|---|
| NBER landing page | https://www.nber.org/papers/w33662 (PDF gated from this machine; landing page saved as `data/weidmann2025/w33662_landing.html`) |
| SSRN mirror | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5207610 |
| Working paper PDF used here | Harvard Skills Lab file `https://680720d1-d2c4-4cbd-9773-4766733b5b75.usrfiles.com/ugd/680720_a4cf798e0ed1465eb18ec9445d6bd89e.pdf` saved as `data/weidmann2025/Weidmann_Xu_Deming_2025_w33662.pdf` (text: `main.txt`, `main_paged.txt`) |
| Supplementary Materials PDF | `https://680720d1-d2c4-4cbd-9773-4766733b5b75.usrfiles.com/ugd/680720_de634e3bf0a549d5994ea89c7fc4cdfb.pdf` saved as `data/weidmann2025/Weidmann_Xu_Deming_2025_SI.pdf` (`si.txt`, `si_paged.txt`; screenshots rendered under `pages/`) |
| Pre-registration | AsPredicted #184,430, https://aspredicted.org/g2pp-t8qv.pdf (saved as `aspredicted_g2pp-t8qv.html`) |
| Replication package | OSF "AI Measurement", DOI 10.17605/OSF.IO/QDY9V, https://osf.io/qdy9v/ ; full mirror (132.8 MB, code + data + materials) at `data/weidmann2025/osf_qdy9v/` with `MANIFEST.json` |
| Publication status (OpenAlex, 2026-09-08) | No journal version found; 8 citing works. |

Data availability statement (paper p.19): "All data, code, and materials are available in a publicly accessible OSF repository (DOI 10.17605/OSF.IO/QDY9V). The GPT prompts used to condition the AI agents, experiment instructions, and screenshots of all task interface are provided in the supplementary materials."

## (b) What they did, in plain terms

249 US adults recruited on Prolific (age 25-55, employed, native English speakers; SI p.2) each led teams on "Hidden Profile" puzzles twice: once with three GPT-4o agents as followers (the "AI leadership test", about 40 minutes, run autonomously online) and once with randomly assigned human followers over Zoom-coordinated sessions (six puzzles, a new random group of three followers for each puzzle, 50 minutes). The two sessions were 1-2 days apart and order was counterbalanced by recruitment round (AI first n=128, human first n=121; p.10, Fig. 6 p.11). Each puzzle is a short scenario with two questions, each with five options; every team member holds 8 clues per puzzle (4 per question, half public and half private), and only by pooling followers' private "disqualifying" clues can the leader rule out wrong options (p.11-12). Communication is text chat in a star network: followers (human or AI) can only message the leader. The leader submits a probability over the five options for each question and is scored by distance from the truth, fully automatically. A leader's causal contribution to human teams is identified by repeated random assignment to fresh follower groups. The headline result is that the AI-test score predicts the human-team leader effect: raw r = 0.67, disattenuated rho = 0.81 (p.8). Good leaders in both settings ask more questions and take more conversational turns (Table 1 p.18), score higher on fluid IQ, emotion perception (PAGE) and an economic decision-making task, and do not differ by gender, age, ethnicity or education (Fig. 5 p.7). Leaders knew the followers were AI (post-survey wording "When you were leading teams of AI agents today", OSF survey file; SI A.2 prompt instructs GPT-4o to act as a research participant follower). The AI version "cost $23 and ran autonomously" versus "$114 per participant and required oversight from two researchers" for the human version (p.10).

## (c) Numbers

### c1. Reported in the paper

| Quantity | Value | Where |
|---|---|---|
| Final leaders analysed | 249 (AI-first 128, human-first 121) | p.10; Fig. 6 p.11 |
| Participant flow | Cond. 1: 124 leaders + 372 followers in human test, 121 completed AI test. Cond. 2: 207 took AI test, 128 completed human test with 384 followers | Fig. 6 p.11 |
| Follower model | "LLM followers were generated using GPT4o" | p.10 |
| Team structure | leader + 3 followers, star network, text chat | p.11-12 |
| Puzzles | 6 per assessment; 2 questions x 5 options; 8 clues per member per puzzle (4 per question), half public half private; disqualifying vs distractor clues | p.11-12 |
| Time | "the task has a time limit" (not quantified in text); AI assessment budgeted 40 min, human 50 min, individual battery 30 min, survey 3 min | p.12; SI p.2, p.5 |
| Sessions | two, 1-2 days apart; AI test could be completed "at their convenience within the next two days" | p.11; SI p.4 |
| Scoring | probabilistic answer, distance from correct option, automatic | p.12; R code |
| Leader fixed-effects R^2 across 6 puzzles | 0.57 AI test, 0.50 human test | p.5 fn.2 |
| Leader effect size (human teams) | +1 SD leader raises team performance about 0.65 SD (about 0.55 SD net of hard skills); good vs bad leader teams fully solve 53% vs 10% | p.5 |
| AI score vs human leader effect | disattenuated rho = 0.81 (n=249), 95% CI "[0.72,88]" (sic, read 0.88); raw r = 0.67 | p.8, fn.7 |
| Same, net of individual task skill (pre-registered alpha) | disattenuated 0.69, CI [0.57, 0.81]; raw 0.52 | p.8, fn.8 |
| Predictors of leader effect (n=249) | emotion perception rho = 0.45 (human) / 0.37 (AI); fluid IQ; decision-making; AI conditional on IQ 0.24; demographics null | p.7-8, Fig. 5, fn.6 |
| Process (Table 1, standardised bivariate coefficients, AI test n=244 / human n=248) | AI: words 0.028, questions 0.150**, turns 0.175***, plural pronouns 0.156**, positive 0.115*; human test same signs | Table 1 p.18 |
| Self-perception | willingness to lead again correlates with overconfidence, rho = 0.29 (AI) / 0.27 (human); self-knowledge weakly related to skill 0.16 (p=.08) / 0.21 | p.9 |
| Cost | $114 per participant + two researchers (human) vs $23 autonomous (AI) | p.10 |
| Recruitment and pay | Prolific, US, 25-55, employed; $15/h; followers about $20, leaders about $30; bonus $4-8 for submitting full responses (completion-contingent, not accuracy-contingent); 11 rounds, Aug 1 to Sep 24 2024 | SI p.2 |
| Pre-registration | AsPredicted #184,430; three predictions (AI score predicts human leader effect; same net of task skill; process/skill correlates replicate) | p.3, p.14 |
| Limitations stated | AI and human tests not identical in logistics; no attempt to replicate full workplace leadership; no validation against real-world outcomes | p.9-10 |

### c2. Re-analysis of the OSF data (`results/weidmann2025.json`)

| Quantity | Value |
|---|---|
| Roster rows in 11 leader files / APPROVED | 482 / 249 (RETURNED 181, AWAITING REVIEW 42, TIMED-OUT 9, REJECTED 1) |
| Human groups led by final leaders | 1,494, all size 4; 1,099 distinct participants, 850 followers |
| AI test participation | 352 Prolific IDs with any answer row; 309 completed all 6 puzzles; 103 started the AI test but are not in the final 249 (attrition mostly Condition 2, consistent with 207 -> 128 in Fig. 6) |
| AI test timing (from timestamps) | fixed 395 s cycle per puzzle (p10 395, p90 400); leader first-to-last answer span median 32.9 min; chat per puzzle median 3.7 min (max 5.5); active chat per leader mean 18.8 min (SD 7.2) |
| AI task score (n=249) | mean 0.648, SD 0.192, min 0.20, median 0.62, max 1.00; 31% of question-dimensions answered perfectly, 2.5% missing (scored 0) |
| Human task score (n=249) | mean 0.627, SD 0.194 |
| AI test reliability (6 puzzles) | split-half Spearman-Brown 0.849 (SD over 1000 splits 0.013); Cronbach alpha 0.840; ICC(1) single puzzle 0.436; ICC(1,6) 0.823; mean inter-puzzle r 0.485; first 3 vs last 3 puzzles r = 0.743 (SB 0.852) |
| Human test reliability | split-half 0.800; alpha 0.799; ICC(1) 0.383; first 3 vs last 3 r = 0.635 |
| Spearman-Brown projection, AI test, by number of puzzles (6.6 min each) | 1: 0.44; 2: 0.61; 3: 0.70; 4: 0.76; 6: 0.82; 8: 0.86; 12: 0.90 |
| Leader FE R^2 | 0.570 AI, 0.503 human (paper 0.57 / 0.50 reproduced) |
| AI score vs human-team score | Pearson 0.670 [0.595, 0.733]; Spearman 0.674; disattenuated 0.813, bootstrap 95% [0.742, 0.882] (paper 0.67 / 0.81 [0.72, 0.88] reproduced) |
| Same by arm | AI-first r = 0.623 (n=128); human-first r = 0.734 (n=121) |
| Human-team score by AI-score quintile | 0.450, 0.530, 0.630, 0.723, 0.801; top-quintile agreement 52%, bottom 48% (chance 20%) |
| Leader effects net of individual HP skill (one-way RE approximation) | sigma_alpha 0.568 AI / 0.511 human; alpha_AI vs alpha_human raw 0.541, disattenuated 0.716 (paper 0.52 / 0.69) |
| Correlates of raw AI score | individual HP 0.535; fluid IQ 0.368; PAGE 0.381; decision-making 0.332; typing speed 0.415; age -0.108 (ns); female 0.053 (ns) |
| Correlates of alpha_AI (net of task skill) | IQ 0.166; PAGE 0.156; decision-making 0.189; typing 0.216; age, female about 0 |
| Post-survey (file 143 rows, 124 of the 249) | self-rated AI-test performance (1-5, mean 3.33) vs actual AI score r = -0.19 (p=.03), vs human score -0.23; self-rated human performance vs human score 0.03; willingness to lead again vs scores about 0.1 / -0.05 (ns); "adapted style for AI" 66% yes, r about 0 with everything; overconfidence vs willingness 0.268 AI / 0.279 human (paper 0.29 / 0.27); self-knowledge vs score 0.145 / 0.214 (paper 0.16 / 0.21) |
| Process metrics, AI chat, n=245 (r with AI score; r with human-team score) | messages sent 0.33; 0.21. words 0.12 (Spearman 0.44); 0.10. share of messages with "?" 0.37; 0.36. GPT-coded question share 0.29; 0.33. turns 0.32; 0.20. plural pronouns (GPT) 0.18; 0.13. positive (GPT) 0.13; 0.11. broadcast share 0.23; 0.14. active chat minutes 0.33; 0.20 |
| "?" heuristic vs authors' GPT question coding | r = 0.82 (n=244) |
| Multivariate standardised betas on AI score (n=244) | words -0.03, turns 0.29, questions 0.25, positive 0.12, plural 0.10; R^2 0.19 |
| Per-puzzle episode | median 20 messages (10 from leader), 3.7 min of chat |
| Clue structure (materials xlsx) | 20 clues per puzzle parsed x 6 puzzles = 120; per puzzle 4 public, 4 leader-private, 12 follower-private, of which 3-6 disqualifying |
| Clue-coverage heuristic (share of 12 follower-private clues surfaced to the leader) | episode mean 0.60 (r with puzzle score 0.42); leader mean 0.58 SD 0.24; r with AI score 0.656 (Spearman 0.681), with human-team score 0.464, with alpha_AI 0.458, alpha_human 0.249; disqualifying-clue coverage r 0.697 / 0.506; coverage reliability across 6 puzzles alpha 0.855, ICC(1) 0.471; coverage vs messages sent 0.53 |
| Order effect (not reported in paper; R script labels it a check "not featured in the final paper") | AI score: human-first 0.743 vs AI-first 0.557, d = 1.10, p < 1e-15; human score: 0.663 vs 0.592, d = 0.37. Adjusted for individual HP, IQ, PAGE, typing, decision-making: human-first minus AI-first = +0.81 SD (SE 0.09) on the AI test, +0.18 SD (SE 0.10) on the human test. Every human-first round mean (0.62-0.82) exceeds every AI-first round mean (0.50-0.61). Human-first leaders also chatted longer (20.4 vs 17.3 min), sent more messages (71 vs 59) and surfaced more clues (coverage 0.66 vs 0.51). |

Reading of the order effect: leaders who had already led six human teams on parallel puzzles 1-2 days earlier scored about 1 SD higher on the AI test, while the reverse carry-over onto the human test is small. This is consistent with a large practice or familiarity effect on the AI-administered version. It is confounded with cohort (arms are whole recruitment rounds) and with differential attrition (Condition 2 lost 79 of 207 AI-tested leaders before the human test), so it is not a clean estimate. The within-arm AI-human correlations (0.62, 0.73) show the predictive result does not depend on pooling arms.

## (d) How EST relates (descriptive)

Both instruments put one person in a text conversation with LLM agents under a time limit, score the outcome automatically against a key, and keep the full transcript for process coding. Differences: Weidmann et al. use three cooperative GPT-4o followers holding planted clues and score the team's probabilistic answer; EST uses a single assistant on technical content and scores which decision-relevant items the participant surfaces, verifies and uses (coverage, specificity, persistence, verification, uptake). Their criterion is the same person's causal effect on randomly assigned human teams measured 1-2 days apart; EST's intended criteria are trial-arm behaviour and uplift outcomes. Their test has six parallel puzzles in one sitting, which is what makes internal-consistency reliability estimable; EST levels are longer and fewer per session. Neither instrument has same-form repeat administration across days.

## (e) What EST should borrow, and what their data say about EST's open questions

Borrow:
1. Several short parallel items per session rather than one long one. Six 6.6-minute puzzles gave split-half 0.85; the SB curve implies about 0.70 with three items and 0.44 with one. EST's reliability will be bounded by item count, not minutes.
2. Planted, enumerable private information with an answer key, so "coverage" is countable without a judge. Their materials (GroupHP_clues_stories.xlsx) are a template: public / private / disqualifying / distractor tags per clue.
3. Probabilistic answers scored by distance, which avoids ceiling effects from binary correctness (31% of dimensions were still perfect).
4. Repeated random assignment as the criterion design, and disattenuation with bootstrap CIs when reporting predictive correlations.
5. Cheap process codes that worked: question share (a "?" count correlates 0.82 with their GPT coding and predicts as well), turn count, and clue coverage. Word count alone is weak (beta about 0 in the multivariate model).
6. Report cost and supervision per administration (they give $23 vs $114).

What their data say about EST's open questions:
- Between-person spread in LLM-interaction skill is large and internally consistent in a general adult sample (leader R^2 0.57; ICC(1) 0.44 per 6.6-minute item). A stratifier built on 4-6 short items is not obviously doomed on reliability grounds.
- Cross-day rank stability: the only cross-day evidence is alternate-form (AI team day 1 vs human team day 2 or vice versa), r = 0.67 raw. That is a lower bound on same-form retest but it is not a retest; EST's "Spearman >= 0.5 across sessions" criterion remains untested by anyone.
- Practice effects are probably large: +0.8 SD adjusted for prior exposure to the task family. Any EST use as a pre-trial stratifier must fix exposure (everyone naive, or everyone given the same warm-up), and a warm-up use should expect real gains.
- A countable coverage metric tracks both the in-task score (0.66) and the external criterion (0.46), and is itself reliable across items (alpha 0.86). This supports EST's choice of coverage as the primary construct.
- Self-report is uninformative or negative: self-rated performance correlated -0.19 with actual AI-test score (n=124). Do not substitute a questionnaire for the behavioural measure.
- Hard-skill correlates are moderate (IQ 0.37, typing 0.42 with raw score; 0.17-0.22 with the skill-adjusted leader effect), so an EST score will partly proxy general ability and typing speed unless those are measured and partialled.
- Completion: 309 of 352 starters finished all six AI puzzles unsupervised; 2.5% of answers missing. Unsupervised administration is feasible with modest loss.

## (f) Data availability and what was computed

Verdict: fully open. The OSF node contains the R analysis script, raw and processed CSV/XLSX for all four parts (Prolific rosters with public Prolific IDs, Qualtrics individual tasks, human and AI Hidden Profile answer logs, both chat logs, GPT-coded chat, post-survey), and materials (task screenshots PDF, clue workbook, individual-task PDFs, survey). No registration or request needed.

Transcript format: `data/ai_hp_chat_raw.csv`, 40,428 rows, columns `created_at` (UTC timestamp, microseconds), `from_source_identifier`, `to_source_identifier` (Prolific ID of leader or bot IDs), `message` (free text), `experiment_configuration_name`, `room`, `grouping_key` (episode), `item_name` (puzzle, e.g. "E2[What is the fish?]"). One row per directed message; a leader "message everyone" appears as three rows. `human_human_chat_raw.csv` has the same schema (54,899 rows). Answers are in `ai_hp_raw_all_sep25.csv` / `human_human_raw_all_sep25.csv` (one row per pid x item x dimension x option credence).

Computed here: N and flow; AI-score distribution; split-half, alpha, ICC, first-half/second-half and SB projections for both tests; leader FE R^2; raw, Spearman, disattenuated and bootstrap AI-human correlations, by arm and by quintile; leader effects net of task skill (one-way random-effects approximation, not lmer REML, so 0.54/0.72 vs paper 0.52/0.69); correlations with IQ, PAGE, decision-making, typing, individual HP, age, sex; all post-survey items; process metrics from raw chat plus the authors' GPT codes; a new clue-coverage heuristic; order/practice effects; per-round table; per-leader CSV (`results/weidmann2025_leader_table.csv`, 249 rows, indexed by the public Prolific IDs as released).

Not computed or not computable: same-form test-retest (does not exist in the design); exact lmer replication (R not run; approximation documented); per-puzzle time limit as displayed to participants (not printed anywhere I could find; 395 s cycle inferred from bot timestamps); ethnicity and education correlations (variables exist in Prolific exports but were not merged here); human-chat process metrics (only AI chat was recoded; authors' human-chat codes were used where needed). Split-half seeds differ from the R script, so third-decimal differences are expected. Four of the 249 leaders have no AI chat rows (process n=245; paper Table 1 n=244). The coverage heuristic is token-overlap based and approximate. No independent verifier has re-run these numbers yet.

## (g) Proposed README prior-art paragraph (179 words)

The closest prior art is Weidmann, Xu and Deming (2025, NBER w33662), who had 249 US adults each lead three GPT-4o agents through six auto-scored hidden-profile puzzles in one unsupervised 40-minute online session. Leader identity explained 57 percent of score variance across puzzles (split-half reliability about 0.85 in our re-analysis of their public data), and the AI-team score correlated 0.67 raw, 0.81 disattenuated (95% CI 0.72 to 0.88), with the same person's causal effect on randomly assigned human teams measured one to two days apart. Leaders who asked more questions and took more turns scored higher; self-rated performance did not track scores. The test was given once per person, so rank stability across sessions is unknown, prior exposure to the task raised scores substantially, and the criterion was a parallel lab task rather than a field outcome. EST differs in probing a single assistant on technical content and in scoring which items the participant surfaces, verifies and uses. Public prompt-injection games (Gandalf, Tensor Trust, HackAPrompt) show lay users can steer models but report no person-level reliability or external validity.

## Follow-ups and related work by the same group (OpenAlex and Skills Lab site, checked 2026-09-08)

- Weidmann, Vecci, Said, Deming & Bhalotra, "How Do You Identify a Good Manager?" QJE 2026 (doi 10.1093/qje/qjag004; NBER w32699): repeated random assignment of managers to teams; leader effects predicted by decision-making skill and IQ, not by self-nomination; same identification strategy as the human arm here.
- Weidmann & Xu, "PAGE: a modern measure of emotion perception", Journal of Intelligence 2025 (doi 10.3390/jintelligence13090116; arXiv 2410.03704): the emotion-perception test used as a predictor in this paper.
- Caplin, Deming, Li, Martin & Marx, "The ABC's of Who Benefits from Working with AI: Ability, Beliefs, and Calibration", Management Science 2025 (doi 10.1287/mnsc.2024.08994; NBER w33021): individual differences in gains from AI assistance depend on calibration of beliefs about own ability.
- Riedl & Weidmann, "Quantifying Human-AI Synergy", PsyArXiv 2025 (doi 10.31234/osf.io/vbkmt_v1): IRT-style separation of human skill, AI skill and collaborative synergy from human-AI task data.
- Caplin, Deming, Leth-Petersen & Weidmann, "Economic Decision-Making Skill Predicts Income in Two Countries", NBER w31674: the Assignment Game decision-making measure used in Part 1.
- Weidmann & Deming, "Team Players: How Social Skills Improve Team Performance", Econometrica 2021: origin of the repeated-random-assignment design for isolating individual contributions to teams.
- No journal version, registered report, or same-form retest follow-up of w33662 was found as of 2026-09-08.

## Known gaps in this write-up

Per-puzzle time limit inferred, not quoted. lmer not replicated exactly. Survey covers 124 of 249 leaders. Order-effect estimate is confounded with recruitment round and attrition. Coverage heuristic unvalidated against hand coding. Numbers not yet checked by a fresh-context verifier.

## Verifier follow-up (V20, 2026-09-08; verification/V20_weidmann2025_verifier.md)

Part A 11/11 paper quotes verified (caveats: evidence that leaders knew followers were AI is the SI B.1 recruitment text,
whereas the SI A.2 agent prompt instructs followers to deny being bots; AsPredicted number is not printed in the paper, only
the URL, and the registration lists four hypotheses). Part B 11/11 re-analysis numbers independently re-derived from the raw
OSF files match. Qualifications adopted in README and on the page: (1) the order effect is a between-cohort association
confounded with round, attrition, baseline skill and administration day, not a causal practice-effect estimate; (2)
"messages sent" and word counts in section c2 count a "message everyone" broadcast once per recipient (raw log rows); on
distinct messages the correlation with AI score is 0.24 (mean 35 messages), not 0.33 (mean 65); the "?"-share result is
unaffected; (3) the post-survey file covers rounds 6 to 11 only (124 of 249), so self-report findings rest on a half-sample.
Privacy: `results/weidmann2025_leader_table.csv` now carries hashed leader ids (sha256 prefix); the raw-id version is kept
only under `data/weidmann2025/` (already public on OSF, not to be redistributed from here). Not independently verified:
covariate-adjusted order effect, lmer leader effects, GPT-coded process metrics, clue-coverage heuristic.

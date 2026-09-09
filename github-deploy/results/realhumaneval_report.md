# RealHumanEval chat arm through the EST transcript coder

Generated 2026-09-08 05:09 by analysis/realhumaneval.py (agent H1). Source: Mozannar et al. 2024, HF `hsseinmz/realhumaneval` (open, license 'CC'). JSON twin: results/realhumaneval_report.json. Figure: results/realhumaneval_fig.png.

## 1. What was built

- 386 (programmer, task) chat episodes from 107 programmers (chat rows 1055); episodes per programmer median 3 (IQR 3-4); chat requests per episode median 2, mean 2.73; user messages per reconstructed episode median 2.
- Arms (episodes): {'gpt35': 119, 'gpt4': 114, 'llama34': 80, 'llama7': 73}; programmers: {'gpt35': 31, 'gpt4': 29, 'llama7': 24, 'llama34': 23}.
- Episodes with a final-code submission: 385; completed (unit tests passed) 249; skipped 68; timed out on last task 68; with >=1 copy event 212.
- Transcript reconstruction: `request` is cumulative within a chat; chats reset per task (no cross-task carry-over found). Within-episode chat clears: 15 of 667 consecutive request pairs; episodes are the concatenation of chat segments (each segment = its last cumulative request + final response). Empty-request rows skipped: 2.
- JOIN HAZARD found and handled: chat `programmer_id` = 0-based row position in study_data.csv = study `programmer_id` - 1 for rows >= 63. Check under this rule: {'rule': 'chat.programmer_id == study row position (== study.programmer_id - 1 for rows>=63)', 'n_chat_programmers': 107, 'arm_and_interface_match': 107, 'tasks_subset_match': 106, 'n_user_message_exact_match': 83}. The naive join on the `programmer_id` column assigns the wrong study row to 103 of 106 programmers (task sets mismatch; arms still match for most because arms are blocked in row order); any third-party reuse of this dataset should be warned.
- Targets: analyst-written (H1) from canonical solution + unit tests, 3-6 per task (78 targets over 17 tasks; analysis/rhe_tasks.py). These are NOT designer-supplied; coverage/specificity are judged against an analyst decomposition of small, fully specified coding tasks, where the task text itself already states most targets. Coverage here mostly measures how much of the task the participant delegated to the model, not thoroughness of inquiry.
- Judge run: {'n_unique': 386, 'n_judged': 386, 'n_failed': 0, 'stopped_early': False}.

### Column inventory

- chat_data.csv: ['request', 'response', 'copy_events', 'logprobs', 'programmer_id', 'timestamp', 'model', 'task_name']
- study_data.csv: ['aiToolTypicalUsage', 'task_id', 'aihelpful', 'skipped_time', 'task_duration', 'model', 'interface', 'n_tasks_completed', 'n_tasks_attempted', 'n_tasks_skipped', 'task_completion_durations', 'mean_task_duration', 'coding_time', 'code_history', 'TLX_frustration', 'TLX_performance', 'TLX_temporal_demand', 'TLX_physical_demand', 'TLX_effort', 'TLX_mental_demand', 'n_sugg_accepted', 'n_sugg_shown', 'sugg_accept_rate', 'time_spent_verifying', 'n_sugg_requested', 'n_sugg_accepted_requested', 'sugg_accept_rate_requested', 'sugg_accept_rate_non_requested', 'n_assistant_response', 'n_user_message', 'n_copy_code_button', 'n_copy_from_chat', 'avg_copy_per_response', 'task_data', 'prog_experience', 'python_experience', 'ai_experience', 'model_size', 'model_name', 'programmer_id']
- tasks_data.csv: ['name', 'task_description', 'function_signature', 'unit_test', 'solution', 'type']

## 2. (A) Base rates of the five behaviours in real users

Episode-level means; 95% CIs from a cluster bootstrap over programmers (2000 resamples). Persistence and uptake are undefined (NaN) when no non-answer was met / nothing was provided; composite scores those as 0 (fixed denominator 5), as in analyze_trial.py.

| behaviour | episode mean | n episodes defined | 95% CI | person median of means | person IQR |
|---|---|---|---|---|---|
| coverage | 0.341 | 386 | [0.312, 0.37] | 0.321 | (0.208, 0.449) |
| specificity | 0.369 | 386 | [0.321, 0.417] | 0.333 | (0.125, 0.5) |
| persistence | 0.436 | 107 | [0.333, 0.539] | 0.417 | (0.0, 1.0) |
| verification | 0.135 | 386 | [0.098, 0.173] | 0.0 | (0.0, 0.25) |
| uptake | 0.886 | 300 | [0.855, 0.914] | 1.0 | (0.833, 1.0) |
| composite | 0.331 | 386 | [0.303, 0.358] | 0.315 | (0.226, 0.404) |
| n_user_turns | 2.806 | 386 | [2.567, 3.039] | 2.5 | (1.75, 3.817) |

Under-elicitation audit (share of episodes; cluster-bootstrap CI):

| indicator | share | n | 95% CI |
|---|---|---|---|
| sessions coverage below half | 0.658 | 386 | [0.605, 0.707] |
| sessions no specific request | 0.541 | 386 | [0.488, 0.594] |
| sessions nonanswer never retried | 0.15 | 386 | [0.111, 0.193] |
| sessions met a nonanswer | 0.277 | 386 | [0.228, 0.331] |
| sessions no verification | 0.865 | 386 | [0.826, 0.902] |
| sessions persistence undefined no nonanswer met | 0.723 | 386 | [0.668, 0.773] |
| sessions uptake undefined nothing provided | 0.223 | 386 | [0.176, 0.275] |
| sessions single user turn | 0.36 | 386 | [0.312, 0.41] |
| sessions uptake below half of defined | 0.077 | 300 | [0.049, 0.109] |
| nonanswer never retried among sessions with nonanswer | 0.542 | 107 | [0.431, 0.649] |
| participants all sessions coverage below half | 0.336 | 107 | NA |

By model arm (episode means): 

| arm | coverage | specificity | persistence | verification | uptake | composite | n_user_turns | n_episodes |
|---|---|---|---|---|---|---|---|---|
| gpt35 | 0.336 | 0.383 | 0.361 | 0.151 | 0.88 | 0.32 | 2.613 | 119 |
| gpt4 | 0.316 | 0.34 | 0.096 | 0.079 | 0.934 | 0.296 | 2.535 | 114 |
| llama34 | 0.361 | 0.369 | 0.523 | 0.2 | 0.858 | 0.358 | 2.962 | 80 |
| llama7 | 0.364 | 0.395 | 0.684 | 0.123 | 0.853 | 0.373 | 3.37 | 73 |

Judge flags: {'episodes_judge_invented_target_ids': 0, 'episodes_turncount_mismatch': 0, 'composite_n_defined_counts': {3: 37, 4: 291, 5: 58}}

## 3. (B) Between-person heterogeneity and rank stability

Split-half: each programmer's episodes ordered by time; odd-position vs even-position episode means; Spearman across programmers with >=2 episodes (bootstrap CI over programmers). ICC(1): one-way random-effects decomposition of episode scores by programmer (programmers with >=2 episodes; unbalanced k0), cluster-bootstrap CI. Spearman-Brown = split-half Pearson stepped up to full length. ICC by task shown for comparison (task-driven variance).

| measure | n programmers | median episodes | split-half Spearman | 95% CI | Spearman-Brown | ICC(1) person | 95% CI | ICC(1) task | between-person SD of means |
|---|---|---|---|---|---|---|---|---|---|
| specificity | 99 | 4.0 | 0.113 (p=0.2649) | [-0.087, 0.303] | 0.211 | 0.072 | [-0.023, 0.17] | 0.028 | 0.278 |
| verification | 99 | 4.0 | -0.049 (p=0.6299) | [-0.218, 0.153] | -0.056 | 0.062 | [-0.046, 0.185] | 0.064 | 0.195 |
| coverage | 99 | 4.0 | 0.13 (p=0.198) | [-0.063, 0.321] | 0.256 | 0.075 | [-0.021, 0.173] | NA | 0.162 |
| composite | 99 | 4.0 | 0.212 (p=0.0353) | [0.007, 0.398] | 0.333 | 0.14 | [0.04, 0.235] | 0.05 | 0.161 |
| n_user_turns | 99 | 4.0 | 0.162 (p=0.1102) | [-0.053, 0.357] | 0.144 | 0.097 | [0.008, 0.189] | 0.132 | 1.404 |
| any_copy | 99 | 4.0 | 0.274 (p=0.0062) | [0.069, 0.459] | 0.427 | 0.236 | [0.103, 0.361] | NA | 0.35 |

Composite first vs last episode: Spearman 0.205 (n=99, 95% CI [0.012, 0.378]); mean change last-first 0.018.

## 4. (C) Self-report validity

This section reports 44 correlations and two group-mean tables without multiplicity correction; read effect sizes and intervals. Extreme-group contrasts (for example Always vs Never on specificity) were not pre-specified: the five-group Kruskal-Wallis for specificity is p = 0.15 and the ordinal Spearman p = 0.067 (V13), so no single group difference should be quoted as established. Survey item wordings are not in the dataset card and are unverified.

n programmers = 107. ai_experience counts: {'Often (multiple times a week)': 34, 'Sometimes (once a week)': 27, 'Rarely (once a month)': 25, 'Always (daily)': 11, 'Never': 10}. aiToolTypicalUsage counts: {'Agree': 52, 'Disagree': 24, 'Neutral': 22, 'Strongly Agree': 6, 'Strongly Disagree': 3} (Likert agreement item from the post-study survey; exact statement wording not in the dataset card (UNVERIFIED; RealHumanEval paper appendix)).

### ai_exp_ord (ordinal) vs person-level behaviour and outcomes

| y | n | Spearman | 95% CI | p | R^2 linear | eta^2 categorical |
|---|---|---|---|---|---|---|
| specificity_mean | 107 | 0.178 | [-0.012, 0.365] | 0.0673 | 0.055 | 0.087 |
| verification_mean | 107 | 0.201 | [0.003, 0.376] | 0.0374 | 0.021 | 0.033 |
| coverage_mean | 107 | -0.032 | [-0.214, 0.145] | 0.7459 | 0.002 | 0.013 |
| composite_mean | 107 | 0.13 | [-0.066, 0.318] | 0.1833 | 0.014 | 0.034 |
| uptake_mean | 97 | -0.179 | [-0.374, 0.007] | 0.0786 | 0.025 | 0.04 |
| n_user_turns_mean | 107 | -0.023 | [-0.212, 0.164] | 0.8161 | 0.0 | 0.004 |
| copy_rate | 107 | 0.212 | [0.041, 0.382] | 0.0282 | 0.042 | 0.084 |
| n_tasks_completed | 107 | 0.079 | [-0.117, 0.257] | 0.4215 | 0.003 | 0.04 |
| mean_task_duration | 106 | 0.022 | [-0.163, 0.205] | 0.8213 | 0.002 | 0.087 |
| completed_rate | 107 | 0.116 | [-0.074, 0.3] | 0.2346 | 0.013 | 0.068 |
| aihelpful | 107 | -0.142 | [-0.327, 0.058] | 0.1453 | 0.013 | 0.091 |

### typical_ord (ordinal) vs person-level behaviour and outcomes

| y | n | Spearman | 95% CI | p | R^2 linear | eta^2 categorical |
|---|---|---|---|---|---|---|
| specificity_mean | 107 | 0.053 | [-0.147, 0.253] | 0.5868 | 0.006 | 0.012 |
| verification_mean | 107 | -0.01 | [-0.209, 0.185] | 0.9157 | 0.003 | 0.032 |
| coverage_mean | 107 | 0.027 | [-0.162, 0.22] | 0.7833 | 0.0 | 0.028 |
| composite_mean | 107 | 0.034 | [-0.169, 0.229] | 0.7286 | 0.0 | 0.022 |
| uptake_mean | 97 | 0.072 | [-0.122, 0.271] | 0.485 | 0.0 | 0.076 |
| n_user_turns_mean | 107 | -0.131 | [-0.317, 0.059] | 0.1791 | 0.034 | 0.055 |
| copy_rate | 107 | 0.003 | [-0.171, 0.188] | 0.9793 | 0.0 | 0.023 |
| n_tasks_completed | 107 | 0.018 | [-0.17, 0.198] | 0.8519 | 0.001 | 0.031 |
| mean_task_duration | 106 | -0.02 | [-0.207, 0.17] | 0.8412 | 0.003 | 0.056 |
| completed_rate | 107 | 0.108 | [-0.074, 0.303] | 0.2672 | 0.005 | 0.012 |
| aihelpful | 107 | 0.378 | [0.196, 0.544] | 0.0001 | 0.138 | 0.157 |

### prog_ord (ordinal) vs person-level behaviour and outcomes

| y | n | Spearman | 95% CI | p | R^2 linear | eta^2 categorical |
|---|---|---|---|---|---|---|
| specificity_mean | 107 | -0.035 | [-0.235, 0.157] | 0.72 | 0.001 | 0.055 |
| verification_mean | 107 | -0.221 | [-0.382, -0.048] | 0.0222 | 0.045 | 0.046 |
| coverage_mean | 107 | -0.062 | [-0.242, 0.117] | 0.5287 | 0.001 | 0.029 |
| composite_mean | 107 | -0.093 | [-0.279, 0.105] | 0.3413 | 0.002 | 0.04 |
| uptake_mean | 97 | -0.015 | [-0.229, 0.197] | 0.8877 | 0.001 | 0.045 |
| n_user_turns_mean | 107 | -0.111 | [-0.295, 0.078] | 0.2569 | 0.012 | 0.038 |
| copy_rate | 107 | -0.169 | [-0.358, 0.015] | 0.0821 | 0.02 | 0.059 |
| n_tasks_completed | 107 | 0.013 | [-0.176, 0.199] | 0.8963 | 0.0 | 0.015 |
| mean_task_duration | 106 | -0.027 | [-0.213, 0.175] | 0.7807 | 0.008 | 0.025 |
| completed_rate | 107 | 0.047 | [-0.148, 0.24] | 0.6333 | 0.011 | 0.028 |
| aihelpful | 107 | -0.16 | [-0.339, 0.016] | 0.0988 | 0.023 | 0.027 |

### python_ord (ordinal) vs person-level behaviour and outcomes

| y | n | Spearman | 95% CI | p | R^2 linear | eta^2 categorical |
|---|---|---|---|---|---|---|
| specificity_mean | 107 | -0.001 | [-0.189, 0.173] | 0.9944 | 0.0 | 0.018 |
| verification_mean | 107 | -0.165 | [-0.344, 0.029] | 0.0904 | 0.023 | 0.033 |
| coverage_mean | 107 | 0.1 | [-0.09, 0.298] | 0.3054 | 0.006 | 0.033 |
| composite_mean | 107 | 0.094 | [-0.092, 0.278] | 0.333 | 0.011 | 0.018 |
| uptake_mean | 97 | 0.121 | [-0.089, 0.323] | 0.2374 | 0.031 | 0.052 |
| n_user_turns_mean | 107 | -0.029 | [-0.215, 0.156] | 0.7684 | 0.003 | 0.012 |
| copy_rate | 107 | -0.036 | [-0.235, 0.178] | 0.7132 | 0.0 | 0.0 |
| n_tasks_completed | 107 | 0.24 | [0.05, 0.423] | 0.0127 | 0.05 | 0.05 |
| mean_task_duration | 106 | -0.183 | [-0.367, 0.01] | 0.0607 | 0.081 | 0.134 |
| completed_rate | 107 | 0.113 | [-0.077, 0.303] | 0.247 | 0.012 | 0.044 |
| aihelpful | 107 | -0.175 | [-0.357, 0.02] | 0.0711 | 0.029 | 0.031 |

### Group means by ai_experience (mean, n, t-based 95% CI)

| group | specificity_mean | verification_mean | coverage_mean | composite_mean | uptake_mean | n_user_turns_mean | copy_rate | n_tasks_completed | mean_task_duration | completed_rate | aihelpful |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Never | 0.198 (n=10, [0.036, 0.36]) | 0.05 (n=10, [-0.063, 0.163]) | 0.332 (n=10, [0.247, 0.418]) | 0.241 (n=10, [0.15, 0.333]) | 0.891 (n=8, [0.755, 1.026]) | 2.735 (n=10, [1.665, 3.805]) | 0.427 (n=10, [0.195, 0.658]) | 4.2 (n=10, [2.738, 5.662]) | 284.834 (n=10, [251.021, 318.648]) | 0.577 (n=10, [0.371, 0.782]) | 5.3 (n=10, [3.421, 7.179]) |
| Rarely (once a month) | 0.338 (n=25, [0.247, 0.43]) | 0.129 (n=25, [0.027, 0.231]) | 0.338 (n=25, [0.288, 0.387]) | 0.317 (n=25, [0.272, 0.362]) | 0.913 (n=25, [0.855, 0.971]) | 2.981 (n=25, [2.468, 3.495]) | 0.458 (n=25, [0.35, 0.565]) | 3.48 (n=25, [2.837, 4.123]) | 328.133 (n=25, [285.479, 370.787]) | 0.518 (n=25, [0.396, 0.641]) | 6.4 (n=25, [5.301, 7.499]) |
| Sometimes (once a week) | 0.34 (n=27, [0.229, 0.451]) | 0.11 (n=27, [0.049, 0.172]) | 0.336 (n=27, [0.27, 0.403]) | 0.326 (n=27, [0.256, 0.396]) | 0.874 (n=25, [0.781, 0.966]) | 2.86 (n=27, [2.297, 3.424]) | 0.429 (n=27, [0.271, 0.587]) | 3.63 (n=27, [2.934, 4.325]) | 416.442 (n=26, [339.121, 493.762]) | 0.702 (n=27, [0.608, 0.797]) | 7.0 (n=27, [6.095, 7.905]) |
| Often (multiple times a week) | 0.352 (n=34, [0.253, 0.451]) | 0.137 (n=34, [0.073, 0.201]) | 0.3 (n=34, [0.232, 0.367]) | 0.306 (n=34, [0.244, 0.369]) | 0.869 (n=29, [0.787, 0.952]) | 2.771 (n=34, [2.231, 3.31]) | 0.661 (n=34, [0.541, 0.781]) | 3.647 (n=34, [3.133, 4.162]) | 359.322 (n=34, [301.955, 416.689]) | 0.576 (n=34, [0.471, 0.68]) | 5.147 (n=34, [4.266, 6.028]) |
| Always (daily) | 0.559 (n=11, [0.334, 0.783]) | 0.204 (n=11, [0.06, 0.348]) | 0.346 (n=11, [0.232, 0.46]) | 0.37 (n=11, [0.249, 0.491]) | 0.761 (n=10, [0.545, 0.977]) | 2.937 (n=11, [2.011, 3.863]) | 0.545 (n=11, [0.306, 0.785]) | 4.545 (n=11, [3.447, 5.644]) | 292.076 (n=11, [220.801, 363.351]) | 0.707 (n=11, [0.508, 0.906]) | 5.455 (n=11, [3.883, 7.026]) |

### Group means by aiToolTypicalUsage

| group | composite_mean | specificity_mean | verification_mean | n_user_turns_mean | n_tasks_completed |
|---|---|---|---|---|---|
| Strongly Disagree | 0.309 (n=3, [-0.309, 0.928]) | 0.264 (n=3, [-0.616, 1.144]) | 0.111 (n=3, [-0.367, 0.589]) | 4.167 (n=3, [1.581, 6.752]) | 2.333 (n=3, [0.899, 3.768]) |
| Disagree | 0.334 (n=24, [0.266, 0.403]) | 0.312 (n=24, [0.204, 0.42]) | 0.171 (n=24, [0.065, 0.278]) | 3.26 (n=24, [2.521, 3.998]) | 3.75 (n=24, [3.0, 4.5]) |
| Neutral | 0.278 (n=22, [0.21, 0.346]) | 0.387 (n=22, [0.277, 0.497]) | 0.109 (n=22, [0.031, 0.187]) | 2.618 (n=22, [2.149, 3.087]) | 4.091 (n=22, [3.355, 4.827]) |
| Agree | 0.314 (n=52, [0.27, 0.357]) | 0.358 (n=52, [0.275, 0.442]) | 0.105 (n=52, [0.055, 0.154]) | 2.71 (n=52, [2.327, 3.093]) | 3.692 (n=52, [3.239, 4.145]) |
| Strongly Agree | 0.376 (n=6, [0.161, 0.591]) | 0.385 (n=6, [0.066, 0.704]) | 0.218 (n=6, [0.084, 0.353]) | 2.73 (n=6, [1.723, 3.737]) | 3.667 (n=6, [2.087, 5.247]) |

## 5. (D) Behaviour -> outcome

episode-level models: completed ~ behaviour + arm FE + prog_ord (logistic, cluster-robust SE by programmer); log(time_in_task) among completed ~ same (OLS, CR1). One model per behaviour. Person-level: n_tasks_completed ~ behaviour_mean + arm + prog_ord (OLS, HC via 1 cluster per person).

Episode completion rate {'overall': 0.647, 'n': 385, 'by_arm': {'gpt35': 0.695, 'gpt4': 0.675, 'llama34': 0.588, 'llama7': 0.589}}.

### Episode completed (logistic; coefficient of the behaviour term, log-odds and odds ratio, cluster-robust 95% CI)

| behaviour | n episodes | clusters | b (log-odds) | OR | OR 95% CI | p |
|---|---|---|---|---|---|---|
| specificity | 385 | 107 | 0.2149 | 1.24 | [0.778, 1.974] | 0.3653 |
| verification | 385 | 107 | -0.4925 | 0.611 | [0.339, 1.102] | 0.1018 |
| coverage | 385 | 107 | 0.3765 | 1.457 | [0.613, 3.463] | 0.394 |
| composite | 385 | 107 | 0.0544 | 1.056 | [0.437, 2.554] | 0.9038 |
| uptake | 299 | 97 | -0.161 | 0.851 | [0.342, 2.12] | 0.7294 |
| n_user_msgs | 385 | 107 | -0.221 | 0.802 | [0.719, 0.893] | 0.0001 |
| any_copy | 385 | 107 | 0.0036 | 1.004 | [0.669, 1.507] | 0.986 |

### log(time in task) among completed episodes (OLS; behaviour coefficient, CR1 95% CI)

| behaviour | n | clusters | b | 95% CI | p | model R^2 |
|---|---|---|---|---|---|---|
| specificity | 249 | 97 | 0.0738 | [-0.1011, 0.2486] | 0.4044 | 0.05 |
| verification | 249 | 97 | 0.3676 | [0.1213, 0.6138] | 0.0038 | 0.078 |
| coverage | 249 | 97 | 0.4706 | [0.1348, 0.8065] | 0.0065 | 0.079 |
| composite | 249 | 97 | 0.5391 | [0.1633, 0.9149] | 0.0054 | 0.078 |
| uptake | 201 | 88 | 0.0136 | [-0.3873, 0.4146] | 0.9462 | 0.075 |
| n_user_msgs | 249 | 97 | 0.1878 | [0.148, 0.2276] | 0.0 | 0.307 |
| any_copy | 249 | 97 | -0.0004 | [-0.1891, 0.1883] | 0.9966 | 0.048 |

### Person level: n_tasks_completed ~ behaviour mean + arm + prog_ord (OLS, robust 95% CI)

| behaviour (person mean) | n | b | 95% CI | p | R^2 |
|---|---|---|---|---|---|
| specificity_mean | 107 | -0.085 | [-1.15, 0.9799] | 0.8745 | 0.08 |
| verification_mean | 107 | -1.5185 | [-2.9764, -0.0607] | 0.0414 | 0.11 |
| coverage_mean | 107 | 0.5812 | [-1.29, 2.4524] | 0.5393 | 0.083 |
| composite_mean | 107 | -0.175 | [-2.1579, 1.8079] | 0.8614 | 0.08 |
| uptake_mean | 97 | 0.9439 | [-0.1783, 2.0661] | 0.0983 | 0.102 |
| n_user_turns_mean | 107 | -0.1782 | [-0.3886, 0.0323] | 0.0962 | 0.102 |
| copy_rate | 107 | 0.5833 | [-0.2818, 1.4483] | 0.1841 | 0.095 |

### Copy events (logged) vs judged uptake

- Episodes with any copy event: 0.549; episodes where the judge found assistant content in the final code (used non-empty): 0.733; raw agreement of the two indicators: 0.692.
- Among episodes with uptake defined (n=300): mean judged uptake 0.89 with a copy event (n=199) vs 0.878 without (n=101); Spearman -0.023 (cluster-bootstrap 95% CI [-0.136, 0.087]).
- copy events undercount uptake (participants can retype); judged 'used' compares assistant content with final code, so it also credits retyped/adapted code.

## 6. Verbatim excerpts (programmer text verbatim, lightly trimmed; assistant text truncated)

### Vague ask (two-word query) — episode `87:t_test` (task t_test, arm gpt35, completed=True, copy events=0)

Judged: {'coverage': 0.2, 'specificity': 0.0, 'persistence': 0.0, 'verification': 0.0, 'uptake': None, 'composite': 0.04, 'n_nonanswers': 1.0, 'n_retries': 0.0}. The task needs a two-sample t statistic with an n-2 variance denominator; the participant typed a two-word search-engine query, got generic numpy.var() boilerplate (population variance) and asked nothing further. The episode was nonetheless completed, so this shows low elicitation from the assistant, not low programming skill: the participant did the task-specific work without it.

> **USER:** numpy variance
>
> **ASSISTANT:** To calculate the variance using numpy in Python, you can use the `numpy.var()` function. Here's an example:
> 
> ```python
> import numpy as np
> 
> # Input data
> data = np.array([1, 2, 3, 4, 5])
> 
> # Calculate variance
> variance = np.var(data)
> 
> # Print variance
> print("Vari [...]
>

### General ask, requirement never stated — episode `194:t_test` (task t_test, arm gpt35, completed=False, copy events=1)

Judged: {'coverage': 0.2, 'specificity': 0.0, 'persistence': None, 'verification': 0.0, 'uptake': 1.0, 'composite': 0.24, 'n_nonanswers': 0.0, 'n_retries': 0.0}. Participant asked how to compute a sample variance in general terms; the assistant gave the textbook n-1 formula. The task's non-standard n-2 denominator was never mentioned to the assistant and nothing was checked. This was the participant's last task and it timed out, so non-completion is not attributable to the elicitation alone.

> **USER:** how do I calculate the variance of a sample?
>
> **ASSISTANT:** You can calculate the variance of a sample using the following steps:
> 
> 1. Calculate the mean (average) of the sample.
> 2. Subtract the mean from each sample data point and square the result.
> 3. Sum up all the squared differences.
> 4. Divide the sum by the number of data points minus 1 (this is known as the degrees of fre [...]
>

### Wrong answer accepted and copied (non-answer never retried) — episode `125:sum_product` (task sum_product, arm llama7, completed=True, copy events=1)

Judged: {'coverage': 0.333, 'specificity': 0.0, 'persistence': 0.0, 'verification': 0.0, 'uptake': None, 'composite': 0.067, 'n_nonanswers': 1.0, 'n_retries': 0.0}. The assistant's code computes a sum, labels it a product, and prints an impossible output; the participant copied it (1 copy event) and asked nothing further. Coded as a non-answer with zero retries and zero verification in the chat; the episode was completed, so any correction happened in the editor, outside the conversation.

> **USER:** how can i enumerate over a python list and get the product of all numbers
>
> **ASSISTANT:** To calculate the product of all numbers in a Python list, you can use a combination of the `map()` and `sum()` functions. Here's an example:
> ```
> numbers = [1, 2, 3, 4, 5]
> product = sum(map(lambda x: x, numbers))
> print(product)  # Output: 120
> ```
> In this example, we first create a list of numbers `numbers`. Then, we use the `map( [...]
>

### No task content at all — episode `113:even_odd_count` (task even_odd_count, arm llama34, completed=True, copy events=0)

Judged: {'coverage': 0.0, 'specificity': 0.0, 'persistence': None, 'verification': 0.0, 'uptake': None, 'composite': 0.0, 'n_nonanswers': 0.0, 'n_retries': 0.0}. The entire exchange. The participant opened the assistant, typed a greeting, and never returned to it for this task.

> **USER:** sup
>
> **ASSISTANT:** Hello! How can I assist you today?
>

### Strong: decomposed, verified, corrected the assistant — episode `82:order_by_points` (task order_by_points, arm gpt35, completed=True, copy events=0)

Judged: {'coverage': 0.75, 'specificity': 1.0, 'persistence': 1.0, 'verification': 1.0, 'uptake': 1.0, 'composite': 0.95, 'n_nonanswers': 1.0, 'n_retries': 1.0}. Participant asked narrow factual questions, pasted their own function for review, pushed back when the assistant mis-stated the goal, then asked the precise tie-breaking question the task hinges on. Completed.

> **USER:** Do you see any errors in this function?
> def order_by_points(nums):
>     ans = []
>     for number in nums:
>         split = [int(x) for x in str(number) if x != '-']
>         if number < 0:
>             split[0] = -split[0]
>         ans.append((sum(split), number))
>     ans.sort()
>     return [x[1] for x in ans]
>
> **ASSISTANT:** Yes, there is an error in the provided function. When sorting the `ans` list, it uses the default sorting order, which is ascending based on the sum of the split digits. However, the desired behavior is to sort in descending order based on [...]
>
> **USER:** The goals is to be sorted in ascending order based on the sum of the split digits
>
> **ASSISTANT:** Apologies for the confusion. If the goal is to sort the list in ascending order based on the sum of the split digits, the original code is correct. The `.sort()` method, without any additional arguments, sorts the list in ascending order. [...]
>
> **USER:** How could I sort based on the sum of the digits, but if there is a tie use the order in the original list?
>

### Persistent verification against an assistant that claims success — episode `66:encode_message` (task encode_message, arm gpt35, completed=True, copy events=5)

Judged: {'coverage': 0.75, 'specificity': 1.0, 'persistence': None, 'verification': 1.0, 'uptake': 1.0, 'composite': 0.75, 'n_nonanswers': 0.0, 'n_retries': 4.0}. Participant re-tested each revision with failing asserts four times; the assistant repeatedly apologised and asserted the new version passed without change in behaviour. Verification scored 1 (persistence is undefined here because the assistant never gave a non-answer; repeated re-testing is not what the persistence subscale measures); the episode was completed. It illustrates what in-conversation verification looks like in this corpus: pasting a failing test rather than asking the assistant whether its code is correct.

> **USER:** assert encode('Mudasir') == 'mWDCSKR'
> 
> this asser fails
>
> **ASSISTANT:** Apologies for the confusion. It seems there was a misunderstanding in the initial code implementation. Here's the corrected version of the encode_message function:
> 
> ```python
> def encode_message(messag [...]
>
> **USER:** assert encode('TEST') == 'tgst'
>
> **ASSISTANT:** Apologies for the confusion. It seems there was another misunderstanding. Here's the corrected version of the encode_message function to satisfy the assertion `assert encode_message('TEST') == 'tgst'` [...]
>
> **USER:** assert encode('TEST') == 'tgst'
>
> **ASSISTANT:** Apologies for the mistake in the previous responses. Here's the corrected version of the encode_message function to satisfy the assertion `assert encode_message('TEST') == 'tgst'`:
> 
> ```python
> def enco [...]
>

## 7. What this does and does not show

- Domain and vintage: short, fully specified Python tasks with unit tests, chat models GPT-3.5-turbo / GPT-4o / CodeLlama-7b/34b-instruct (data collected 2023-24). Elicitation behaviour toward a coding assistant when the task text can be pasted verbatim is not the same construct as eliciting withheld or judgement-laden information; coverage here reflects whether the participant conveyed the task's requirements to the assistant at all (337 of 386 episodes paste none of the task text; 12 paste at least half), which is a different construct from thoroughness in extracting withheld information.
- 'Submission' is the last 15-second autosave of the editor, not a captured submit event; 29 of 249 completed episodes have stored code that does not parse and only 112 stored snapshots pass the unit tests (V13), so uptake is judged against approximately-final code.
- The composite split-half interval is fragile: under the verifier's bootstrap seed it straddles zero ([-0.004, 0.397] vs [0.007, 0.398] here), and 46% of programmers have a one-episode half. Read the split-half rows as 'weak and imprecise', not as established non-zero stability.
- One sitting: all episodes are consecutive tasks inside one ~40-minute session, so split-half stability is within-session consistency, not test-retest across days. Task identity and order are confounded with episode within a person (each participant works through one fixed task sequence). Task set is not fixed per condition: all five task sets (0 to 4) occur in both the no-model and the chat arm (arm by task set chi-square 3.41, dof 4, p = 0.49, n = 157; by assigned model p = 0.62), so task set is not confounded with arm.
- Thin episodes: median 2 chat requests per episode; persistence is undefined in most episodes (few non-answers from coding assistants) and verification is a single binary per episode, so per-episode scores are coarse and per-person means rest on ~4 episodes.
- Model arm is randomised between persons: it confounds person-level outcome comparisons less than behaviour comparisons, but arm differences in assistant quality change what behaviours are needed (e.g. more retries with CodeLlama). Arm fixed effects are included in D; B and C pool arms.
- Selection: only episodes where the participant opened the chat exist (388 of ~700 programmer-task cells in the chat arm); people/tasks with no chat use are absent, so base rates are conditional on choosing to ask.
- The judge (claude-sonnet via CLI, JUDGE_SYS unchanged) was validated only on the synthetic EST lab-troubleshooting transcripts (V2), not on coding chats; no human double-coding was done here. Targets are analyst-written. Treat absolute levels as indicative and between-person contrasts as the more trustworthy quantity.
- Outcome 'completed' = unit tests passed at submission per study task_data; time_in_task is only interpretable for completed tasks; the last task of a session is often cut off by the timer.
- No causal claim: behaviour-outcome associations are cross-sectional and confounded by programmer skill (prog_ord is a coarse control) and by task difficulty (harder tasks elicit more turns and fail more).

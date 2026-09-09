# OpenAI 2024 self-report check

Source: cdn.openai.com/building-an-early-warning-system-for-llm-aided-biological-threat-creation/{participants,responses}.csv
Arm: llm_internet only. Outcome: sum of accuracy over 5 stages (0-50). Predictor: llm_experience (4 levels).

| subset | n | outcome | R² ordinal [95% boot CI] | R² 4-category | Spearman | level means |
|---|---|---|---|---|---|---|
| all_llm_arm | 50 | total_accuracy | 0.057 [0.00, 0.20] | 0.076 | -0.19 | {'Never used': 24.85, 'Use almost every day': 20.0, 'Use at least once every few weeks': 23.64, 'Used a few times': 23.18} |
| all_llm_arm | 50 | total_msgs | 0.040 [0.00, 0.16] | 0.087 | 0.20 | {'Never used': 28.15, 'Use almost every day': 36.92, 'Use at least once every few weeks': 45.36, 'Used a few times': 34.18} |
| expert_llm_arm | 25 | total_accuracy | 0.034 [0.00, 0.34] | 0.036 | 0.22 | {'Never used': 25.17, 'Use at least once every few weeks': 27.67, 'Used a few times': 25.86} |
| expert_llm_arm | 25 | total_msgs | 0.086 [0.00, 0.37] | 0.131 | 0.19 | {'Never used': 28.33, 'Use at least once every few weeks': 45.33, 'Used a few times': 26.86} |
| student_llm_arm | 25 | total_accuracy | 0.001 [0.00, 0.16] | 0.014 | -0.04 | {'Never used': 21.0, 'Use almost every day': 20.0, 'Use at least once every few weeks': 20.62, 'Used a few times': 18.5} |
| student_llm_arm | 25 | total_msgs | 0.008 [0.00, 0.23] | 0.060 | -0.10 | {'Never used': 26.0, 'Use almost every day': 36.92, 'Use at least once every few weeks': 45.38, 'Used a few times': 47.0} |

LLM-arm task-responses with zero messages to the model: 20.0%; participants with zero messages across all 5 tasks: 4

Caveats: n=50 (25/25), 4-level self-report, outcome graded by study's rubric; R² CIs are wide. This is a check that self-report is a weak proxy, not evidence that a performance test would do better (that requires a pilot). Identifiability: within-cohort n = 25 gives 80% power only for Spearman >= 0.55 (0.40 with both cohorts and a cohort term); simulation shows power <= 0.33 for any self-report with r <= 0.5 to a skill with rho <= 0.5 to outcome; message count does not predict accuracy either (within-cohort +0.06, CI -0.23 to +0.35). See critique2_20260908/B12_openai_null_ident/openai_null_identifiability.md and verification/V39_openai_null_identifiability.md.

"""Known-truth checks for est/estimands.py. Run: .venv/bin/python tests/test_estimands.py
Simulates a trial with latent extraction propensity a, selection (Y(0) correlated with a), one-sided non-use, and a
stratum-dependent effect; checks that CACE recovers the complier effect, trimming bounds contain the true E[Y(0)|H],
covariate tightening narrows without losing the truth, and trim_bounds is exact on a hand case."""
import pathlib, sys, math
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from est.estimands import md_section, trim_bounds, one_sided_cace, stratum_bounds, covariate_tightened_bounds, run, simulate_value_of_covariate

fails = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond: fails.append(name)

# 1. trim_bounds exact on a hand case
lo, hi = trim_bounds([1, 2, 3, 4, 5, 6], 0.5)
check("trim_bounds hand case", abs(lo - 2.0) < 1e-12 and abs(hi - 5.0) < 1e-12, f"{lo},{hi}")
lo, hi = trim_bounds([1, 2, 3, 4], 0.375)          # k = 1.5: lowest = (1 + 0.5*2)/1.5 = 4/3; highest = (4 + 0.5*3)/1.5 = 11/3
check("trim_bounds fractional", abs(lo - 4 / 3) < 1e-12 and abs(hi - 11 / 3) < 1e-12, f"{lo},{hi}")
lo, hi = trim_bounds([3, 1, 2], 1.0); check("trim_bounds full share = mean", lo == hi == 2.0)

# 2. large-sample simulation with known truth
rng = np.random.default_rng(7); n = 200_000
a = rng.standard_normal(n)                                     # latent extraction propensity
y0 = 0.5 * a + math.sqrt(0.75) * rng.standard_normal(n)        # selection: better extractors score higher without the model
use = (rng.random(n) < 0.8) | (a > 1.0)                        # 80% use, heavy extractors always use
H_true = (a >= np.quantile(a, 2 / 3)) & use
tau = np.where(H_true, 1.0, 0.2) * use                         # effect only if used; larger in H
y1 = y0 + tau
z = rng.random(n) < 0.5
score = np.where(use, a, a.min() - 1)                           # non-users carry the minimum score
T_y, T_use, T_score, C_y = y1[z], use[z].astype(int), score[z], y0[~z]
true_itt = float((y1 - y0).mean()); true_cace = float(tau[use].mean())
c = one_sided_cace(T_y, T_use, C_y)
check("ITT recovered", abs(c["itt_diff"] - true_itt) < 0.02, f"{c['itt_diff']:.4f} vs {true_itt:.4f}")
check("CACE recovered (one-sided)", abs(c["cace_diff"] - true_cace) < 0.02, f"{c['cace_diff']:.4f} vs {true_cace:.4f}")
mu0c_true = float(y0[use].mean()); check("complier control mean recovered", abs(c["mu0_compliers"] - mu0c_true) < 0.02, f"{c['mu0_compliers']:.4f} vs {mu0c_true:.4f}")
s = stratum_bounds(T_y, T_score, C_y, 1 / 3)
H_sim = score >= s["cut"]; mu0H_true = float(y0[H_sim].mean()); eff_true = float(tau[H_sim].mean())
check("trimming bounds contain true E[Y0|H]", s["H"]["mu0_lo"] - 0.02 <= mu0H_true <= s["H"]["mu0_hi"] + 0.02, f"[{s['H']['mu0_lo']:.3f},{s['H']['mu0_hi']:.3f}] truth {mu0H_true:.3f}")
check("effect set contains true H effect", s["H"]["effect_lo"] - 0.02 <= eff_true <= s["H"]["effect_hi"] + 0.02, f"[{s['H']['effect_lo']:.3f},{s['H']['effect_hi']:.3f}] truth {eff_true:.3f}")
check("naive E3a is inside the set but not at the truth", s["H"]["effect_lo"] <= s["H"]["naive_minus_all_controls"] <= s["H"]["effect_hi"] and abs(s["H"]["naive_minus_all_controls"] - eff_true) > 0.1, f"naive {s['H']['naive_minus_all_controls']:.3f}")
# covariate tightening: W correlated 0.9 with a
w = 0.9 * a + math.sqrt(1 - 0.81) * rng.standard_normal(n)
sub = rng.choice(n, 20_000, replace=False); zs = z[sub]
cv = covariate_tightened_bounds(y1[sub][zs], (score[sub] >= s["cut"])[zs], w[sub][zs][:, None], y0[sub][~zs], w[sub][~zs][:, None], n_bins=5)
check("covariate bounds narrower", cv["width"] < s["H"]["width"] * 0.8, f"{cv['width']:.3f} vs {s['H']['width']:.3f}; AUC {cv['predictor_auc_crossfit']:.3f}")
check("covariate bounds still contain truth", cv["mu0_lo"] - 0.05 <= mu0H_true <= cv["mu0_hi"] + 0.05, f"[{cv['mu0_lo']:.3f},{cv['mu0_hi']:.3f}] truth {mu0H_true:.3f}")
# pure-noise covariate must not tighten materially
wn = rng.standard_normal(n)
cvn = covariate_tightened_bounds(y1[sub][zs], (score[sub] >= s["cut"])[zs], wn[sub][zs][:, None], y0[sub][~zs], wn[sub][~zs][:, None], n_bins=5)
check("noise covariate does not tighten (<5%)", cvn["width"] > s["H"]["width"] * 0.95, f"{cvn['width']:.3f} vs {s['H']['width']:.3f}; AUC {cvn['predictor_auc_crossfit']:.3f}")

# 3. run() end to end on a small frame (trial-sized) with a threshold
m = rng.choice(n, 160, replace=False)
P = pd.DataFrame({"participant_id": [f"p{i}" for i in range(160)], "arm": np.where(z[m], "llm", "control"), "outcome": np.where(z[m], y1[m], y0[m]) + 3.0, "pre_w": w[m]})
R = run(P, score=pd.Series(np.where(z[m], score[m], np.nan)), use=pd.Series(np.where(z[m], use[m].astype(float), np.nan)), pre_cols=["pre_w"],
        thresholds=[("demo", "diff", 0.5), ("demo_ratio", "ratio", 1.2)], B=200)
check("run() returns all blocks", all(k in R for k in ("exposure", "itt", "cace", "strata", "threshold_checks", "not_identified")))
check("run() stratum set well-formed", R["strata"]["high_extraction"]["effect_set"][0] <= R["strata"]["high_extraction"]["effect_set"][1])
check("run() covariate block present", "effect_set" in R["strata"]["high_extraction_covariate_tightened"], str(R["strata"]["high_extraction_covariate_tightened"].get("skipped")))

# 4. simulation of covariate value runs and is monotone-ish
sim = simulate_value_of_covariate(reps=30, rhos=(0.0, 0.5, 1.0))
wr = [r["width_reduction"] for r in sim["rows"]]
check("width reduction increases with rho", wr[0] < wr[1] < wr[2], str([round(x, 3) for x in wr]))
check("unconditional coverage ~1", all(r["coverage_unconditional"] >= 0.9 for r in sim["rows"]), str([r["coverage_unconditional"] for r in sim["rows"]]))

# 5. V24 gaps (verifier report V24, not shipped): tie rule, sharpness, cross-fitting, trial-size noise floor
from est.estimands import stratum_cut, permutation_noise_floor
# 5a. ties at the cut are included (mutation M7: strict '>' would drop them)
sc_t = np.array([0.9] * 10 + [0.72] * 5 + [0.5] * 21)           # n 36, k = ceil(12) = 12 -> cut 0.72, H = 15
cut_t = stratum_cut(sc_t, 1 / 3); sb = stratum_bounds(np.ones(36), sc_t, np.ones(10), 1 / 3)
check("tie rule: count-based cut includes ties", cut_t == 0.72 and sb["n_H"] == 15, f"cut {cut_t} n_H {sb['n_H']}")
check("tie rule: no float boundary at k = (1-1/3)*117", stratum_bounds(np.ones(118), np.r_[np.linspace(0, 1, 116), 0.39583333332500004, 0.39583333332500004], np.ones(10), 1 / 3)["n_H"] == 40, "k = ceil(118/3) = 40")
# 5b. sharpness with truth at the EDGE of the set (mutation M6, complement share, would give a wider set that still contains the truth).
#     Y(0) = a exactly, H = top third of a: E[Y0|H] = phi(q)/(1/3) = 1.0908 must equal the upper bound, and the lower bound must be -1.0908.
rng2 = np.random.default_rng(11); n2 = 400_000; a2 = rng2.standard_normal(n2); z2 = rng2.random(n2) < 0.5
s2 = stratum_bounds(a2[z2] + 1.0, a2[z2], a2[~z2], 1 / 3)
check("sharp bounds match analytic +-1.0908 when truth is at the edge", abs(s2["H"]["mu0_hi"] - 1.0908) < 0.02 and abs(s2["H"]["mu0_lo"] + 1.0908) < 0.02, f"[{s2['H']['mu0_lo']:.3f},{s2['H']['mu0_hi']:.3f}]")
# 5c. cross-fitting is real (mutation M11): 30 pure-noise covariates at trial size would give in-sample AUC ~0.8; cross-fit AUC must stay near 0.5
aucs = []
for sd in range(10):
    r3 = np.random.default_rng(100 + sd); nT3, nC3 = 118, 39
    a3 = r3.standard_normal(nT3); H3 = a3 >= np.quantile(a3, 2 / 3); W3 = r3.standard_normal((nT3 + nC3, 30))
    cv3 = covariate_tightened_bounds(a3 + 1, H3, W3[:nT3], r3.standard_normal(nC3), W3[nT3:], seed=sd)
    aucs.append(cv3["predictor_auc_crossfit"])
check("cross-fit AUC of 30 noise covariates stays < 0.6 at n 118/39", np.mean(aucs) < 0.6, f"mean {np.mean(aucs):.3f}, max {max(aucs):.3f}")
# 5d. trial-size noise floor: a pure-noise covariate at n 118/39 tightens by ~6%; run() must report a permutation null and must NOT flag it as beyond noise in most seeds
flags = []; reds = []; p95s = []
for sd in range(8):
    r4 = np.random.default_rng(200 + sd); nT4, nC4 = 118, 39; nn = nT4 + nC4
    a4 = r4.standard_normal(nn); y04 = 0.5 * a4 + math.sqrt(0.75) * r4.standard_normal(nn); z4 = np.zeros(nn, bool); z4[r4.choice(nn, nT4, replace=False)] = True
    P4 = pd.DataFrame({"participant_id": [f"q{i}" for i in range(nn)], "arm": np.where(z4, "llm", "control"), "outcome": y04 + np.where(z4, 0.5, 0.0), "pre_noise1": r4.standard_normal(nn), "pre_noise2": r4.standard_normal(nn), "pre_noise3": r4.standard_normal(nn)})
    R4 = run(P4, score=pd.Series(np.where(z4, a4, np.nan)), use=pd.Series(np.where(z4, 1.0, np.nan)), pre_cols=["pre_noise1", "pre_noise2", "pre_noise3"], B=0, perm_reps=60, seed=sd)
    ct4 = R4["strata"]["high_extraction_covariate_tightened"]; flags.append(bool(ct4["tightening_beyond_noise"])); reds.append(ct4["width_reduction_vs_unconditional"]); p95s.append(ct4["permutation_null"]["p95_reduction"])
check("permutation null present at trial size", all(p == p for p in p95s), f"p95 {[round(p, 3) for p in p95s]}")
check("pure-noise covariates flagged 'beyond noise' in at most 1 of 8 seeds", sum(flags) <= 1, f"flags {flags}; observed {[round(r, 3) for r in reds]}")
check("noise floor at n 118/39 is material (median pure-noise reduction > 3%)", np.median(reds) > 0.03, f"median {np.median(reds):.3f}")
# 5e. exposure, ceiling and outer-interval threshold columns exist
R5 = run(P, score=pd.Series(np.where(z[m], score[m], np.nan)), use=pd.Series(np.where(z[m], use[m].astype(float), np.nan)), pre_cols=["pre_w"], thresholds=[("t", "diff", 0.5)], B=50,
         intensity=pd.Series(np.where(z[m], rng.integers(0, 12, 160), np.nan)), ceilings={"model_alone": 6.0}, perm_reps=20)
check("exposure carries an intensity distribution", "quantiles_treated" in R5["exposure"]["use_intensity"])
check("ceiling block reports gaps and share of gain", "share_of_ceiling_gain_reached_H" in R5["ceiling"]["model_alone"])
check("threshold rows classify the outer interval and the ceiling", "high_extraction_set_outer_ci" in R5["threshold_checks"][0] and "ceilings_vs_control" in R5["threshold_checks"][0])
check("bootstrap failures are counted", R5["bootstrap"]["failed"] == 0 and "first_error" in R5["bootstrap"])

# 6. V25 gaps (verifier report V25, not shipped): fold-seed averaging, re-seed check, two-sided label, calibrated simulation
# 6a. the median-over-splits estimator is less seed-dependent than one split (mutation: fold_reps ignored would make the SDs equal)
r6 = np.random.default_rng(600); nT6, nC6 = 997, 301; nn6 = nT6 + nC6
a6 = r6.standard_normal(nn6); y06 = np.round(np.clip(0.5 * a6 + math.sqrt(0.75) * r6.standard_normal(nn6), -1, 1)) / 2 + 0.5   # three-valued outcome like HELPMed
z6 = np.zeros(nn6, bool); z6[r6.choice(nn6, nT6, replace=False)] = True; W6 = np.c_[0.15 * a6 + r6.standard_normal(nn6), r6.standard_normal((nn6, 12))]
H6 = z6 & (a6 >= np.quantile(a6[z6], 0.5))
w1 = [covariate_tightened_bounds(y06[z6], H6[z6], W6[z6], y06[~z6], W6[~z6], seed=sd, fold_reps=1)["width"] for sd in range(12)]
w30 = [covariate_tightened_bounds(y06[z6], H6[z6], W6[z6], y06[~z6], W6[~z6], seed=sd, fold_reps=30)["width"] for sd in range(12)]
check("fold_reps 30 estimator varies less across seeds than one split", np.std(w30) < 0.5 * np.std(w1), f"sd one-split {np.std(w1):.5f}, sd 30-split {np.std(w30):.5f}")
cv6 = covariate_tightened_bounds(y06[z6], H6[z6], W6[z6], y06[~z6], W6[~z6], seed=0, fold_reps=7)
check("fold_reps output names the estimator and keeps the split widths", cv6.get("fold_reps") == 7 and len(cv6["split_widths"]) == 7 and "median" in cv6["estimator"])
# 6b. run() reports the re-seed check and the split distribution, and the null uses the same estimator (mutation M13: unpermuted null would give share 1.0 and p95 == observed)
P6 = pd.DataFrame({"participant_id": [f"h{i}" for i in range(nn6)], "arm": np.where(z6, "llm", "control"), "outcome": y06, **{f"pre_w{j}": W6[:, j] for j in range(W6.shape[1])}})
R6 = run(P6, score=pd.Series(np.where(z6, a6, np.nan)), use=pd.Series(np.where(z6, 1.0, np.nan)), pre_cols=[f"pre_w{j}" for j in range(W6.shape[1])], top_share=0.5, B=0, perm_reps=40, fold_reps=10, reseeds=3, seed=1)
ct6 = R6["strata"]["high_extraction_covariate_tightened"]; pn6 = ct6["permutation_null"]
check("run() carries reseed_check and split distribution", ct6["reseed_check"]["reseeds"] == 3 and ct6["width_reduction_across_fold_splits"]["n_splits"] == 10 and ct6["fold_reps"] == 10)
check("permutation null is a real null (not the observed value repeated)", pn6["share_null_at_or_above_observed"] < 1.0 and abs(pn6["p95_reduction"] - ct6["width_reduction_vs_unconditional"]) > 1e-9, f"share {pn6['share_null_at_or_above_observed']}, p95 {pn6['p95_reduction']:.4f}, obs {ct6['width_reduction_vs_unconditional']:.4f}")
check("verdict string is one of the tested cases", ct6["tightening_verdict"].split(":")[0].split(",")[0] in ("beyond noise in the original and every re-seed", "at the edge of the noise floor", "within noise") or ct6["tightening_verdict"].startswith(("clears the noise floor in every seed but", "not tested")), ct6["tightening_verdict"])
# 6c. two-sided label: control_model_access != none must flip the flag, the assumption text, the md header and add a not_identified line
R6b = run(P6, score=pd.Series(np.where(z6, a6, np.nan)), use=pd.Series(np.where(z6, 1.0, np.nan)), pre_cols=[], B=0, perm_reps=0, control_model_access="usual_sources", control_model_exposure={"share_llm": 0.49})
md6 = "\n".join(md_section(R6b))
check("two-sided: control_has_no_model False and assumption text says NOT one-sided", R6b["exposure"]["control_has_no_model"] is False and any("NOT one-sided" in x for x in R6b["cace"]["assumptions"]))
check("two-sided: md header and not_identified say so", "could use models outside the platform" in md6 and any("against NO model" in x for x in R6b["not_identified"]) and "no-model counterfactual" not in md6)
md6a = "\n".join(md_section(R6)); check("one-sided default unchanged in md", "non-compliance is one-sided" in md6a and "no-model counterfactual" in md6a)
# 6d. calibrated simulation: Y(0) takes only the empirical values, widths on the outcome scale, coverage holds, reductions monotone
sim6 = simulate_value_of_covariate(n_t=300, n_c=100, top_share=0.5, rhos=(0.0, 0.5, 0.9), reps=30, seed=3, control_y0=y06[~z6])
check("calibrated simulation labels itself and stays on the outcome scale", sim6["calibration"].startswith("Y(0) drawn from the trial") and 0 < sim6["rows"][0]["mean_width_unconditional"] < 1.0, sim6["calibration"][:60])
check("calibrated simulation: reduction monotone in rho and coverage ~1", sim6["rows"][0]["width_reduction"] < sim6["rows"][1]["width_reduction"] < sim6["rows"][2]["width_reduction"] and all(r["coverage_unconditional"] >= 0.9 for r in sim6["rows"]), str([round(r["width_reduction"], 3) for r in sim6["rows"]]))
check("generic simulation still labels itself GENERIC", simulate_value_of_covariate(n_t=60, n_c=20, rhos=(0.0,), reps=5)["calibration"].startswith("GENERIC"))

# 7. V24b (verifier report V24b item 3, not shipped): behaviours the suite could not see. Each check states the mutation it catches.
# 7a. M13: the null must actually permute W. With a covariate that nearly reveals H, the unpermuted statistic is far above any null draw.
r7 = np.random.default_rng(700); nT7, nC7 = 150, 60
a7 = r7.standard_normal(nT7); H7 = a7 >= np.quantile(a7, 2 / 3)
y7T = a7 + r7.standard_normal(nT7); y7C = r7.standard_normal(nC7) * 1.2
W7T = np.c_[a7 + 0.1 * r7.standard_normal(nT7)]; W7C = np.c_[r7.standard_normal(nC7) * 1.2]
cv7 = covariate_tightened_bounds(y7T, H7, W7T, y7C, W7C, seed=3, fold_reps=5); w07 = stratum_bounds(y7T, a7, y7C, 1 / 3)["H"]["width"]
obs7 = 1 - cv7["width"] / w07
pn7 = permutation_noise_floor(y7T, H7, W7T, y7C, W7C, w07, reps=40, seed=3, observed=obs7, fold_reps=5)
check("M13: permuted null sits far below a strongly informative covariate (W really is permuted)", obs7 > 0.15 and pn7["p95_reduction"] < obs7 / 2 and pn7["share_null_at_or_above_observed"] == 0.0, f"obs {obs7:.3f}, null p95 {pn7['p95_reduction']:.3f}, share {pn7['share_null_at_or_above_observed']}")
# 7b. M14: share counts permutations AT the observed value (>=), tested by passing the null's own maximum as 'observed'
pn7b = permutation_noise_floor(y7T, H7, W7T, y7C, W7C, w07, reps=15, seed=5, observed=float("nan"), fold_reps=2)
reds7 = []
rngm = np.random.default_rng(5 + 7); Wm = np.vstack([W7T, W7C])
for _ in range(15):
    Wp = Wm[rngm.permutation(len(Wm))]; cvm = covariate_tightened_bounds(y7T, H7, Wp[:nT7], y7C, Wp[nT7:], seed=int(rngm.integers(1e9)), fold_reps=2); reds7.append(1 - cvm["width"] / w07)
pn7c = permutation_noise_floor(y7T, H7, W7T, y7C, W7C, w07, reps=15, seed=5, observed=max(reds7), fold_reps=2)
check("M14: a permutation equal to the observed value is counted (share >= 1/reps)", pn7c["share_null_at_or_above_observed"] >= 1 / 15 - 1e-12, f"share {pn7c['share_null_at_or_above_observed']:.4f}, reproduced max {max(reds7):.4f} vs reported p95 {pn7b['p95_reduction']:.4f}")
# 7c. M15 / M16 / M18 / M19 on the section-5 fixture: ceiling share denominator, outer interval really outer, counters
cm5 = R5["itt"]["control_mean"]; tm5 = R5["itt"]["treated_mean"]; ce5 = R5["ceiling"]["model_alone"]
check("M15: share of ceiling gain = (treated - control) / (ceiling - control)", abs(ce5["share_of_ceiling_gain_reached_treated"] - (tm5 - cm5) / (6.0 - cm5)) < 1e-12 and abs(ce5["gap_from_control_mean"] - (6.0 - cm5)) < 1e-12, f"{ce5['share_of_ceiling_gain_reached_treated']:.4f}")
H5 = R5["strata"]["high_extraction"]; oc5 = H5["effect_set_outer_ci95"]
check("M16: outer interval contains the point set and is wider", oc5[0] <= H5["effect_set"][0] + 1e-12 and oc5[1] >= H5["effect_set"][1] - 1e-12 and (oc5[1] - oc5[0]) > (H5["effect_set"][1] - H5["effect_set"][0]), f"outer {oc5}, set {H5['effect_set']}")
# M18: a cell with H members but no controls must be counted and its H share reported; built by giving controls a covariate range the H members never share
W18T = (a7 + 0.5 * r7.standard_normal(nT7))[:, None]; W18C = r7.uniform(-3.0, -0.2, (nC7, 1))     # controls never reach the top treated tertile: that cell holds H members and no controls, the middle cell holds both
cv18 = covariate_tightened_bounds(y7T, H7, W18T, y7C, W18C, seed=1, fold_reps=1, n_bins=3)
check("M18: cells with H members and no controls are counted, with the excluded H share", (not cv18.get("skipped")) and cv18["cells_without_controls"] >= 1 and cv18["share_of_H_excluded_no_controls"] > 0 and cv18["cells_with_fewer_than_min_controls"] == 0 and abs(sum(c["weight"] for c in cv18["cells"]) - 1) < 1e-9, f"{ {k: cv18.get(k) for k in ('skipped', 'cells_without_controls', 'share_of_H_excluded_no_controls', 'cells_with_fewer_than_min_controls')} }")
# M19: bootstrap failures are counted, forced by an outcome the point function cannot handle in some resamples (a ceiling dict with a non-numeric value raises inside point)
P19 = P.copy(); P19.loc[P19.index[:3], "outcome"] = np.nan
R19 = run(P19, score=pd.Series(np.where(z[m], score[m], np.nan)), use=pd.Series(np.where(z[m], use[m].astype(float), np.nan)), pre_cols=[], B=0, perm_reps=0)
check("NaN outcomes are dropped from every quantity with a count (V24b item 7)", R19["n_dropped_missing_outcome"] == 3 and R19["n_treated"] + R19["n_control"] == len(P) - 3 and R19["itt"]["diff"] == R19["itt"]["diff"] and "dropped from every quantity" in "\n".join(md_section(R19)), f"dropped {R19['n_dropped_missing_outcome']}, itt {R19['itt']['diff']:.3f}")
import est.estimands as _em
_orig = _em.one_sided_cace
_calls = {"n": 0}
def _flaky(*a, **k):
    _calls["n"] += 1
    if _calls["n"] % 2 == 0: raise ValueError("forced failure for M19")
    return _orig(*a, **k)
_em.one_sided_cace = _flaky
try:
    R20 = run(P, score=pd.Series(np.where(z[m], score[m], np.nan)), use=pd.Series(np.where(z[m], use[m].astype(float), np.nan)), pre_cols=[], B=20, perm_reps=0)
finally:
    _em.one_sided_cace = _orig
check("M19: bootstrap failures are counted and the first error kept", R20["bootstrap"]["failed"] >= 5 and R20["bootstrap"]["kept"] + R20["bootstrap"]["failed"] == 20 and "forced failure" in str(R20["bootstrap"]["first_error"]) and "failed" in "\n".join(md_section(R20)), f"kept {R20['bootstrap']['kept']}, failed {R20['bootstrap']['failed']}")

# M22 (V25 regression): an md line lost its f-prefix and printed "{_f(q[0.1], 1)}" verbatim into every report. Every md rendered above
# must be free of unformatted Python placeholders, and the intensity line must carry real numbers.
import re as _re
_md5 = "\n".join(md_section(R5))
_mds = {"R5": _md5, "R6b": md6, "R6": md6a, "R19": "\n".join(md_section(R19)), "R20": "\n".join(md_section(R20))}
_bad = {k: _re.findall(r"\{_f\(|\{ui\[|\{q\[|\{sa\[|\{e\[|\{R\[|\{ct\[|\{H\[", v) for k, v in _mds.items()}
check("M22: no unformatted placeholders in any rendered md", not any(_bad.values()), str({k: v for k, v in _bad.items() if v}))
_il = [l for l in _md5.split("\n") if l.startswith("Use intensity in the treated arm")]
check("M22: intensity line prints numeric quantiles", bool(_il) and _re.search(r"quantiles 10/25/50/75/90% = [-\d.]+ / [-\d.]+ / [-\d.]+ / [-\d.]+ / [-\d.]+, mean [-\d.]+;", _il[0]) is not None, _il[0][:120] if _il else "no intensity line")

# 8. V25b (verifier report V25b section C, not shipped): two core properties the suite could not see.
# MX1: every call of the covariate estimator inside run() (point, every bootstrap replicate, every permutation, every re-seed) must carry the
# caller's fold_reps. A bootstrap that silently fell back to one split would pass every earlier check.
_orig_cov = _em.covariate_tightened_bounds
_seen = []
def _recording_cov(*a, **k):
    if len(a) <= 5: _seen.append(k.get("fold_reps", 1))      # outer calls from run(); the per-split recursion passes everything positionally
    return _orig_cov(*a, **k)
_em.covariate_tightened_bounds = _recording_cov
try:
    R8 = run(P6, score=pd.Series(np.where(z6, a6, np.nan)), use=pd.Series(np.where(z6, 1.0, np.nan)), pre_cols=[f"pre_w{j}" for j in range(W6.shape[1])], top_share=0.5, B=6, perm_reps=4, fold_reps=3, reseeds=2, seed=1)
finally:
    _em.covariate_tightened_bounds = _orig_cov
check("MX1: point, bootstrap, null and re-seed calls all carry fold_reps", len(_seen) == 1 + 6 + 4 + 2 and all(v == 3 for v in _seen), f"calls {len(_seen)}, fold_reps seen {sorted(set(_seen))}")
# run()-level frame from the 7a fixture: the covariate nearly reveals H, so the original seed clears the null by a wide margin
P8 = pd.DataFrame({"participant_id": [f"q{i}" for i in range(nT7 + nC7)], "arm": ["llm"] * nT7 + ["control"] * nC7, "outcome": np.r_[y7T, y7C], "pre_w": np.r_[W7T[:, 0], W7C[:, 0]]})
_s8 = pd.Series(np.r_[a7, np.full(nC7, np.nan)]); _u8 = pd.Series(np.r_[np.ones(nT7), np.full(nC7, np.nan)])
R8a = run(P8, score=_s8, use=_u8, pre_cols=["pre_w"], top_share=1 / 3, B=0, perm_reps=40, fold_reps=5, reseeds=3, seed=1)
ct8a = R8a["strata"]["high_extraction_covariate_tightened"]
check("MX2 precondition: the original seed and every re-seed clear the null on the 7a fixture", ct8a["tightening_beyond_noise"] is True and ct8a["reseed_check"]["n_clearing_null_p95"] == 3, f"obs {ct8a['width_reduction_vs_unconditional']:.3f}, p95 {ct8a['permutation_null']['p95_reduction']:.3f}, verdict {ct8a['tightening_verdict']}")
# MX2: the re-seed gate must be able to FAIL. Force the re-seeded estimator to return a width far above the unconditional width (reduction
# well below any null draw) while leaving the original seed untouched; the verdict must be the edge case and the flag False.
_w0 = R8a["strata"]["high_extraction"]["width"]; _reseed_seeds = {1 + 9973 * (r + 1) for r in range(3)}
def _sabotaged_cov(*a, **k):
    out = _orig_cov(*a, **k)
    if k.get("seed") in _reseed_seeds and out and not out.get("skipped"): out = {**out, "width": 10 * _w0}
    return out
_em.covariate_tightened_bounds = _sabotaged_cov
try:
    R8b = run(P8, score=_s8, use=_u8, pre_cols=["pre_w"], top_share=1 / 3, B=0, perm_reps=40, fold_reps=5, reseeds=3, seed=1, thresholds=[("t", "diff", 0.0)])
finally:
    _em.covariate_tightened_bounds = _orig_cov
ct8 = R8b["strata"]["high_extraction_covariate_tightened"]
check("MX2: a re-seed that misses the null flips the verdict to the edge case", ct8["tightening_beyond_noise"] is False and ct8["tightening_verdict"].startswith("at the edge") and ct8["reseed_check"]["n_clearing_null_p95"] == 0 and "AT THE EDGE" in "\n".join(md_section(R8b)), ct8["tightening_verdict"])
# 8b. V25b B2 corner cases: (i) all seeds clear but AUC <= 0.5 gets its own label, not the seed-dependent one; (ii) perm_reps = 0 reads "not tested", not "within noise" or "noise-level";
# (iii) a real narrowing below the reporting floor is labelled negligible in a separate field and in the verdict string.
def _auc_killer(*a, **k):
    out = _orig_cov(*a, **k)
    return {**out, "predictor_auc_crossfit": 0.45} if out and not out.get("skipped") else out
_em.covariate_tightened_bounds = _auc_killer
try:
    R8c = run(P8, score=_s8, use=_u8, pre_cols=["pre_w"], top_share=1 / 3, B=0, perm_reps=40, fold_reps=5, reseeds=3, seed=1, thresholds=[("t", "diff", 0.0)])
finally:
    _em.covariate_tightened_bounds = _orig_cov
ct8c = R8c["strata"]["high_extraction_covariate_tightened"]
check("B2(i): all seeds clear with AUC <= 0.5 is labelled as the AUC failure, not as seed-dependent", ct8c["tightening_beyond_noise"] is False and ct8c["tightening_verdict"].startswith("clears the noise floor in every seed but") and "cell-count artefact" in "\n".join(md_section(R8c)), ct8c["tightening_verdict"])
R8d = run(P6, score=pd.Series(np.where(z6, a6, np.nan)), use=pd.Series(np.where(z6, 1.0, np.nan)), pre_cols=[f"pre_w{j}" for j in range(W6.shape[1])], top_share=0.5, B=0, perm_reps=0, fold_reps=3, seed=1, thresholds=[("t", "diff", 0.0)])
ct8d = R8d["strata"]["high_extraction_covariate_tightened"]; md8d = "\n".join(md_section(R8d))
check("B2(ii): perm_reps = 0 reads 'not tested' everywhere, never 'noise-level'", ct8d["tightening_beyond_noise"] is None and ct8d["tightening_verdict"].startswith("not tested") and "NOT TESTED" in md8d and "not tested against a noise floor" in md8d and "NOISE-LEVEL" not in md8d and "noise-level" not in md8d, ct8d["tightening_verdict"])
check("B2(iii): magnitude is reported separately with the floor stated", ct6.get("tightening_magnitude", {}).get("negligible_below_reduction") == 0.05 and ct6["tightening_magnitude"]["label"] in ("negligible", "material") and abs(ct6["tightening_magnitude"]["absolute_units"] - ct6["width_reduction_vs_unconditional"] * R6["strata"]["high_extraction"]["width"]) < 1e-12)
R8e = run(P8, score=_s8, use=_u8, pre_cols=["pre_w"], top_share=1 / 3, B=0, perm_reps=40, fold_reps=5, reseeds=3, seed=1, negligible_reduction=0.999, thresholds=[("t", "diff", 0.0)])
ct8e = R8e["strata"]["high_extraction_covariate_tightened"]; md8e = "\n".join(md_section(R8e))
check("B2(iii): a real narrowing below the floor says so in the verdict and the md", ct8e["tightening_beyond_noise"] is True and "negligible in size" in ct8e["tightening_verdict"] and "NEGLIGIBLE" in md8e and "here it is negligible" in md8e, ct8e["tightening_verdict"])

# 8c. V27 finding 1: the estimate-table row and the threshold header used a binary on tightening_beyond_noise while the verdict paragraph
# had four cases, so an "at the edge" run printed "NOISE-LEVEL narrowing" in its table. The three surfaces must agree in every branch.
def _md_surfaces(R):
    md = md_section(R); row = next(l for l in md if "with baseline covariates" in l); head = next((l for l in md if l.startswith("| threshold |")), "")
    return "\n".join(md), row, head
_want = {"edge": (R8b, "AT THE EDGE", "at the edge of the noise floor"), "auc": (R8c, "AUC is not above 0.5", "AUC not above 0.5"),
         "negligible": (R8e, "NEGLIGIBLE", "beyond noise but negligible"), "not tested": (R8d, "NOT TESTED", "not tested against a noise floor")}
for _k, (_R, _row_tok, _head_tok) in _want.items():
    _md, _row, _head = _md_surfaces(_R)
    check(f"V27: '{_k}' run labels the table row and threshold header consistently with the verdict (no NOISE-LEVEL leak)",
          _row_tok in _row and _head_tok in _head and "NOISE-LEVEL" not in _row and "noise-level" not in _head, f"row: {_row[-160:]} | head: {_head[-90:]}")
check("V27: the not-tested row names the reason from the permutation block, not a hardcoded one", "(perm_reps = 0)" in _md_surfaces(R8d)[1] and R8d["strata"]["high_extraction_covariate_tightened"]["permutation_null"]["skipped"] == "perm_reps = 0")

print("\n" + ("ALL PASS" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)

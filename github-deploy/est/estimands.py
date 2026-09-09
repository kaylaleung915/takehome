"""Use-adjusted uplift estimands for a two-arm trial (one-sided non-compliance by default; two-sided when the caller says the control arm could use models elsewhere).

Problem this answers (docs/assessment_2026-09-08.md section 7): uplift trials report a treatment-policy contrast
(ITT) and read it against a threshold whose referent is a motivated user; use is heterogeneous, a minority never use
the model, and nobody reports the per-arm use distribution, a complier estimand, or the effect among people who
extract well. This module computes, from arm + outcome + a per-participant use/extraction measure, every quantity
that IS identified or set-identified by randomisation alone, and labels what is not. Section 7's three omitted
objects map onto the output as: (1) `exposure` (use share plus, when an intensity series is supplied, its quantiles);
(2) `cace` and `strata` (complier estimand; principal-stratum set with covariate tightening and a permutation noise
floor); (3) `ceiling` (gap of every treated quantity to a supplied ceiling value; reported as missing when none is).

V24 (verifier report, 2026-09-08, not shipped) fixes in this version: count-based stratum cut with ties
included (was a float-decided np.nanquantile boundary); permutation noise floor for the covariate tightening (the
old text called any tightening "genuine prediction"; at n_c 39 pure noise buys 6 to 7%); the outer bootstrap interval
is labelled as conservative for the parameter, not for the set; threshold checks also classify the outer intervals;
non-use is labelled under its operational definition rather than as "never used"; dropped cells and bootstrap
failures are counted and printed.
V25 (verifier report, not shipped) fixes: the covariate-tightened estimator is the median over `fold_reps`
fold assignments (a single split's reduction was a noise draw; the same estimator is used for point, null and
bootstrap); `control_model_access` labels two-sided non-compliance when the control arm could use models outside
the platform (HELPMed controls could); the simulation can be calibrated to the trial's control outcome
distribution and realised pi_H instead of a generic normal outcome; stratum H is described by what produced the
score, not as "motivated users".

Estimands (Z = arm, D = used the model, X = extraction score under treatment, H = X >= cut, Y = outcome):
  ITT        E[Y|Z=1] - E[Y|Z=0]                                  point-identified
  CACE       ITT / P(D=1|Z=1)   (Bloom 1984; Angrist, Imbens & Rubin 1996; one-sided non-compliance)
             complier control mean mu0c = (E[Y|Z=0] - (1-pi_c) E[Y|Z=1,D=0]) / pi_c, so the complier RATIO is also
             identified. Needs the exclusion restriction: assignment without use has no effect.
  Stratum H  effect among people who WOULD extract at or above the cut if treated (a principal stratum, Frangakis &
             Rubin 2002). E[Y(1)|H] is observed; E[Y(0)|H] is the mean of an unknown share pi_H of the control
             arm, so it lies between the means of the lowest and highest pi_H fraction of control outcomes
             (Horowitz & Manski 1995; Zhang & Rubin 2003; Lee 2009 trimming). Sharp without further assumptions.
  Covariate- the same bounds computed within cells of a pre-randomisation predictor of H (cross-fitted), then
  tightened  averaged with weights P(cell|H). The better the baseline covariate predicts H, the narrower the set;
             perfect prediction collapses it to a point. This is the quantitative value of a pre-test.
Not identified from any post-hoc analysis: the effect of MAKING people extract well (a trained-user estimand).
That needs a mandated-protocol arm; the report says so rather than printing a number.
"""

from __future__ import annotations
import math
import numpy as np, pandas as pd

NAN = float("nan")


# ----------------------------------------------------------------------------- primitives
def trim_bounds(y, share):
    """Sharp bounds on the mean of an unidentified sub-population that makes up `share` of the sample y was drawn
    from: (mean of the lowest share*n values, mean of the highest share*n values), fractional last observation."""
    y = np.sort(np.asarray(y, dtype=float))
    y = y[~np.isnan(y)]
    n = len(y)
    if n == 0 or share <= 0 or share != share:
        return NAN, NAN
    k = min(share, 1.0) * n
    if k >= n:
        return float(y.mean()), float(y.mean())

    def mean_lowest(v, k):
        full = int(math.floor(k))
        frac = k - full
        s = v[:full].sum() + (v[full] * frac if frac > 1e-12 else 0.0)
        return float(s / k)

    return mean_lowest(y, k), -mean_lowest(-y[::-1], k)


def _ratio(a, b):
    return float(a / b) if (b == b and a == a and b > 0) else NAN


def one_sided_cace(T_y, T_use, C_y):
    """Bloom / AIR estimator with one-sided non-compliance. T_use is 0/1 for treated participants."""
    T_y = np.asarray(T_y, float)
    T_use = np.asarray(T_use, int)
    C_y = np.asarray(C_y, float)
    pi = float(T_use.mean())
    itt = float(T_y.mean() - C_y.mean())
    mu1c = float(T_y[T_use == 1].mean()) if (T_use == 1).any() else NAN
    mu0n = float(T_y[T_use == 0].mean()) if (T_use == 0).any() else NAN  # non-users' Y = Y(0) under exclusion
    c0 = float(C_y.mean())
    mu0c = (c0 - (1 - pi) * mu0n) / pi if (pi > 0 and (T_use == 0).any()) else (c0 if pi > 0 else NAN)
    return {
        "pi_c": pi,
        "itt_diff": itt,
        "itt_ratio": _ratio(T_y.mean(), c0),
        "cace_diff": itt / pi if pi > 0 else NAN,
        "mu1_compliers": mu1c,
        "mu0_compliers": mu0c,
        "cace_ratio": _ratio(mu1c, mu0c),
        "mu_nonusers_treated": mu0n,
        "control_mean": c0,
        "treated_mean": float(T_y.mean()),
    }


def stratum_cut(T_score, top_share):
    """Count-based cut: the k-th largest score with k = ceil(top_share * n); H = score >= cut, so every participant
    tied at the cut is in H and realised pi_H can exceed top_share. (V24: np.nanquantile decided boundary membership
    by floating-point interpolation; this rule is stated and reproducible.)"""
    s = np.asarray(T_score, float)
    s = s[~np.isnan(s)]
    if len(s) == 0:
        return NAN
    k = max(1, min(len(s), int(math.ceil(top_share * len(s)))))
    return float(np.sort(s)[::-1][k - 1])


def stratum_bounds(T_y, T_score, C_y, top_share):
    """Principal stratum H = top `top_share` of treated by score (non-users must already carry the lowest score),
    cut by `stratum_cut` (ties at the cut included). Returns observed E[Y(1)|H], trimming bounds on E[Y(0)|H], the
    effect set, and the same for the complement L."""
    T_y = np.asarray(T_y, float)
    s = np.asarray(T_score, float)
    C_y = np.asarray(C_y, float)
    cut = stratum_cut(s, top_share)
    H = s >= cut
    piH = float(H.mean())
    out = {
        "cut": cut,
        "pi_H": piH,
        "n_H": int(H.sum()),
        "n_L": int((~H).sum()),
        "tie_rule": "k = ceil(top_share * n) largest; ties at the cut included",
    }
    c0 = float(C_y.mean())
    for name, mask, share in (("H", H, piH), ("L", ~H, 1 - piH)):
        if mask.sum() == 0:
            out[name] = None
            continue
        mu1 = float(T_y[mask].mean())
        lo0, hi0 = trim_bounds(C_y, share)
        out[name] = {
            "mu1": mu1,
            "mu0_lo": lo0,
            "mu0_hi": hi0,
            "effect_lo": mu1 - hi0,
            "effect_hi": mu1 - lo0,
            "ratio_lo": _ratio(mu1, hi0),
            "ratio_hi": _ratio(mu1, lo0),
            "width": hi0 - lo0,
            "naive_minus_all_controls": mu1 - c0,
        }
    return out


def _ridge_fit(Z, h, ridge=1.0):
    A = np.c_[np.ones(len(Z)), Z]
    pen = ridge * np.eye(A.shape[1])
    pen[0, 0] = 0
    return np.linalg.solve(A.T @ A + pen, A.T @ h)


def _auc(score, label):
    score = np.asarray(score, float)
    label = np.asarray(label, bool)
    if label.all() or (~label).all():
        return NAN
    r = pd.Series(score).rank().values
    n1 = label.sum()
    n0 = (~label).sum()
    return float((r[label].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def covariate_tightened_bounds(
    T_y, T_H, T_W, C_y, C_W, n_bins=3, k=2, ridge=1.0, seed=12345, min_control_per_bin=3, fold_reps=1
):
    """Trimming bounds on E[Y(0)|H] within cells of a cross-fitted pre-randomisation predictor of H, aggregated with
    weights P(cell|H). Predictor: ridge linear probability of H on standardised W, fit on treated rows of the other
    fold; bin edges from that fold's treated predictions; fold-f rows of BOTH arms scored with the same beta.
    In population the bounds equal the unconditional ones when the predictor carries no information. In finite
    samples they do NOT: chance variation in P(H|cell) across cells tightens the weighted bound by Jensen's inequality
    (V24 measured 6 to 7% at n_c 39 for a pure-noise covariate, 1% at n_c 301). Compare any reported reduction with
    the permutation null that `run` computes (`permutation_null`). Returns None if W is empty.
    Cells that contain H members but no controls are dropped and the weights renormalised; `cells_without_controls`
    counts them, and when it is positive the bound is for the sub-population of H in cells that have controls.
    `fold_reps` > 1 (V25 fix): the estimator is the MEDIAN over fold_reps random fold assignments of each bound
    (lower and upper separately), the AUC the mean over them. A single fold split is itself a noise draw (V25: on
    HELPMed the one-split reduction ranged -0.4% to 2.8% across splits, median 0.3%); the same estimator must be
    used for the point, the permutation null and the bootstrap, which `run` does. `cells` reports the first split."""
    if T_W is None or T_W.shape[1] == 0:
        return None
    if fold_reps > 1:
        outs = [
            covariate_tightened_bounds(
                T_y, T_H, T_W, C_y, C_W, n_bins, k, ridge, seed + 1000003 * r, min_control_per_bin, 1
            )
            for r in range(fold_reps)
        ]
        ok = [o for o in outs if o and not o.get("skipped")]
        if not ok:
            return outs[0]
        lo0 = float(np.median([o["mu0_lo"] for o in ok]))
        hi0 = float(np.median([o["mu0_hi"] for o in ok]))
        mu1H = float(np.asarray(T_y, float)[np.asarray(T_H, bool)].mean())
        return {
            "mu0_lo": lo0,
            "mu0_hi": hi0,
            "effect_lo": mu1H - hi0,
            "effect_hi": mu1H - lo0,
            "width": hi0 - lo0,
            "ratio_lo": _ratio(mu1H, hi0),
            "ratio_hi": _ratio(mu1H, lo0),
            "predictor_auc_crossfit": float(np.nanmean([o["predictor_auc_crossfit"] for o in ok])),
            "n_bins": n_bins,
            "cells": ok[0]["cells"],
            "cells_with_fewer_than_min_controls": int(
                round(np.mean([o["cells_with_fewer_than_min_controls"] for o in ok]))
            ),
            "cells_without_controls": int(round(np.mean([o["cells_without_controls"] for o in ok]))),
            "share_of_H_excluded_no_controls": float(np.mean([o["share_of_H_excluded_no_controls"] for o in ok])),
            "fold_reps": len(ok),
            "split_widths": [o["width"] for o in ok],
            "split_aucs": [o["predictor_auc_crossfit"] for o in ok],
            "estimator": f"median over {len(ok)} random fold assignments of each bound",
        }
    rng = np.random.default_rng(seed)
    T_y = np.asarray(T_y, float)
    T_H = np.asarray(T_H, bool)
    C_y = np.asarray(C_y, float)
    W = np.vstack([np.asarray(T_W, float), np.asarray(C_W, float)])
    nT, nC = len(T_y), len(C_y)
    col_mean = np.nanmean(W, axis=0)
    W = np.where(np.isnan(W), col_mean, W)
    mu, sd = W.mean(0), W.std(0)
    sd[sd == 0] = 1
    Z = (W - mu) / sd
    fold = np.empty(nT + nC, int)
    idx = rng.permutation(nT + nC)
    fold[idx] = np.arange(nT + nC) % k
    pred = np.full(nT + nC, NAN)
    cell = np.full(nT + nC, -1)
    for f in range(k):
        tr = np.where((fold != f) & (np.arange(nT + nC) < nT))[0]
        if len(tr) < Z.shape[1] + 3:
            return {"skipped": f"fold {f}: only {len(tr)} treated training rows"}
        beta = _ridge_fit(Z[tr], T_H[tr].astype(float), ridge)
        ptr = np.c_[np.ones(len(tr)), Z[tr]] @ beta
        edges = np.quantile(ptr, np.linspace(0, 1, n_bins + 1)[1:-1])
        te = np.where(fold == f)[0]
        p = np.c_[np.ones(len(te)), Z[te]] @ beta
        pred[te] = p
        cell[te] = np.digitize(p, edges)
    cells = []
    lo_sum = hi_sum = 0.0
    wsum = 0.0
    small = 0
    dropped = 0
    nH_dropped = 0
    for b in range(n_bins):
        tb = np.where((cell == b) & (np.arange(nT + nC) < nT))[0]
        cb = np.where((cell == b) & (np.arange(nT + nC) >= nT))[0]
        if len(tb) == 0:
            continue
        piHb = float(T_H[tb].mean())
        nH_b = int(T_H[tb].sum())
        if nH_b == 0:
            cells.append({"cell": b, "n_treated": len(tb), "n_control": len(cb), "pi_H": 0.0, "weight": 0.0})
            continue
        yb = C_y[cb - nT]
        if 0 < len(yb) < min_control_per_bin:
            small += 1
        lo, hi = trim_bounds(yb, piHb) if len(yb) else (NAN, NAN)
        w = nH_b  # P(cell|H) proportional to treated H count in the cell
        cells.append(
            {
                "cell": b,
                "n_treated": len(tb),
                "n_control": len(cb),
                "pi_H": piHb,
                "weight": w,
                "mu0_lo": lo,
                "mu0_hi": hi,
            }
        )
        if lo == lo:
            lo_sum += w * lo
            hi_sum += w * hi
            wsum += w
        else:
            dropped += 1
            nH_dropped += nH_b  # H members whose cell has no controls: excluded from the bound
    if wsum == 0:
        return {"skipped": "no cell with both H members and controls"}
    for c in cells:
        c["weight"] = c["weight"] / wsum if (wsum and c.get("mu0_lo", NAN) == c.get("mu0_lo", NAN)) else 0.0
    lo0, hi0 = lo_sum / wsum, hi_sum / wsum
    mu1H = float(T_y[T_H].mean())
    return {
        "mu0_lo": lo0,
        "mu0_hi": hi0,
        "effect_lo": mu1H - hi0,
        "effect_hi": mu1H - lo0,
        "width": hi0 - lo0,
        "ratio_lo": _ratio(mu1H, hi0),
        "ratio_hi": _ratio(mu1H, lo0),
        "predictor_auc_crossfit": _auc(pred[:nT], T_H),
        "n_bins": n_bins,
        "cells": cells,
        "cells_with_fewer_than_min_controls": small,
        "cells_without_controls": dropped,
        "share_of_H_excluded_no_controls": nH_dropped / max(1, int(T_H.sum())),
    }


# ----------------------------------------------------------------------------- full analysis
def _boot(fn, T, C, B, seed=0):
    """Participants resampled within arm. Failures are counted, not hidden: returns (values, n_failed, first_error)."""
    rng = np.random.default_rng(seed)
    vals = []
    failed = 0
    first_err = None
    for _ in range(B):
        ti = rng.integers(0, len(T), len(T))
        ci = rng.integers(0, len(C), len(C))
        try:
            v = fn(T.iloc[ti], C.iloc[ci])
            if v is not None:
                vals.append(v)
            else:
                failed += 1
        except Exception as ex:
            failed += 1
            first_err = first_err or repr(ex)
    return vals, failed, first_err


def permutation_noise_floor(T_y, T_H, T_W, C_y, C_W, width0, reps=100, seed=0, **kw):
    """Null distribution of the covariate width reduction when W carries no information: W rows are permuted across
    the pooled sample (arms, outcomes and H fixed), the cross-fitted bounds recomputed, and 1 - width/width0 recorded.
    Returns median and 95th percentile of the null reduction, the mean null AUC, and the share of permutations that
    reach the observed reduction when `observed` is passed in kw."""
    observed = kw.pop("observed", NAN)
    rng = np.random.default_rng(seed + 7)
    W = np.vstack([np.asarray(T_W, float), np.asarray(C_W, float)])
    nT = len(T_y)
    reds = []
    aucs = []
    for _ in range(reps):
        Wp = W[rng.permutation(len(W))]
        cv = covariate_tightened_bounds(T_y, T_H, Wp[:nT], C_y, Wp[nT:], seed=int(rng.integers(1e9)), **kw)
        if cv and not cv.get("skipped") and width0 > 0:
            reds.append(1 - cv["width"] / width0)
            aucs.append(cv["predictor_auc_crossfit"])
    if not reds:
        return {"skipped": "no permutation produced a bound", "reps": reps}
    reds = np.array(reds)
    return {
        "reps": int(len(reds)),
        "median_reduction": float(np.median(reds)),
        "p95_reduction": float(np.percentile(reds, 95)),
        "mean_reduction": float(reds.mean()),
        "mean_auc_null": float(np.nanmean(aucs)),
        "share_null_at_or_above_observed": float((reds >= observed - 1e-12).mean()) if observed == observed else NAN,
        "note": "W permuted across participants, everything else fixed; a reduction is evidence of information only if it clears p95 of this null",
    }


def _pct(vals, key, lo=2.5, hi=97.5):
    x = np.array([v[key] for v in vals if v.get(key) == v.get(key) and v.get(key) is not None], float)
    return [float(np.percentile(x, lo)), float(np.percentile(x, hi))] if len(x) > 20 else [NAN, NAN]


def classify(value_lo, value_hi, thr):
    if value_lo != value_lo or value_hi != value_hi:
        return "undefined"
    if value_hi < thr:
        return "below"
    if value_lo >= thr:
        return "at_or_above"
    return "straddles"


def run(
    P,
    score,
    use,
    pre_cols=(),
    top_share=1 / 3,
    thresholds=(),
    B=1000,
    seed=0,
    outcome_range=None,
    exclusion_delta_sd=(-0.5, -0.25, 0.0, 0.25, 0.5),
    intensity=None,
    intensity_name="user turns",
    ceilings=None,
    perm_reps=100,
    fold_reps=30,
    control_model_access="none",
    control_model_exposure=None,
    reseeds=5,
    negligible_reduction=0.05,
):
    """P: participants frame (arm in {llm, control}, outcome, pre-randomisation columns; optional `model_arm`). `use`:
    0/1 per treated participant, indexed like P (control rows ignored). `score`: extraction score per treated
    participant (non-users must carry the minimum). `thresholds`: iterable of (name, scale in {ratio, diff}, value).
    `intensity`: optional per-participant use intensity (e.g. total user turns), indexed like P, for the exposure
    distribution. `ceilings`: optional {name: value on the outcome scale} (model-alone, expert-paired); the third
    section-7 object. `perm_reps`: permutations for the covariate noise floor (0 disables). `fold_reps`: fold
    assignments averaged in the covariate-tightened estimator (same for point, null, bootstrap).
    `control_model_access`: "none" (control arm could not use any model: one-sided non-compliance, CACE is the
    effect of use) or a description such as "usual_sources" (controls could use models outside the platform: the
    ITT is assigned-platform-model versus usual sources, non-compliance is two-sided, and the CACE below is the
    Bloom estimator for platform use only, not the effect of using an LLM against none). `control_model_exposure`:
    optional dict of measured control-arm model exposure (e.g. share reporting LLM influence) printed with it.
    `reseeds`: fresh fold seeds under which the observed tightening is recomputed; `tightening_beyond_noise` is True
    only if the original and every re-seed clear the permutation null's 95th percentile. `negligible_reduction`: a width
    reduction below this share is labelled negligible in `tightening_magnitude` whatever the noise verdict (reporting
    convention, stated in the output)."""
    P = P.copy()
    P["_use"] = use
    P["_score"] = score
    P["_int"] = intensity if intensity is not None else np.nan
    n_nan_outcome = int(P.outcome.isna().sum())
    P = P[P.outcome.notna()].reset_index(drop=True)  # V24b: ITT and bounds on the same rows
    T = P[P.arm == "llm"].reset_index(drop=True)
    C = P[P.arm == "control"].reset_index(drop=True)
    pre_cols = [c for c in pre_cols if c in P.columns and P[c].notna().any()]
    one_sided = (control_model_access or "none") == "none"
    R = {
        "n_treated": int(len(T)),
        "n_control": int(len(C)),
        "top_share": top_share,
        "pre_cols": pre_cols,
        "n_dropped_missing_outcome": n_nan_outcome,
        "control_model_access": control_model_access or "none",
        "control_model_exposure": control_model_exposure,
    }

    def point(Tb, Cb):
        c = one_sided_cace(Tb.outcome, Tb._use, Cb.outcome)
        s = stratum_bounds(Tb.outcome, Tb._score, Cb.outcome, top_share)
        flat = {**c, "pi_H": s["pi_H"]}
        for nm in ("H", "L"):
            if s[nm]:
                for k2, v in s[nm].items():
                    flat[f"{nm}_{k2}"] = v
        if pre_cols:
            cov = covariate_tightened_bounds(
                Tb.outcome,
                Tb._score >= s["cut"],
                Tb[pre_cols].values,
                Cb.outcome,
                Cb[pre_cols].values,
                seed=seed,
                fold_reps=fold_reps,
            )
            if cov and not cov.get("skipped"):
                for k2 in (
                    "mu0_lo",
                    "mu0_hi",
                    "effect_lo",
                    "effect_hi",
                    "width",
                    "ratio_lo",
                    "ratio_hi",
                    "predictor_auc_crossfit",
                ):
                    flat[f"cov_{k2}"] = cov[k2]
                flat["_cov_full"] = cov
        flat["_strata"] = s
        return flat

    pt = point(T, C)
    boots, n_failed, first_err = _boot(point, T, C, B, seed)
    sd_c = float(C.outcome.std(ddof=1)) if len(C) > 1 else NAN
    # exposure (section 7 object 1): use share, use intensity distribution, score distribution, arm composition
    R["exposure"] = {
        "share_nonusers_treated": 1 - pt["pi_c"],
        "n_nonusers_treated": int((T._use == 0).sum()),
        "score_quantiles_treated": {q: float(np.nanquantile(T._score, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
        "score_mean_treated": float(np.nanmean(T._score)),
        "control_has_no_model": one_sided,
        "control_model_access": control_model_access or "none",
        "control_model_exposure": control_model_exposure,
    }
    if T._int.notna().any():
        it = T._int.astype(float)
        R["exposure"]["use_intensity"] = {
            "name": intensity_name,
            "n_with_value": int(it.notna().sum()),
            "n_zero": int((it.fillna(0) == 0).sum()),
            "quantiles_treated": {q: float(np.nanquantile(it, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
            "mean_treated": float(np.nanmean(it)),
            "share_at_least": {k: float((it.fillna(0) >= k).mean()) for k in (1, 3, 5, 10, 20)},
        }
    else:
        R["exposure"]["use_intensity"] = {
            "skipped": "no intensity series supplied; only the binary use share is reported"
        }
    if "model_arm" in T.columns and T.model_arm.notna().any():
        R["exposure"]["treated_arm_composition"] = {str(k): int(v) for k, v in T.model_arm.value_counts().items()}
    # ITT / CACE
    R["itt"] = {
        "diff": pt["itt_diff"],
        "diff_ci95": _pct(boots, "itt_diff"),
        "ratio": pt["itt_ratio"],
        "ratio_ci95": _pct(boots, "itt_ratio"),
        "treated_mean": pt["treated_mean"],
        "control_mean": pt["control_mean"],
        "control_sd": sd_c,
    }
    R["cace"] = {
        "pi_c": pt["pi_c"],
        "diff": pt["cace_diff"],
        "diff_ci95": _pct(boots, "cace_diff"),
        "ratio": pt["cace_ratio"],
        "ratio_ci95": _pct(boots, "cace_ratio"),
        "mu1_compliers": pt["mu1_compliers"],
        "mu0_compliers": pt["mu0_compliers"],
        "mu_nonusers_treated": pt["mu_nonusers_treated"],
        "cace_over_itt": (
            pt["cace_diff"] / pt["itt_diff"]
            if pt["itt_diff"] not in (0, NAN) and pt["itt_diff"] == pt["itt_diff"]
            else NAN
        ),
        "assumptions": [
            "random assignment",
            (
                "one-sided non-compliance (control arm cannot use the model)"
                if one_sided
                else f"NOT one-sided: control arm could use models outside the platform (control_model_access = {control_model_access}); "
                "this CACE is the Bloom estimator for use of the ASSIGNED platform model against the control condition, not the effect of using an LLM against none"
            ),
            "exclusion restriction: assignment without use has no effect on outcome",
            "SUTVA",
        ],
        "estimand_label": (
            "effect of using the model among compliers, against no model"
            if one_sided
            else "effect of using the assigned platform model among platform users, against usual sources (which may include other models)"
        ),
        "mu0_compliers_out_of_range": (
            bool(pt["mu0_compliers"] < outcome_range[0] or pt["mu0_compliers"] > outcome_range[1])
            if outcome_range and pt["mu0_compliers"] == pt["mu0_compliers"]
            else None
        ),
    }
    R["cace"]["exclusion_sensitivity"] = [
        {
            "delta_nonuser_effect_in_control_sd": d,
            "cace_diff": (pt["itt_diff"] - (1 - pt["pi_c"]) * d * sd_c) / pt["pi_c"] if pt["pi_c"] > 0 else NAN,
        }
        for d in exclusion_delta_sd
    ]
    # strata
    s = pt["_strata"]
    R["strata"] = {
        "score_cut": s["cut"],
        "pi_H": s["pi_H"],
        "n_H": s["n_H"],
        "n_L": s["n_L"],
        "tie_rule": s["tie_rule"],
    }
    for nm, label in (("H", "high_extraction"), ("L", "rest")):
        if not s[nm]:
            R["strata"][label] = None
            continue
        d = s[nm]
        R["strata"][label] = {
            "mu1_observed": d["mu1"],
            "mu0_bounds": [d["mu0_lo"], d["mu0_hi"]],
            "effect_set": [d["effect_lo"], d["effect_hi"]],
            "effect_set_outer_ci95": [_pct(boots, f"{nm}_effect_lo")[0], _pct(boots, f"{nm}_effect_hi")[1]],
            "ratio_set": [d["ratio_lo"], d["ratio_hi"]],
            "ratio_set_outer_ci95": [_pct(boots, f"{nm}_ratio_lo")[0], _pct(boots, f"{nm}_ratio_hi")[1]],
            "width": d["width"],
            "width_in_control_sd": d["width"] / sd_c if sd_c == sd_c and sd_c > 0 else NAN,
            "naive_minus_all_controls_BIASED": d["naive_minus_all_controls"],
            "gap_to_itt_set": [d["effect_lo"] - pt["itt_diff"], d["effect_hi"] - pt["itt_diff"]],
        }
    if "_cov_full" in pt:
        cv = pt["_cov_full"]
        R["strata"]["high_extraction_covariate_tightened"] = {
            "mu0_bounds": [cv["mu0_lo"], cv["mu0_hi"]],
            "effect_set": [cv["effect_lo"], cv["effect_hi"]],
            "effect_set_outer_ci95": [_pct(boots, "cov_effect_lo")[0], _pct(boots, "cov_effect_hi")[1]],
            "ratio_set": [cv["ratio_lo"], cv["ratio_hi"]],
            "width": cv["width"],
            "width_reduction_vs_unconditional": 1 - cv["width"] / s["H"]["width"] if s["H"]["width"] > 0 else NAN,
            "predictor_auc_crossfit": cv["predictor_auc_crossfit"],
            "cells": cv["cells"],
            "cells_with_fewer_than_min_controls": cv["cells_with_fewer_than_min_controls"],
            "cells_without_controls": cv.get("cells_without_controls", 0),
            "share_of_H_excluded_no_controls": cv.get("share_of_H_excluded_no_controls", 0.0),
            "estimator": cv.get("estimator", "single fold assignment"),
            "fold_reps": cv.get("fold_reps", 1),
            "note": "bounds within cells of a cross-fitted pre-randomisation predictor of H; collapse to a point as AUC -> 1; compare the reduction with permutation_null",
        }
        ct = R["strata"]["high_extraction_covariate_tightened"]
        if cv.get("split_widths") and s["H"]["width"] > 0:
            sr = 1 - np.array(cv["split_widths"]) / s["H"]["width"]
            ct["width_reduction_across_fold_splits"] = {
                "median": float(np.median(sr)),
                "p5": float(np.percentile(sr, 5)),
                "p95": float(np.percentile(sr, 95)),
                "min": float(sr.min()),
                "max": float(sr.max()),
                "n_splits": int(len(sr)),
                "note": "one-split reductions; the reported reduction uses the median-over-splits bounds",
            }
        if perm_reps and s["H"]["width"] > 0:
            ct["permutation_null"] = permutation_noise_floor(
                T.outcome.values,
                (T._score >= s["cut"]).values,
                T[pre_cols].values,
                C.outcome.values,
                C[pre_cols].values,
                width0=s["H"]["width"],
                reps=perm_reps,
                seed=seed,
                observed=ct["width_reduction_vs_unconditional"],
                fold_reps=fold_reps,
            )
            pn = ct["permutation_null"]
            # V25: a verdict at the edge of the floor can flip with the fold seed; recompute the observed estimator under
            # fresh seeds and require every re-seed to clear the null before calling the tightening real
            re = []
            for r in range(reseeds):
                cvr = covariate_tightened_bounds(
                    T.outcome.values,
                    (T._score >= s["cut"]).values,
                    T[pre_cols].values,
                    C.outcome.values,
                    C[pre_cols].values,
                    seed=seed + 9973 * (r + 1),
                    fold_reps=fold_reps,
                )
                if cvr and not cvr.get("skipped"):
                    re.append(1 - cvr["width"] / s["H"]["width"])
            clears = [x > pn["p95_reduction"] for x in re] if not pn.get("skipped") else []
            ct["reseed_check"] = {
                "reseeds": len(re),
                "reductions": re,
                "n_clearing_null_p95": int(sum(clears)),
                "note": "observed estimator recomputed under fresh fold seeds; the verdict below requires the original and every re-seed to clear the null p95",
            }
            if pn.get("skipped"):
                ct["tightening_beyond_noise"] = None
                ct["tightening_verdict"] = f"not tested ({pn['skipped']})"
            else:
                # V25b (B2): the three cases are exhaustive and the AUC gate has its own label, so a run that clears the
                # floor in every seed with a predictor no better than chance is not reported as a seed-dependent edge case
                orig_clears = ct["width_reduction_vs_unconditional"] > pn["p95_reduction"]
                all_clear = orig_clears and all(clears)
                auc_ok = (ct["predictor_auc_crossfit"] or 0) > 0.5
                ct["tightening_beyond_noise"] = bool(all_clear and auc_ok)
                ct["tightening_verdict"] = (
                    "beyond noise in the original and every re-seed"
                    if ct["tightening_beyond_noise"]
                    else (
                        "clears the noise floor in every seed but the predictor's cross-fit AUC is not above 0.5; treat as not established"
                        if all_clear
                        else (
                            "at the edge of the noise floor: clears it in some seeds and not others; treat as not established"
                            if (orig_clears or any(clears))
                            else "within noise"
                        )
                    )
                )
            # magnitude is a separate verdict from signal (V25b item 4): a narrowing can be real and still irrelevant to the decision
            red = ct["width_reduction_vs_unconditional"]
            csd = R["strata"]["high_extraction"]["width_in_control_sd"]
            ct["tightening_magnitude"] = {
                "reduction": red,
                "absolute_units": red * s["H"]["width"],
                "in_control_sd": (red * csd if csd == csd else None),
                "negligible_below_reduction": negligible_reduction,
                "label": "negligible" if red < negligible_reduction else "material",
                "note": "size of the narrowing, independent of whether it clears the noise floor; the cutoff is a reporting convention, not a test",
            }
            if ct["tightening_beyond_noise"] and red < negligible_reduction:
                ct[
                    "tightening_verdict"
                ] += f", negligible in size ({red * 100:.1f}% of the width, below the {negligible_reduction * 100:.0f}% reporting floor)"
        else:
            ct["permutation_null"] = {"skipped": "perm_reps = 0"}
            ct["tightening_beyond_noise"] = None
            ct["tightening_verdict"] = "not tested (perm_reps = 0)"
    elif pre_cols:
        R["strata"]["high_extraction_covariate_tightened"] = {
            "skipped": "predictor could not be fit (too few treated rows per fold)"
        }
    else:
        R["strata"]["high_extraction_covariate_tightened"] = {"skipped": "no pre-randomisation covariates supplied"}
    # ceilings (section 7 object 3): gap of each treated quantity to a supplied ceiling on the outcome scale
    if ceilings:
        Hd = R["strata"]["high_extraction"]
        cm = R["itt"]["control_mean"]
        R["ceiling"] = {}
        for nm, val in ceilings.items():
            val = float(val)
            denom = val - cm
            R["ceiling"][nm] = {
                "value": val,
                "gap_from_treated_mean": val - R["itt"]["treated_mean"],
                "gap_from_complier_mean": val - R["cace"]["mu1_compliers"],
                "gap_from_H_mean": (val - Hd["mu1_observed"]) if Hd else NAN,
                "gap_from_control_mean": denom,
                "share_of_ceiling_gain_reached_treated": (R["itt"]["treated_mean"] - cm) / denom if denom != 0 else NAN,
                "share_of_ceiling_gain_reached_H": ((Hd["mu1_observed"] - cm) / denom) if (Hd and denom != 0) else NAN,
                "diff_vs_control": denom,
                "ratio_vs_control": _ratio(val, cm),
            }
        R["ceiling"][
            "note"
        ] = "ceiling values supplied by the caller on the trial outcome scale (model-alone or expert-paired arm); share_of_ceiling_gain_reached = (arm mean - control) / (ceiling - control)"
    else:
        R["ceiling"] = {
            "skipped": "no ceiling arm or reference value supplied; section 7's third object is not delivered by this run"
        }
    # thresholds: point quantities, their CIs, the sets, and the outer intervals of the sets
    rows = []
    for name, scale, val in thresholds:
        key = "ratio" if scale == "ratio" else "diff"
        skey = "ratio_set" if scale == "ratio" else "effect_set"
        Hd = R["strata"]["high_extraction"]
        Hset = Hd[skey] if Hd else [NAN, NAN]
        Hout = Hd.get(f"{skey}_outer_ci95", [NAN, NAN]) if Hd else [NAN, NAN]
        row = {
            "threshold": name,
            "scale": scale,
            "value": val,
            "itt": classify(R["itt"][key], R["itt"][key], val),
            "itt_ci": classify(*R["itt"][f"{key}_ci95"], val),
            "cace": classify(R["cace"][key], R["cace"][key], val),
            "cace_ci": classify(*R["cace"][f"{key}_ci95"], val),
            "high_extraction_set": classify(Hset[0], Hset[1], val),
            "high_extraction_set_outer_ci": classify(Hout[0], Hout[1], val),
        }
        ct = R["strata"].get("high_extraction_covariate_tightened") or {}
        if ct.get(skey):
            row["high_extraction_covariate_tightened_set"] = classify(*ct[skey], val)
            if skey == "effect_set":
                row["high_extraction_covariate_tightened_set_outer_ci"] = classify(*ct["effect_set_outer_ci95"], val)
        if ceilings:  # can the ceiling itself clear the threshold against control? if not, no user could
            row["ceilings_vs_control"] = {
                nm: classify(R["ceiling"][nm][f"{key}_vs_control"], R["ceiling"][nm][f"{key}_vs_control"], val)
                for nm in ceilings
            }
        rows.append(row)
    R["threshold_checks"] = rows
    R["not_identified"] = [
        "effect of making every participant extract like stratum H (trained-user estimand): needs a mandated-protocol or trained arm",
        "dose-response of outcome on use or extraction: use is chosen after randomisation, so any slope is correlational",
        "whether stratum H's higher extraction CAUSES its outcome rather than marking prior ability: the trimming bounds allow for any such selection, which is why they are wide",
    ]
    if not ceilings:
        R["not_identified"].append(
            "distance to a ceiling (model-alone or expert-paired on the trial rubric): no ceiling value was supplied"
        )
    if not one_sided:
        R["not_identified"].append(
            f"the effect of model use against NO model: the control arm could use models outside the platform (control_model_access = {control_model_access}"
            + (f"; measured exposure {control_model_exposure}" if control_model_exposure else "")
            + "), so every contrast here is against usual sources"
        )
    R["bootstrap"] = {
        "B": B,
        "kept": len(boots),
        "failed": n_failed,
        "first_error": first_err,
        "note": (
            "participants resampled within arm; set endpoints bootstrapped separately and the outer interval reported. Not an Imbens-Manski CI: "
            "conservative for the parameter inside the set (coverage ~1), NOT a 95% confidence set for the identified set itself "
            "(V24 simulation: set coverage 0.84 at n_control 39, 0.92 to 0.94 at n_control 118 to 400)"
        ),
    }
    return R


def _norm_cdf(x):
    return 0.5 * (1 + np.vectorize(math.erf)(np.asarray(x, float) / math.sqrt(2)))


def simulate_value_of_covariate(
    n_t=120,
    n_c=40,
    top_share=1 / 3,
    rhos=(0.0, 0.3, 0.5, 0.7, 0.9, 1.0),
    reps=200,
    seed=1,
    selection=0.5,
    tau_H=1.0,
    tau_L=0.2,
    n_bins=3,
    control_y0=None,
    fold_reps=1,
):
    """How much does a pre-randomisation covariate of correlation rho with the latent extraction propensity narrow
    the identified set for the high-extraction stratum? Simulated at the trial size given with `selection` =
    correlation between latent propensity and Y(0) (the confounding the bounds guard against). Two modes:
    generic (control_y0 None): Y(0) standard normal, H = strict top `top_share` of the latent; widths in control-SD units.
    calibrated (control_y0 = the trial's control outcomes, V25 fix): Y(0) is drawn from the EMPIRICAL control
    distribution through a Gaussian copula (rank of a normal with correlation `selection` to the latent), so the
    outcome scale, its discreteness and its SD are the trial's; H is the top `top_share` of the latent by the count
    rule. Pass the realised pi_H as top_share to match the trial's stratum. Widths are then on the outcome scale.
    Also records whether the true E[Y(0)|H] falls inside the bounds (should be ~always)."""
    rng = np.random.default_rng(seed)
    out = []
    cal = control_y0 is not None and len(np.asarray(control_y0, float)[~np.isnan(np.asarray(control_y0, float))]) > 1
    if cal:
        pool = np.sort(np.asarray(control_y0, float)[~np.isnan(np.asarray(control_y0, float))])
    for rho in rhos:
        widths0 = []
        widths1 = []
        cover0 = []
        cover1 = []
        aucs = []
        for _ in range(reps):
            n = n_t + n_c
            a = rng.standard_normal(n)
            g = selection * a + math.sqrt(1 - selection**2) * rng.standard_normal(n)
            y0 = pool[np.minimum(len(pool) - 1, (_norm_cdf(g) * len(pool)).astype(int))] if cal else g
            w = rho * a + math.sqrt(max(0.0, 1 - rho**2)) * rng.standard_normal(n)
            cut = stratum_cut(a, top_share)
            H = a >= cut
            y1 = y0 + np.where(H, tau_H, tau_L)
            z = np.zeros(n, bool)
            z[rng.choice(n, n_t, replace=False)] = True
            T_y, C_y = y1[z], y0[~z]
            T_H = H[z]
            true_mu0H = float(y0[H].mean())
            lo, hi = trim_bounds(C_y, T_H.mean())
            widths0.append(hi - lo)
            cover0.append(lo - 1e-9 <= true_mu0H <= hi + 1e-9)
            cv = covariate_tightened_bounds(
                T_y,
                T_H,
                w[z][:, None],
                C_y,
                w[~z][:, None],
                n_bins=n_bins,
                seed=int(rng.integers(1e9)),
                fold_reps=fold_reps,
            )
            if cv and not cv.get("skipped"):
                widths1.append(cv["width"])
                cover1.append(cv["mu0_lo"] - 1e-9 <= true_mu0H <= cv["mu0_hi"] + 1e-9)
                aucs.append(cv["predictor_auc_crossfit"])
        out.append(
            {
                "rho_covariate_vs_latent": rho,
                "mean_width_unconditional": float(np.mean(widths0)),
                "mean_width_covariate": float(np.mean(widths1)) if widths1 else NAN,
                "width_reduction": 1 - float(np.mean(widths1)) / float(np.mean(widths0)) if widths1 else NAN,
                "coverage_unconditional": float(np.mean(cover0)),
                "coverage_covariate": float(np.mean(cover1)) if cover1 else NAN,
                "mean_auc": float(np.nanmean(aucs)) if aucs else NAN,
            }
        )
    return {
        "n_treated": n_t,
        "n_control": n_c,
        "top_share": top_share,
        "selection_corr_y0_latent": selection,
        "tau_H": tau_H,
        "tau_L": tau_L,
        "reps": reps,
        "rows": out,
        "fold_reps": fold_reps,
        "calibration": (
            f"Y(0) drawn from the trial's empirical control outcome distribution (n {len(pool)}, SD {float(pool.std(ddof=1)):.3f}) via a Gaussian copula; "
            f"H = top {top_share:.3f} by the count rule; widths on the outcome scale"
            if cal
            else "GENERIC: Y(0) standard normal, continuous; widths in control-SD units; not calibrated to any trial's outcome scale or pi_H"
        ),
        "note": "coverage = share of replicates whose bounds contain the true E[Y(0)|H]; finite-sample undercoverage is expected in cells with few controls; "
        "tau_H/tau_L add to Y(0) without clipping and affect nothing but the treated mean",
    }


# ----------------------------------------------------------------------------- markdown
def _f(x, nd=3):
    return (
        "n/a"
        if x is None or (isinstance(x, float) and x != x)
        else (f"{x:.{nd}f}" if isinstance(x, (int, float)) else str(x))
    )


def _set(v, nd=3):
    return f"[{_f(v[0], nd)}, {_f(v[1], nd)}]" if v else "n/a"


def _tightening_label(ct):
    """One classification of the covariate-tightening verdict, used by the estimate-table row and the threshold header so they
    cannot disagree with the verdict paragraph. Returns (row suffix, header suffix). Mirrors the five outcomes of
    `tightening_verdict` in run(): beyond noise (material or negligible), at the edge, AUC not above 0.5, within noise, not tested.
    """
    v = ct.get("tightening_verdict") or ""
    bn = ct.get("tightening_beyond_noise")
    mg = ct.get("tightening_magnitude") or {}
    if bn is None:
        why = (ct.get("permutation_null") or {}).get("skipped") or "no permutation null"
        return (
            f" NOT TESTED against a noise floor ({why}), read the unconditional set instead;",
            " (not tested against a noise floor)",
        )
    if bn:
        return (
            (
                " real but NEGLIGIBLE narrowing, the unconditional set is the answer;",
                " (beyond noise but negligible, read the unconditional set)",
            )
            if mg.get("label") == "negligible"
            else ("", "")
        )
    if v.startswith("at the edge"):
        return (
            " AT THE EDGE of the noise floor, not established, read the unconditional set instead;",
            " (at the edge of the noise floor, not established)",
        )
    if v.startswith("clears the noise floor in every seed but"):
        return (
            " clears the noise floor but the predictor AUC is not above 0.5, not established, read the unconditional set instead;",
            " (AUC not above 0.5, not established)",
        )
    return (" NOISE-LEVEL narrowing, read the unconditional set instead;", " (noise-level, not a separate estimate)")


def md_section(R, title="Use-adjusted estimands", score_name="extraction score", use_def="any user message"):
    e, i, c = R["exposure"], R["itt"], R["cace"]
    comp = e.get("treated_arm_composition")
    L = [
        f"## {title}",
        "",
        f"Treated n={R['n_treated']}, control n={R['n_control']}"
        + (
            f" ({R['n_dropped_missing_outcome']} participants with a missing outcome dropped from every quantity)"
            if R.get("n_dropped_missing_outcome")
            else ""
        )
        + (
            f"; the treated arm pools {len(comp)} models ({', '.join(f'{k} {v}' for k, v in comp.items())}), so every treated quantity below is for that mixture"
            if comp and len(comp) > 1
            else ""
        )
        + f". Use = {use_def}; stratum H = top {R['top_share']:.0%} of treated by {score_name}, ties at the cut included, realised share {R['strata']['pi_H']:.1%} "
        f"(non-users carry the minimum score). Use and H are measured after randomisation; neither replaces a pre-specified use indicator. "
        + (
            "Control arm has no model, so non-compliance is one-sided."
            if e.get("control_has_no_model", True)
            else f"**Control arm could use models outside the platform** (control_model_access = {e.get('control_model_access')}"
            + (f"; measured exposure {e.get('control_model_exposure')}" if e.get("control_model_exposure") else "")
            + "): non-compliance is two-sided, every contrast below is assigned-platform-model versus usual sources, and the CACE is the Bloom "
            "estimator for platform use against that control condition, not the effect of using an LLM against none."
        ),
        "",
    ]
    ui = e.get("use_intensity") or {}
    if ui.get("quantiles_treated"):
        q = ui["quantiles_treated"]
        sa = ui["share_at_least"]
        L += [
            f"Use intensity in the treated arm ({ui['name']}, n {ui['n_with_value']}"
            + (
                f", of whom {ui['n_zero']} at 0, which includes any treated participant with no recorded sessions"
                if ui.get("n_zero")
                else ""
            )
            + f"): quantiles 10/25/50/75/90% = {_f(q[0.1], 1)} / {_f(q[0.25], 1)} / {_f(q[0.5], 1)} / {_f(q[0.75], 1)} / {_f(q[0.9], 1)}, mean {_f(ui['mean_treated'], 1)}; "
            f"share with at least 1 / 3 / 5 / 10 / 20: {' / '.join(f'{sa[k]:.0%}' for k in (1, 3, 5, 10, 20))}.",
            "",
        ]
    L += [
        "| quantity | estimate | 95% interval | identified? | assumptions beyond randomisation |",
        "|---|---|---|---|---|",
    ]
    L += [
        f"| share of treated with use = 0 under the stated definition | {_f(e['share_nonusers_treated'])} ({e['n_nonusers_treated']}) | | yes | none |",
        f"| ITT, difference | {_f(i['diff'])} | {_set(i['diff_ci95'])} | yes | none |",
        f"| ITT, ratio of arm means | {_f(i['ratio'])} | {_set(i['ratio_ci95'])} | yes | none |",
        f"| CACE, difference (ITT / {_f(c['pi_c'])}) | {_f(c['diff'])} | {_set(c['diff_ci95'])} | yes | exclusion restriction |",
        f"| CACE, ratio (complier means {_f(c['mu1_compliers'])} / {_f(c['mu0_compliers'])}) | {_f(c['ratio'])} | {_set(c['ratio_ci95'])} | yes | exclusion restriction |",
    ]
    H = R["strata"].get("high_extraction")
    if H:
        L += [
            f"| stratum H effect, difference (set) | {_set(H['effect_set'])} | outer {_set(H['effect_set_outer_ci95'])} | set only | none (sharp trimming bounds) |",
            f"| stratum H effect, ratio (set) | {_set(H['ratio_set'])} | outer {_set(H['ratio_set_outer_ci95'])} | set only | none |",
            f"| stratum H naive: treated-H mean minus all controls | {_f(H['naive_minus_all_controls_BIASED'])} | | **no (E3a, biased)** | |",
        ]
    ct = R["strata"].get("high_extraction_covariate_tightened") or {}
    if ct.get("effect_set"):
        nz = _tightening_label(ct)[0]
        L += [
            f"| stratum H effect with baseline covariates {R['pre_cols']} (set) | {_set(ct['effect_set'])} | outer {_set(ct['effect_set_outer_ci95'])} | set only |{nz} predictor fit on pre-randomisation columns only |"
        ]
    Lr = R["strata"].get("rest")
    if Lr:
        L += [
            f"| complement stratum effect, difference (set) | {_set(Lr['effect_set'])} | outer {_set(Lr['effect_set_outer_ci95'])} | set only | none |"
        ]
    nonuse = (
        f"Treated participants with use = 0 ({e['n_nonusers_treated']}) averaged {_f(c['mu_nonusers_treated'])} against a control mean of {_f(i['control_mean'])} (SD {_f(i['control_sd'])}); "
        f"under the exclusion restriction that difference is selection, not effect. "
        if e["n_nonusers_treated"] > 0
        else f"Every treated participant has use = 1 under the stated definition, so CACE equals ITT (control mean {_f(i['control_mean'])}, SD {_f(i['control_sd'])}). "
    )
    L += [
        "",
        nonuse
        + f"CACE / ITT = {_f(c['cace_over_itt'])}. "
        + (
            "Complier control mean falls outside the stated outcome range, a sign the exclusion restriction or the sample is too thin. "
            if c.get("mu0_compliers_out_of_range")
            else ""
        )
        + "Exclusion sensitivity (effect of mere access on non-users, in control SD): "
        + ", ".join(
            f"{r['delta_nonuser_effect_in_control_sd']:+.2f} -> CACE {_f(r['cace_diff'])}"
            for r in c["exclusion_sensitivity"]
        )
        + ".",
    ]
    if H:
        cf = (
            "no-model counterfactual"
            if e.get("control_has_no_model", True)
            else "counterfactual under the control condition (usual sources, which could include other models)"
        )
        L += [
            "",
            f"Stratum H (pi_H {_f(R['strata']['pi_H'])}, n {R['strata']['n_H']}, cut {_f(R['strata']['score_cut'])}, {R['strata']['tie_rule']}): observed treated mean {_f(H['mu1_observed'])}; its {cf} lies in {_set(H['mu0_bounds'])} "
            f"(width {_f(H['width'])}, {_f(H['width_in_control_sd'], 2)} control SD). Gap between the H effect and ITT: {_set(H['gap_to_itt_set'])}. This is the effect among treated participants "
            f"whose {score_name} put them at or above the cut, whatever produced that score (the user's asking, the model's behaviour, the task drawn). "
            "It is not the effect of training everyone to extract well.",
        ]
    if ct.get("effect_set"):
        pn = ct.get("permutation_null") or {}
        red = ct["width_reduction_vs_unconditional"] * 100
        auc = ct["predictor_auc_crossfit"]
        sp = ct.get("width_reduction_across_fold_splits") or {}
        splits = (
            f" The estimator is the {ct.get('estimator', 'single fold assignment')}; one-split reductions ranged {_f(sp['p5'] * 100, 1)}% to {_f(sp['p95'] * 100, 1)}% (5th to 95th percentile over {sp['n_splits']} splits)."
            if sp
            else " Single fold split: the reduction is itself a noise draw; rerun with fold_reps > 1 before quoting it."
        )
        rs = ct.get("reseed_check") or {}
        rtxt = (
            f" Re-seeded {rs['reseeds']} times, the observed reduction ranged {_f(min(rs['reductions']) * 100, 1)}% to {_f(max(rs['reductions']) * 100, 1)}% and cleared the null in {rs['n_clearing_null_p95']} of {rs['reseeds']}."
            if rs.get("reductions")
            else ""
        )
        if pn.get("p95_reduction") is not None and not pn.get("skipped"):
            base = (
                f"permutation noise floor: null median {_f(pn['median_reduction'] * 100, 1)}%, 95th percentile {_f(pn['p95_reduction'] * 100, 1)}%, "
                f"{int(round(pn['share_null_at_or_above_observed'] * pn['reps']))} of {pn['reps']} permutations reach the observed value, same estimator"
            )
            mg = ct.get("tightening_magnitude") or {}
            if ct.get("tightening_beyond_noise"):
                verdict = (
                    f"This clears the {base}.{rtxt} The covariates carry information about H; whether the narrowing matters is a separate question of its size"
                    + (
                        f", and here it is negligible ({red:.1f}% of the width, below the {mg['negligible_below_reduction'] * 100:.0f}% reporting floor): the unconditional set is the answer."
                        if mg.get("label") == "negligible"
                        else "."
                    )
                )
            elif ct.get("tightening_verdict", "").startswith("clears the noise floor in every seed but"):
                verdict = f"This clears the {base} in every seed, but the predictor's cross-fit AUC is {_f(auc, 3)}, not above 0.5; a bound that narrows without a predictor that discriminates is a cell-count artefact. Not established."
            elif ct.get("tightening_verdict", "").startswith("at the edge"):
                verdict = f"This sits AT THE EDGE of the {base}.{rtxt} Not established: the verdict flips with the fold seed, and the size is what it is."
            else:
                verdict = (
                    f"This does NOT clear the {base}"
                    + (f"; AUC at or below 0.5" if (auc or 0) <= 0.5 else "")
                    + f".{rtxt} "
                    "On this trial these baseline covariates are worth nothing for the stratum-H estimand, and the reported reduction is finite-sample noise."
                )
        else:
            verdict = "No permutation null was computed; do not read the reduction as information without one."
        dw = (H["width"] - ct["width"]) if H else float("nan")
        csd = (H or {}).get("width_in_control_sd")
        dsd = csd * (dw / H["width"]) if H and csd and H["width"] > 0 else None
        L += [
            "",
            f"Baseline covariates {R['pre_cols']} predict H with cross-fitted AUC {_f(auc)} and change the set width by {_f(red, 1)}% "
            f"({_f(H['width'])} to {_f(ct['width'])} on the outcome scale, {_f(dw, 3)} outcome units"
            + (f", {_f(dsd, 2)} control SD" if dsd is not None else "")
            + "; "
            f"{ct['n_bins'] if 'n_bins' in ct else len(ct['cells'])} cells"
            + (
                f", {ct['cells_with_fewer_than_min_controls']} with very few controls"
                if ct.get("cells_with_fewer_than_min_controls")
                else ""
            )
            + (
                f", {ct['cells_without_controls']} cell(s) with H members but no controls dropped, {_f(ct['share_of_H_excluded_no_controls'] * 100, 1)}% of H excluded from the bound"
                if ct.get("cells_without_controls")
                else ""
            )
            + "). "
            + verdict
            + splits
            + " A pre-randomisation test that predicted H better would narrow the set further; the simulation table (when present) says how much for a given correlation.",
        ]
    elif ct.get("skipped"):
        L += ["", f"Covariate tightening skipped: {ct['skipped']}."]
    ce = R.get("ceiling") or {}
    if ce and not ce.get("skipped"):
        for nm, v in ce.items():
            if nm == "note":
                continue
            L += [
                "",
                f"Ceiling '{nm}' = {_f(v['value'])} on the outcome scale: gap from the treated mean {_f(v['gap_from_treated_mean'])}, from the complier mean {_f(v['gap_from_complier_mean'])}, from stratum H {_f(v['gap_from_H_mean'])}; "
                f"the treated arm reached {_f(v['share_of_ceiling_gain_reached_treated'] * 100, 0)}% and stratum H {_f(v['share_of_ceiling_gain_reached_H'] * 100, 0)}% of the control-to-ceiling distance.",
            ]
    else:
        L += [
            "",
            "Ceiling: none supplied. The distance between what users got and what the model (or an expert with the model) could produce on this rubric is not reported by this run.",
        ]
    if R["threshold_checks"]:
        has_ct = any("high_extraction_covariate_tightened_set" in r for r in R["threshold_checks"])
        has_ce = any("ceilings_vs_control" in r for r in R["threshold_checks"])
        ct_head = " covariate-tightened set" + _tightening_label(ct)[1] + " |"
        L += [
            "",
            "| threshold | ITT | ITT 95% CI | CACE | CACE 95% CI | stratum H set | H set outer 95% |"
            + (ct_head if has_ct else "")
            + (" ceiling vs control |" if has_ce else ""),
            "|---|---|---|---|---|---|---|" + ("---|" if has_ct else "") + ("---|" if has_ce else ""),
        ]
        for r in R["threshold_checks"]:
            L += [
                f"| {r['threshold']} ({r['scale']} {r['value']}) | {r['itt']} | {r['itt_ci']} | {r['cace']} | {r['cace_ci']} | {r['high_extraction_set']} | {r['high_extraction_set_outer_ci']} |"
                + (f" {r.get('high_extraction_covariate_tightened_set', 'n/a')} |" if has_ct else "")
                + ((" " + ", ".join(f"{k}: {v}" for k, v in r["ceilings_vs_control"].items()) + " |") if has_ce else "")
            ]
        L += [
            "",
            "Reading for a rule-out decision: 'below' on the stratum H set means the sample's stratum-H quantity cannot reach the threshold under any selection pattern; "
            "the 'outer 95%' column says whether that survives sampling uncertainty; 'straddles' means the trial cannot rule it out and the decision rests on the ITT alone.",
        ]
    L += [
        "",
        "Not identified by this or any post-hoc analysis: " + "; ".join(R["not_identified"]) + ".",
        f"Intervals: {R['bootstrap']['note']} (B={R['bootstrap']['B']}, kept {R['bootstrap']['kept']}"
        + (
            f", failed {R['bootstrap']['failed']}: {R['bootstrap']['first_error']}"
            if R["bootstrap"].get("failed")
            else ""
        )
        + ").",
    ]
    return L

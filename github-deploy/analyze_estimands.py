"""Use-adjusted estimands for a trial directory (trial/SCHEMA.md). Runs after analyze_trial.py (needs results/sessions.json)
or on its own with --use-csv. Usage:
  .venv/bin/python analyze_estimands.py --trial-dir <trial-dir> --score coverage \
      --threshold card_acceptable:ratio:2.8 --threshold card_trigger:ratio:5
Writes <trial-dir>/results/use_adjusted_estimands.{json,md}. Pure arithmetic on existing files; no model calls.

What it adds to the post-trial report (docs/assessment_2026-09-08.md section 7): the per-arm use distribution,
the complier (CACE) estimate, the set-identified effect among treated participants whose extraction score reached
the cut (stratum H: whatever produced the score, the user, the model or the task drawn; the closest identified object
to the quantity a rule-out threshold refers to), how much the trial's pre-randomisation covariates narrow that set
(with a permutation noise floor and a fold-seed-averaged estimator, V24/V25), the gap to a supplied ceiling, and a
threshold table saying whether each quantity is below, above, or straddling the decision value. --control-access
labels two-sided non-compliance when the control arm could use models outside the platform."""

from __future__ import annotations
import argparse, json, pathlib, sys
import numpy as np, pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from est.estimands import run, md_section, simulate_value_of_covariate

SCORES = (
    "coverage",
    "specificity",
    "verification",
    "uptake",
    "persistence",
    "composite",
    "n_user_turns",
    "target_yield",
)


def build_inputs(
    d: pathlib.Path,
    score: str,
    use_min_turns: int,
    use_csv: str | None,
    outcome_col: str = "outcome",
    llm_subset: str | None = None,
):
    P = pd.read_csv(d / "participants.csv")
    if outcome_col != "outcome":  # e.g. a secondary outcome column in participants.csv
        P = P.drop(columns=["outcome"]).rename(columns={outcome_col: "outcome"})
    if llm_subset:  # keep one treated sub-arm (col=value) against all controls
        col, val = llm_subset.split("=", 1)
        P = P[(P.arm == "control") | (P[col].astype(str) == val)].reset_index(drop=True)
    P = P[P.outcome.notna()].reset_index(drop=True)
    if use_csv:
        U = pd.read_csv(use_csv)  # columns: participant_id, use (0/1), score (numeric, treated only)
        P = P.merge(U, on="participant_id", how="left")
        use = np.where(P.arm == "llm", P["use"].fillna(0), np.nan)
        sc = np.where(P.arm == "llm", P["score"].fillna(P["score"].min()), np.nan)
        inten = (
            P["n_user_turns_total"].where(P.arm == "llm") if "n_user_turns_total" in P.columns else None
        )  # intensity if the trial dir carries it
        return (
            P.drop(columns=[c for c in ("use", "score") if c in P]),
            pd.Series(use),
            pd.Series(sc),
            "use.csv",
            "use.csv",
            inten,
        )
    S = pd.read_json(d / "results" / "sessions.json")
    turns = S.groupby("participant_id").n_user_turns.sum()
    per = S.groupby("participant_id")[score].mean() if score != "n_user_turns" else turns
    P = P.merge(turns.rename("_turns"), left_on="participant_id", right_index=True, how="left").merge(
        per.rename("_sc"), left_on="participant_id", right_index=True, how="left"
    )
    llm = P.arm == "llm"
    P["_turns"] = P["_turns"].fillna(0)
    use = np.where(llm, (P._turns >= use_min_turns).astype(float), np.nan)
    floor = float(np.nanmin(P.loc[llm, "_sc"])) if P.loc[llm, "_sc"].notna().any() else 0.0
    sc = np.where(
        llm, np.where(use == 1, P._sc.fillna(floor), min(floor, 0.0)), np.nan
    )  # use = 0 rows carry the minimum score
    inten = P["_turns"].where(llm)
    return (
        P.drop(columns=["_turns", "_sc"]),
        pd.Series(use),
        pd.Series(sc),
        f"total user turns >= {use_min_turns} in results/sessions.json (participants with no session rows count as use = 0)",
        f"per-participant mean session {score}",
        inten,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial-dir", required=True)
    ap.add_argument("--score", default="coverage", choices=SCORES)
    ap.add_argument("--use-min-turns", type=int, default=1)
    ap.add_argument("--top-share", type=float, default=1 / 3)
    ap.add_argument("--threshold", action="append", default=[], help="name:ratio|diff:value (repeatable)")
    ap.add_argument("--outcome-range", nargs=2, type=float, default=None)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument(
        "--use-csv", default=None, help="external per-participant use/score table (participant_id,use,score)"
    )
    ap.add_argument(
        "--simulate-covariate-value", action="store_true", help="append the width-vs-rho simulation at this trial's n"
    )
    ap.add_argument(
        "--outcome-col", default="outcome", help="participants.csv column to treat as the outcome (default outcome)"
    )
    ap.add_argument(
        "--llm-subset",
        default=None,
        help="col=value: keep only this treated sub-arm against all controls (e.g. model_arm=GPT-4o)",
    )
    ap.add_argument("--tag", default="", help="suffix for the output file names")
    ap.add_argument(
        "--ceiling",
        action="append",
        default=[],
        help="name:value on the outcome scale (model-alone or expert-paired arm mean); repeatable",
    )
    ap.add_argument(
        "--perm-reps", type=int, default=100, help="permutations for the covariate noise floor (0 disables)"
    )
    ap.add_argument(
        "--fold-reps",
        type=int,
        default=30,
        help="fold assignments averaged in the covariate-tightened estimator (point, null and bootstrap alike)",
    )
    ap.add_argument(
        "--control-access",
        default="none",
        help="'none' if the control arm could not use any model (one-sided non-compliance); otherwise a short description, e.g. usual_sources",
    )
    ap.add_argument(
        "--control-exposure",
        action="append",
        default=[],
        help="name:value describing measured control-arm model exposure (repeatable), printed with --control-access",
    )
    ap.add_argument(
        "--exclude-pre",
        action="append",
        default=[],
        help="drop pre-randomisation columns whose name starts with this prefix (repeatable)",
    )
    a = ap.parse_args()
    d = pathlib.Path(a.trial_dir)
    out = d / "results"
    out.mkdir(exist_ok=True)
    P, use, sc, use_def, score_name, inten = build_inputs(
        d, a.score, a.use_min_turns, a.use_csv, a.outcome_col, a.llm_subset
    )
    if a.use_csv:
        score_name = f"use table {pathlib.Path(a.use_csv).name} (score column)"
        use_def = f"use table {pathlib.Path(a.use_csv).name} (use column)"
    pre_cols = [
        c
        for c in P.columns
        if (c.startswith("pre_") or c.startswith("selfreport") or (c.startswith("est_") and c != "est_stratum"))
        and P[c].notna().any()
    ]
    if "est_composite" in pre_cols and any(c.startswith("est_") and c != "est_composite" for c in pre_cols):
        pre_cols.remove("est_composite")
    pre_cols = [c for c in pre_cols if not any(c.startswith(x) for x in a.exclude_pre)]
    cexp = {t.split(":")[0]: float(t.split(":")[1]) for t in a.control_exposure} or None
    thr = []
    for t in a.threshold:
        name, scale, val = t.split(":")
        thr.append((name, scale, float(val)))
    ceil = {t.split(":")[0]: float(t.split(":")[1]) for t in a.ceiling}
    R = run(
        P,
        score=sc,
        use=use,
        pre_cols=pre_cols,
        top_share=a.top_share,
        thresholds=thr,
        B=a.boot,
        outcome_range=tuple(a.outcome_range) if a.outcome_range else None,
        intensity=inten,
        intensity_name="total user turns",
        ceilings=ceil or None,
        perm_reps=a.perm_reps,
        fold_reps=a.fold_reps,
        control_model_access=a.control_access,
        control_model_exposure=cexp,
    )
    R["inputs"] = {
        "trial_dir": str(d),
        "score": a.score,
        "use_definition": use_def,
        "score_definition": score_name,
        "pre_cols": pre_cols,
        "outcome_range": a.outcome_range,
        "outcome_col": a.outcome_col,
        "llm_subset": a.llm_subset,
        "use_csv": a.use_csv,
        "ceilings": ceil,
        "perm_reps": a.perm_reps,
        "fold_reps": a.fold_reps,
        "control_access": a.control_access,
        "control_exposure": cexp,
        "exclude_pre": a.exclude_pre,
    }
    nT, nC = R["n_treated"], R["n_control"]
    if a.simulate_covariate_value:
        # calibrated (V25): the trial's own control outcomes and realised pi_H, so the widths are on this outcome scale
        R["simulated_value_of_baseline_covariate"] = simulate_value_of_covariate(
            n_t=nT,
            n_c=nC,
            top_share=R["strata"]["pi_H"],
            reps=200,
            control_y0=P.loc[P.arm == "control", "outcome"].values,
            fold_reps=1,
        )
    stem = "use_adjusted_estimands" + (f"_{a.tag}" if a.tag else "")
    json.dump(R, open(out / f"{stem}.json", "w"), indent=1, default=float)
    L = [
        "# Use-adjusted estimands" + (f" ({a.tag})" if a.tag else ""),
        "",
        f"Trial dir `{d}`. Outcome column `{a.outcome_col}`"
        + (f", treated subset `{a.llm_subset}`" if a.llm_subset else "")
        + f". Score = {score_name}; use = {use_def}. Pre-randomisation covariates used for tightening: {pre_cols or 'none'}.",
        "",
    ]
    L += md_section(R, score_name=score_name, use_def=use_def)
    if (d / "truth.json").exists():
        L += [
            "",
            "Simulated trial (truth.json present): the pre-randomisation `est_*` columns are generated from the same tier that drives the outcome, so any covariate AUC and tightening here is circular by construction and says nothing about a real pre-test.",
        ]
    if a.simulate_covariate_value:
        sim = R["simulated_value_of_baseline_covariate"]
        L += [
            "",
            f"## What a better baseline covariate would buy at this trial's size (simulation, n_treated {nT}, n_control {nC}, stratum share {R['strata']['pi_H']:.3f})",
            "",
            f"Calibration: {sim['calibration']}. Selection correlation between the latent propensity and Y(0): {sim['selection_corr_y0_latent']}. The rho-to-AUC mapping assumes a Gaussian latent; a real pre-test's AUC is the column to read.",
            "",
            "| rho(covariate, latent extraction) | mean cross-fit AUC | set width, no covariate (outcome scale) | set width with covariate | reduction | bounds cover truth |",
            "|---|---|---|---|---|---|",
        ]
        for r in sim["rows"]:
            L += [
                f"| {r['rho_covariate_vs_latent']:.1f} | {r['mean_auc']:.2f} | {r['mean_width_unconditional']:.2f} | {r['mean_width_covariate']:.2f} | {r['width_reduction']*100:.0f}% | {r['coverage_covariate']:.2f} |"
            ]
        L += [
            "",
            f"The rho = 0 row is the finite-sample noise floor for a ONE-split estimator at this n: reductions at or below it are not evidence that a covariate carries information. {sim['note']}.",
        ]
    open(out / f"{stem}.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    print("\nwrote", out / f"{stem}.md")


if __name__ == "__main__":
    main()

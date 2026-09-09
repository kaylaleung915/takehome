"""Post-trial transcript pipeline. Usage: .venv/bin/python analyze_trial.py --trial-dir demo_trial [--no-judge]
Reads participants.csv, transcripts.jsonl, tasks.yaml (trial/SCHEMA.md). Scores every LLM-arm session on the five
EST constructs with the transcript judge, then reports:
  A. in-trial elicitation profile per participant, learning curve over sessions, rank stability (first vs last)
  B. predictive validity of the pre-trial EST (and any self-report) for in-trial elicitation
  C. under-elicitation audit
  D. uplift estimates: E0 unadjusted; E1 pre-stratified on EST (valid); E2 calibrated pre-treatment index
     (weights learned from transcripts, inputs pre-treatment only, cross-fitted; valid); E3 naive post-hoc
     stratification on transcript scores (BIASED — shown for contrast only, never as an estimate)
  E. if truth.json exists (simulated trial): every estimate beside the known truth
  F. if truth.json has controller ground truth per session: transcript-judge vs controller agreement.
  G. (2026-09-08) use-adjusted estimands from est/estimands.py: per-arm use distribution, CACE under one-sided
     non-compliance, set-identified effect among high-extraction participants (trimming bounds), how much the
     pre-randomisation covariates narrow that set, and threshold checks (--threshold name:ratio|diff:value)."""

from __future__ import annotations
import argparse, json, pathlib, sys, math
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, yaml
from scipy import stats
from est.transcripts import judge_session, metrics, session_hash
from est.estimands import run as run_estimands, md_section as estimands_md

SUBS = ["coverage", "specificity", "persistence", "verification", "uptake", "composite"]
B = 2000
RNG = np.random.default_rng(0)
FOLD_RNG = np.random.default_rng(12345)


def boot_ci(fn, df, strat_col="arm"):
    """Nonparametric bootstrap CI, resampling participants within arm."""
    vals = []
    groups = [g for _, g in df.groupby(strat_col)]
    for _ in range(B):
        samp = pd.concat([g.sample(len(g), replace=True, random_state=RNG.integers(1e9)) for g in groups])
        try:
            v = fn(samp)
            if v == v:
                vals.append(v)
        except Exception:
            pass
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))) if vals else (math.nan, math.nan)


def diff_means(df, ycol="outcome"):
    a, c = df[df.arm == "llm"][ycol], df[df.arm == "control"][ycol]
    return float(a.mean() - c.mean()) if len(a) and len(c) else math.nan


def stratified(df, scol):
    """Size-weighted within-stratum difference in means; per-stratum effects."""
    per, w, tot = {}, 0, 0.0
    for s, g in df.groupby(scol):
        d = diff_means(g)
        n = len(g)
        per[str(s)] = {"effect": d, "n": n, "n_llm": int((g.arm == "llm").sum())}
        if d == d:
            tot += d * n
            w += n
    return (tot / w if w else math.nan), per


def tertiles(x, cuts=None):
    x = np.asarray(x, dtype=float)
    cuts = cuts if cuts is not None else np.nanpercentile(x, [100 / 3, 200 / 3])
    st = np.digitize(x, cuts).astype(float)
    st[np.isnan(x)] = np.nan  # NaN -> no stratum (dropped by groupby)
    return st, cuts


def crossfit_index(P, pre_cols, target_col="intrial_composite", k=2, ridge=1.0):
    """Predict in-trial elicitation from PRE-TREATMENT covariates only. Weights (ridge) fit on LLM-arm rows of the
    other fold(s); prediction AND tertile cut points for fold f come from data excluding fold f, so a participant's
    own transcript cannot influence their own stratum. Controls are assigned to folds too and scored by the same beta.
    """
    P = P.copy()
    idx = np.arange(len(P))
    FOLD_RNG.shuffle(idx)
    fold = np.empty(len(P), int)
    fold[idx] = np.arange(len(P)) % k
    P["fold"] = fold
    P["cal_index"] = np.nan
    P["cal_stratum"] = np.nan
    X = P[pre_cols].astype(float)
    X = X.fillna(X.mean())
    mu, sd = X.mean(), X.std().replace(0, 1)
    Z = (X - mu) / sd
    coefs = []
    for f in range(k):
        tr = P[(P.fold != f) & (P.arm == "llm") & P[target_col].notna()]
        if len(tr) < max(6, len(pre_cols) + 2):
            coefs.append({"fold": f, "skipped": True, "n_train": int(len(tr))})
            continue
        A = np.c_[np.ones(len(tr)), Z.loc[tr.index].values]
        pen = ridge * np.eye(A.shape[1])
        pen[0, 0] = 0
        beta = np.linalg.solve(A.T @ A + pen, A.T @ tr[target_col].values)
        cuts = np.percentile(np.c_[np.ones((P.fold != f).sum()), Z.loc[P.fold != f].values] @ beta, [100 / 3, 200 / 3])
        te = P.fold == f
        pred = np.c_[np.ones(te.sum()), Z.loc[te].values] @ beta
        P.loc[te, "cal_index"] = pred
        P.loc[te, "cal_stratum"] = np.digitize(pred, cuts)
        coefs.append(
            {
                "fold": f,
                "n_train": int(len(tr)),
                "cuts": [float(c) for c in cuts],
                **dict(zip(["intercept"] + pre_cols, map(float, beta))),
            }
        )
    return P, coefs


GAP_CATS = ["never_raised", "raised_general_only_not_provided", "raised_specific_not_provided", "provided_not_used"]
MIN_REF_RECORDS = 3  # (B06 2026-09-08, units since V57b) fewer independent ceiling units than this on any task -> CI withheld, gap table flagged "insufficient reference sessions"
# (B14-B3 2026-09-08) ceilings.jsonl provenance (trial/SCHEMA.md, section ceilings.jsonl): two kinds, legacy names mapped; the
# fields a record must carry for the ratio to be comparable across trials; fewer than MIN_REF_RECORDS independent units on a task
# withholds the CI; a kind covering under half the LLM-arm tasks, or mixing protocol_ids, is refused rather than averaged over.
KIND_ALIAS = {"model_alone": "model_alone", "expert_with_model": "expert_with_model", "expert": "expert_with_model"}
CEIL_REQ = [
    "task_id",
    "participant_id",
    "messages",
    "submission",
    "protocol_id",
    "model_id",
    "assistant_condition",
    "aggregation",
]
CEIL_KINDS = ("model_alone", "expert_with_model")
MIN_TASK_COVERAGE = 0.5
TRIAL_META_FILES = {
    "arms.yaml": [
        "assistant_condition",
        "model_id",
        "tools",
        "time_budget_min",
        "model_snapshot",
        "training_text_sha1",
        "training_minutes",
        "prompt_guidance_given",
        "data_handling",
    ],
    "grading.yaml": ["grader_ids", "blinded", "batch_id"],
    "prereg.yaml": [
        "estimands",
        "compliance_definition",
        "analysis_model",
        "thresholds",
        "date_registered",
        "registry",
    ],
}


def normalise_ceiling_record(rec, i):
    """Map legacy `ceiling`/`expert`/`ceiling_model` names onto the schema, and list the required provenance fields the
    record lacks. Unknown kinds stop the run (a typo here would silently create a third ceiling). Returns (rec, problem or None).
    """
    k = rec.get("kind", rec.get("ceiling"))
    if k not in KIND_ALIAS:
        sys.exit(f"ceilings.jsonl record {i}: kind/ceiling must be one of {sorted(KIND_ALIAS)}, got {k!r}")
    rec["ceiling"] = KIND_ALIAS[k]
    if rec.get("model_id") is None and rec.get("ceiling_model") is not None:
        rec["model_id"] = rec["ceiling_model"]
    miss = [f for f in CEIL_REQ if rec.get(f) is None] + (
        ["elicitor_id"] if rec["ceiling"] == "expert_with_model" and not rec.get("elicitor_id") else []
    )
    return rec, (f"record {i} ({rec['ceiling']}, {rec.get('task_id')}): missing {miss}" if miss else None)


def ceiling_unit_id(rec, transcript_hash):
    """The independent unit a ceiling record belongs to (trial/SCHEMA.md, minimum numbers). expert_with_model: the elicitor;
    without elicitor_id there is no unit (None), and elicitation_ratio withholds the CI. model_alone: the seed, else the
    transcript hash, so two byte-identical records are one unit, not two. participant_id is never the unit (it names the
    actor and may repeat across records)."""
    if rec.get("elicitor_id"):
        return str(rec["elicitor_id"])
    if rec["ceiling"] == "expert_with_model":
        return None
    if rec.get("seed") is not None:
        return f"seed:{rec['seed']}"
    return f"rec:{transcript_hash}"


def load_trial_metadata(d):
    """arms.yaml / grading.yaml / prereg.yaml (checklist items 7, 9 to 13 in trial/SCHEMA.md). Each entry is the parsed mapping,
    plus `missing_fields`; an absent file is recorded as such so the report can print NOT COLLECTED instead of nothing.
    """
    meta = {}
    for fn, fields in TRIAL_META_FILES.items():
        p = d / fn
        if not p.exists():
            meta[fn] = {"present": False, "missing_fields": fields}
            continue
        try:
            y = yaml.safe_load(open(p)) or {}
        except Exception as ex:
            meta[fn] = {"present": False, "error": repr(ex), "missing_fields": fields}
            continue
        if not isinstance(y, dict):
            meta[fn] = {"present": False, "error": "top level is not a mapping", "missing_fields": fields}
            continue
        y = _jsonable(
            y
        )  # yaml parses dates and timestamps into objects the JSON writer cannot take; keep them as ISO strings
        meta[fn] = {"present": True, "fields": y, "missing_fields": [f for f in fields if y.get(f) in (None, "", [])]}
    return meta


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if o is None or isinstance(o, (bool, int, float, str)):
        return o
    return o.isoformat() if hasattr(o, "isoformat") else str(o)


def _macro_yield(df):
    """task-macro-averaged target yield (each task weighted equally)"""
    return float(df.groupby("task_id").target_yield.mean().mean()) if len(df) else float("nan")


def elicitation_ratio(S_llm, C, ctype, P_llm, n_boot=1000, seed=11, arm_meta=None, grading_meta=None):
    """Ratio of LLM-arm achievement to one ceiling type on the designer-target yield scale, task-macro-averaged over
    tasks present in both. Percentile CI from a cluster bootstrap over participants; ceiling records are always
    resampled with replacement within task (with <3 records per task this adds little real ceiling uncertainty, and
    the CI inherits any pseudo-replication in the LLM arm; both are flagged in the output).
    Gap decomposition (B06 2026-09-08, replaces the V11 majority/fallback reference set): frequency-weighted reference.
    On task t with n ceiling records whose final answers used target sets U_1..U_n, every designer target k gets weight
    p_k = #{r: k in U_r} / n (the ceiling's reach frequency). Each (session, target) pair is classified as before (reached /
    provided_not_used / raised_specific_not_provided / raised_general_only_not_provided / never_raised) and counted with
    weight p_k; the per-task share of a category is its weighted mass over W_t = sum_k p_k (the expected number of targets
    one ceiling run reaches). Targets a participant used that carry weight < 1 contribute (1 - p_k) to 'beyond_ceiling'.
    This gives an exact accounting identity per task, ratio_t = reached_t + beyond_ceiling_t, and, pooling tasks in the
    same ratio-of-task-means form as the headline ratio (weights = per-task ceiling yield), ratio = reached + beyond_ceiling
    overall. The rule is defined for every n >= 1, has no threshold (so no 50% discontinuity and no empty-set fallback),
    and uses every record: n=1 gives p_k in {0,1} (the single run, unavoidable), n=2 gives {0, 0.5, 1} instead of the
    intersection, n>=3 grades targets by how reliably the ceiling reaches them. Reliability of the reference itself is
    reported separately as the leave-one-out self-agreement of the ceiling (each ceiling run scored on the participant
    'reached' scale against the other n-1 runs; undefined at n=1), and the whole table is flagged
    'insufficient reference sessions' when any task has fewer than MIN_REF_RECORDS independent ceiling units (records that
    repeat a unit, or carry none, do not count).
    Provenance (B14-B3 2026-09-08, trial/SCHEMA.md): refuses (returns {"refused": ...}) when the ceiling covers fewer than half
    of the LLM-arm tasks or mixes protocol_ids; withholds the CI (ratio_ci95 = None, the participant-side interval kept under
    its own name) when any task has fewer than MIN_REF_RECORDS independent units (elicitor_id for the human ceiling, else no unit;
    seed or distinct transcript for the model ceiling; never participant_id); and
    lists `flags` (undocumented protocol, missing assistant_condition, best-of-k aggregation, cross-model, condition or grading
    batch differing from the arm) that the report prints next to the row."""
    Cc = C[C.ceiling == ctype]
    tasks = sorted(set(S_llm.task_id) & set(Cc.task_id))
    if not tasks:
        return None
    n_llm_tasks = int(S_llm.task_id.nunique())
    arm_meta = arm_meta or {}
    grading_meta = grading_meta or {}
    if len(tasks) < MIN_TASK_COVERAGE * n_llm_tasks:
        return {
            "ceiling": ctype,
            "refused": f"ceiling covers {len(tasks)} of {n_llm_tasks} LLM-arm tasks (under {int(MIN_TASK_COVERAGE * 100)}%); ratio not reported",
            "tasks_with_ceiling": tasks,
            "llm_tasks_without_ceiling": sorted(set(S_llm.task_id) - set(tasks)),
        }
    L = S_llm[S_llm.task_id.isin(tasks)]
    Cc = Cc[Cc.task_id.isin(tasks)]
    col = lambda name: Cc[name] if name in Cc.columns else pd.Series([None] * len(Cc), index=Cc.index, dtype=object)
    protocols = sorted(col("protocol_id").dropna().astype(str).unique())
    if len(protocols) > 1:
        return {
            "ceiling": ctype,
            "refused": "mixed protocol_id within one kind; split ceilings.jsonl by protocol and report separately",
            "protocols": protocols,
            "tasks_with_ceiling": tasks,
        }
    flags = []
    if not protocols:
        flags.append(
            "ceiling protocol undocumented (no protocol_id): the ratio is prompt-dependent and not comparable across trials"
        )
    if col("assistant_condition").isna().any():
        flags.append(
            "assistant_condition missing on ceiling records (cannot tell a helpful-only from a safeguarded ceiling)"
        )
    elif (
        arm_meta.get("assistant_condition")
        and (col("assistant_condition").astype(str) != str(arm_meta["assistant_condition"])).any()
    ):
        flags.append(
            f"ceiling assistant_condition differs from the LLM arm's ({arm_meta['assistant_condition']})"
            + ("; R_hum requires the same condition" if ctype == "expert_with_model" else "")
        )
    if col("aggregation").fillna("single").isin(["best_of_k", "pass_at_k", "majority"]).any():
        flags.append(
            "some ceiling records aggregate several samples (best-of-k or majority); the table uses the mean over records, so best-of-k inflates the denominator"
        )
    models = sorted(col("model_id").dropna().astype(str).unique())
    if not models:
        flags.append("model_id missing on ceiling records")
    elif arm_meta.get("model_id") and set(models) != {str(arm_meta["model_id"])}:
        flags.append(
            f"cross-model: ceiling {models} vs LLM arm {arm_meta['model_id']}; the ratio mixes participants' under-elicitation with the capability difference"
        )
    if grading_meta.get("batch_id") and (col("grading_batch_id").astype(object) != grading_meta["batch_id"]).any():
        flags.append(
            f"ceiling grading_batch_id differs from the participants' batch ({grading_meta['batch_id']}); rubric-scale ratio not comparable"
        )
    unit = col("unit_id")  # set by main() via ceiling_unit_id; a frame without it has no units and the CI is withheld
    n_unit_missing = int(unit.isna().sum())  # expert_with_model records without elicitor_id carry no unit (V57b-1)
    _with_unit = Cc.assign(_u=unit.values).dropna(subset=["_u"])
    units_per_task = _with_unit.groupby("task_id")._u.nunique().reindex(tasks, fill_value=0)
    units_repeated = (
        bool((_with_unit.groupby("task_id")._u.size() > _with_unit.groupby("task_id")._u.nunique()).any())
        if len(_with_unit)
        else False
    )  # some record shares a unit with another on the same task
    ci_ok = bool((units_per_task >= MIN_REF_RECORDS).all()) and n_unit_missing == 0
    ci_reason = (
        None
        if ci_ok
        else (
            f"elicitor_id missing on {n_unit_missing} {ctype} record(s): the R_hum resampling unit is the elicitor (trial/SCHEMA.md, minimum numbers), "
            "so independence of the ceiling runs cannot be established and no 95% CI is reported for the ratio"
            if n_unit_missing
            else f"fewer than {MIN_REF_RECORDS} independent ceiling units (seed / elicitor_id / distinct transcript) on some task: "
            "the ceiling side of the interval is unmeasured, so no 95% CI is reported for the ratio (trial/SCHEMA.md, minimum numbers)"
        )
    )
    ly, cy = _macro_yield(L), _macro_yield(Cc)
    rng = np.random.default_rng(seed)
    pids = L.participant_id.unique()
    boots = []
    dropped = 0
    for _ in range(n_boot):
        bp = rng.choice(pids, len(pids), replace=True)
        Lb = pd.concat([L[L.participant_id == q] for q in bp])
        Cb = pd.concat(
            [g.sample(len(g), replace=True, random_state=int(rng.integers(1e9))) for _, g in Cc.groupby("task_id")]
        )
        cyb = _macro_yield(Cb)
        if cyb > 0 and len(set(Lb.task_id) & set(tasks)) == len(tasks):
            boots.append(_macro_yield(Lb[Lb.task_id.isin(tasks)]) / cyb)
        else:
            dropped += 1
    recs_per_task = Cc.groupby("task_id").size()
    # circularity check (V11): ceiling transcripts that are hash-identical to LLM-arm sessions share the same cached judge call
    overlap = (
        int(Cc.transcript_hash.isin(set(L.transcript_hash)).sum())
        if "transcript_hash" in Cc and "transcript_hash" in L
        else None
    )
    overlap_arm = int(L.transcript_hash.isin(set(Cc.transcript_hash)).sum()) if overlap is not None else None
    # gap decomposition (B06 2026-09-08): frequency-weighted reference, see docstring
    CATS_ALL = ["reached"] + GAP_CATS + ["beyond_ceiling"]
    per_task = {}
    pooled_num = {k: 0.0 for k in CATS_ALL}
    pooled_den = 0.0
    loo_num = loo_den = 0.0
    sess_nonanswer_noretry = 0
    empty_ceiling_tasks = []
    ident_err = 0.0
    r3 = lambda x: (None if x is None or x != x else round(float(x), 4))
    for t in tasks:
        ct = Cc[Cc.task_id == t]
        n = len(ct)
        Lt = L[L.task_id == t]
        ns = len(Lt)
        cnt = pd.Series([x for ids in ct.used_ids for x in ids]).value_counts() if n else pd.Series(dtype=int)
        p = {k: v / n for k, v in cnt.items()}  # ceiling reach frequency per target
        W = float(sum(p.values()))  # expected targets per ceiling run (= n_targets * ceiling yield)
        cy_t = float(ct.target_yield.mean()) if n else float("nan")
        ly_t = float(Lt.target_yield.mean()) if ns else float("nan")
        mass = {k: 0.0 for k in CATS_ALL}
        for _, s in Lt.iterrows():
            used = set(s.used_ids)
            for k, pk in p.items():
                if k in used:
                    mass["reached"] += pk
                elif k in s.provided_ids:
                    mass["provided_not_used"] += pk
                elif k in s.specific_ids:
                    mass["raised_specific_not_provided"] += pk
                elif k in s.asked_ids:
                    mass["raised_general_only_not_provided"] += pk
                else:
                    mass["never_raised"] += pk
            mass["beyond_ceiling"] += sum(
                1.0 - p.get(k, 0.0) for k in used
            )  # participant reached what the ceiling did not (fully) reach
        share = {k: (mass[k] / (ns * W) if ns and W > 0 else float("nan")) for k in CATS_ALL}
        ratio_t = (ly_t / cy_t) if (ns and cy_t == cy_t and cy_t > 0) else float("nan")
        e_t = (
            abs((share["reached"] + share["beyond_ceiling"]) - ratio_t)
            if ratio_t == ratio_t and share["reached"] == share["reached"]
            else float("nan")
        )
        if e_t == e_t:
            ident_err = max(ident_err, e_t)
        if W == 0:
            empty_ceiling_tasks.append(t)
        # leave-one-out self-agreement of the ceiling on the participant 'reached' scale (n >= 2 only)
        loo = []
        if n >= 2:
            for ids in ct.used_ids:
                U = set(ids)
                pm = {k: (cnt[k] - (k in U)) / (n - 1) for k in cnt.index}
                Wm = sum(pm.values())
                if Wm > 0:
                    loo.append(sum(pm[k] for k in U if k in pm) / Wm)
        loo_t = float(np.mean(loo)) if loo else float("nan")
        unanimous = (sum(1.0 for k, pk in p.items() if pk == 1.0) / W) if W > 0 else float("nan")
        per_task[t] = {
            "n_ceiling_records": int(n),
            "n_sessions": int(ns),
            "reference_weights": {k: r3(v) for k, v in sorted(p.items())},
            "expected_targets_per_ceiling_run": r3(W),
            "unanimous_weight_share": r3(unanimous),
            **{k: r3(share[k]) for k in CATS_ALL},
            "per_task_ratio": r3(ratio_t),
            "identity_abs_error": r3(e_t),
            "ceiling_loo_self_agreement": r3(loo_t),
        }
        # pool over tasks in the same ratio-of-task-means form as the headline ratio: weight each task's shares by its ceiling yield
        if ns and cy_t == cy_t:
            for k in CATS_ALL:
                if share[k] == share[k]:
                    pooled_num[k] += cy_t * share[k]
            if W == 0 and ly_t == ly_t:
                pooled_num["beyond_ceiling"] += ly_t  # ceiling reached nothing: all arm yield is beyond-ceiling
            pooled_den += cy_t
            if loo_t == loo_t:
                loo_num += cy_t * loo_t
                loo_den += cy_t
    for _, s in L.iterrows():
        if s.n_nonanswers > 0 and s.n_retries == 0:
            sess_nonanswer_noretry += 1
    PT = pd.DataFrame(per_task).T
    pooled = {k: (round(pooled_num[k] / pooled_den, 3) if pooled_den > 0 else None) for k in CATS_ALL}
    PTv = PT[PT.expected_targets_per_ceiling_run.astype(float) > 0]
    macro_eq = {k: round(float(PTv[k].astype(float).mean()), 3) for k in CATS_ALL} if len(PTv) else None
    macro = {k: pooled[k] for k in GAP_CATS} if pooled_den > 0 else None
    min_recs = int(recs_per_task.min()) if len(recs_per_task) else 0
    # (V57b fix round) adequacy is judged on independent units, not records: three copies of one transcript, or three records
    #   from one unidentified elicitor, are one run of the reference, so their self-agreement says nothing about reliability
    min_units = int(units_per_task.min()) if len(units_per_task) else 0
    adequate = bool(min_units >= MIN_REF_RECORDS)
    ref_adequacy = {
        "min_ceiling_records_per_task": min_recs,
        "min_independent_units_per_task": min_units,
        "required": MIN_REF_RECORDS,
        "adequate": adequate,
        "note": (
            None
            if adequate
            else f"insufficient reference sessions: {min_units} independent ceiling unit(s) on some task (< {MIN_REF_RECORDS}; {min_recs} record(s)); the decomposition is against the available run(s), "
            "reference weights are 0/1 (n=1) or 0/0.5/1 (n=2), and how reliably the ceiling reaches each target is unmeasured"
            + (
                " (ceiling_loo_self_agreement is inflated when records repeat a unit)"
                if units_repeated
                else (
                    f" ({n_unit_missing} record(s) carry no unit and do not count; see ceiling_loo_self_agreement)"
                    if n_unit_missing
                    else " (see ceiling_loo_self_agreement)"
                )
            )
        ),
    }
    single_turn_ceiling = bool((Cc.n_user_turns <= 1).all()) if "n_user_turns" in Cc else False
    out = {
        "ceiling": ctype,
        "tasks": tasks,
        "n_llm_sessions": int(len(L)),
        "n_llm_participants": int(len(pids)),
        "n_ceiling_records": int(len(Cc)),
        "ceiling_records_per_task": {t: int(v) for t, v in recs_per_task.items()},
        "llm_arm_yield": round(ly, 3),
        "ceiling_yield": round(cy, 3),
        "ratio": round(ly / cy, 3) if cy > 0 else None,
        "ratio_ci95": (
            [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)]
            if (boots and ci_ok)
            else None
        ),
        "ci_withheld": (not ci_ok),
        "ci_withheld_reason": ci_reason,
        "ratio_ci95_participants_only_ceiling_fixed": (
            [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)]
            if (boots and not ci_ok)
            else None
        ),
        "independent_units_per_task": {t: int(v) for t, v in units_per_task.items()},
        "records_without_unit": n_unit_missing,
        "flags": flags,
        "protocol_id": (protocols[0] if protocols else None),
        "ceiling_model_ids": models,
        "bootstrap": {
            "n_boot": n_boot,
            "kept": len(boots),
            "dropped": dropped,
            "ci_caveats": (
                ["ceiling has <3 records for some task: ceiling-side uncertainty is essentially unmeasured"]
                if (recs_per_task < 3).any()
                else []
            )
            + [
                "participants are the resampling unit; if transcripts are duplicated across participants (see pseudo_replication_warning) the interval is too narrow"
            ],
        },
        "ceiling_verification_rate": (None if single_turn_ceiling else round(float(Cc.verification.mean()), 3)),
        "ceiling_verification_note": (
            "n/a: single-turn ceiling (task prompt only), verification is structurally impossible"
            if single_turn_ceiling
            else None
        ),
        "llm_arm_verification_rate": round(float(L.verification.mean()), 3),
        "gap_reference_rule": (
            "frequency-weighted: each designer target weighted by the share of the task's ceiling records whose answer used it; "
            "category shares = weighted mass / expected targets per ceiling run; tasks pooled with ceiling-yield weights "
            "(same ratio-of-task-means form as the headline ratio), so reached + beyond_ceiling = ratio"
        ),
        "gap_weighting": "ceiling-yield-weighted over tasks (pooled); equal-task macro also given in gap_decomposition_task_macro_equal_weight",
        "reference_adequacy": ref_adequacy,
        "gap_reference_per_task": per_task,
        "gap_decomposition_share_of_ceiling_targets": macro,
        "reached_share_of_ceiling_targets": pooled["reached"],
        "beyond_ceiling_share": pooled["beyond_ceiling"],
        "gap_identity_max_abs_error": round(ident_err, 6),
        "gap_decomposition_task_macro_equal_weight": macro_eq,
        "ceiling_loo_self_agreement": (round(loo_num / loo_den, 3) if loo_den > 0 else None),
        "ceiling_loo_self_agreement_note": (
            "each ceiling run scored on the participant 'reached' scale against the other runs of the same task; "
            "read participants' reached against this, not against 1.0; undefined with one record per task"
        ),
        "llm_sessions_with_nonanswer_never_retried": round(sess_nonanswer_noretry / len(L), 3),
        "circular": bool(Cc.circular.any()) if "circular" in Cc else False,
        "ceiling_records_hash_identical_to_llm_sessions": overlap,
        "llm_sessions_hash_identical_to_ceiling_records": overlap_arm,
        "gap_tasks_with_empty_ceiling": empty_ceiling_tasks,
        "scale_note": "Scale: designer-target yield (share of task targets reflected in the final answer), not the trial's own outcome rubric",
    }
    if "outcome" in Cc.columns and Cc.outcome.notna().all() and P_llm is not None and P_llm.outcome.notna().all():
        out["outcome_scale"] = {
            "llm_arm_mean_outcome": round(float(P_llm.outcome.mean()), 3),
            "ceiling_mean_outcome": round(float(Cc.outcome.mean()), 3),
            "ratio": round(float(P_llm.outcome.mean() / Cc.outcome.mean()), 3) if Cc.outcome.mean() > 0 else None,
            "note": "trial-rubric scale; requires ceiling submissions graded on the same rubric as participants",
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial-dir", required=True)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument(
        "--threshold",
        action="append",
        default=[],
        help="section G decision threshold, name:ratio|diff:value (repeatable)",
    )
    ap.add_argument(
        "--estimand-score",
        default="coverage",
        help="section G extraction score (a sessions.json column; default coverage)",
    )
    ap.add_argument(
        "--ceiling",
        action="append",
        default=[],
        help="section G ceiling on the outcome scale, name:value (repeatable; e.g. model_alone:0.95)",
    )
    ap.add_argument(
        "--fold-reps",
        type=int,
        default=30,
        help="section G: fold assignments averaged in the covariate-tightened estimator (V25)",
    )
    ap.add_argument(
        "--control-access",
        default="none",
        help="section G: 'none' if the control arm could not use any model; otherwise a short description (two-sided non-compliance labels)",
    )
    ap.add_argument(
        "--control-exposure",
        action="append",
        default=[],
        help="section G: name:value, measured control-arm model exposure (repeatable)",
    )
    a = ap.parse_args()
    d = pathlib.Path(a.trial_dir)
    out = d / "results"
    out.mkdir(exist_ok=True)
    P = pd.read_csv(d / "participants.csv")
    T = [json.loads(l) for l in open(d / "transcripts.jsonl")]
    tasks = yaml.safe_load(open(d / "tasks.yaml")) if (d / "tasks.yaml").exists() else {}
    truth = json.load(open(d / "truth.json")) if (d / "truth.json").exists() else None
    bad = [
        c
        for c in P.columns
        if c not in ("participant_id", "arm", "outcome")
        and not (c.startswith("est_") or c.startswith("pre_") or c.startswith("selfreport"))
    ]
    if bad:
        print("WARNING: unrecognised participant columns (must be pre-randomisation):", bad)
    # (2026-09-08, RHE real-trial run) a real trial may have no pre-trial EST: est_composite absent or all-NaN -> skip E1
    # and the EST predictive-validity row with an explicit note; everything else runs unchanged.
    has_est = "est_composite" in P.columns and P.est_composite.notna().any()
    NO_EST = "no pre-test available: participants.csv has no est_composite (or all NaN), so E1 and EST predictive validity are not computed"
    if not has_est:
        print("NOTE:", NO_EST)

    # ---- judge sessions
    # judge each UNIQUE (task, transcript, submission) once, then fan out — identical transcripts get identical scores
    uniq = {}
    for rec in T:
        uniq.setdefault(session_hash(rec, tasks.get(rec["task_id"])), rec)
    if (
        a.no_judge
        and (out / "sessions.json").exists()
        and "transcript_hash" in pd.read_json(out / "sessions.json").columns
    ):
        S = pd.read_json(out / "sessions.json")
    else:
        with ThreadPoolExecutor(a.workers) as ex:
            judged = dict(
                zip(
                    uniq.keys(),
                    ex.map(
                        lambda h: judge_session(uniq[h], tasks.get(uniq[h]["task_id"]), d / "judge_cache"),
                        list(uniq.keys()),
                    ),
                )
            )
        rows = []
        for rec in T:
            task = tasks.get(rec["task_id"])
            h = session_hash(rec, task)
            m = metrics(judged[h], list(((task or {}).get("targets") or {}).keys()) or None)
            rows.append(
                {
                    "participant_id": rec["participant_id"],
                    "session_idx": rec["session_idx"],
                    "task_id": rec["task_id"],
                    "targets_given": bool((task or {}).get("targets")),
                    "transcript_hash": h,
                    **m,
                }
            )
        S = pd.DataFrame(rows)
        S.to_json(out / "sessions.json", orient="records", indent=1)
    R = {}
    R["n_unique_transcripts"] = int(len(uniq))
    R.update(
        {
            "n_participants": int(len(P)),
            "n_llm": int((P.arm == "llm").sum()),
            "n_sessions": int(len(S)),
            "tasks_without_designer_targets": sorted(S[~S.targets_given].task_id.unique().tolist()),
            "composite_definition": "mean of 5 subscales with undefined persistence/uptake scored 0 (fixed denominator)",
            "sessions_by_n_defined": {
                int(k): int(v) for k, v in S.composite_n_defined.value_counts().sort_index().items()
            },
            "judge_invented_target_ids": int(S.judge_invented_ids.apply(len).gt(0).sum()),
        }
    )
    if R["n_unique_transcripts"] < len(S):
        R["pseudo_replication_warning"] = (
            f"{len(S)} sessions but only {R['n_unique_transcripts']} unique transcripts: participant-level n overstates information; all LLM-arm CIs too narrow"
        )

    # ---- A. profiles, learning curve, rank stability
    prof = S.groupby("participant_id")[SUBS].mean().add_prefix("intrial_")
    S2 = S[
        S.groupby("participant_id").session_idx.transform("nunique") >= 2
    ]  # first-vs-last needs >=2 sessions (1 session: first==last)
    first = S2.sort_values("session_idx").groupby("participant_id").first()["composite"].rename("intrial_first")
    last = S2.sort_values("session_idx").groupby("participant_id").last()["composite"].rename("intrial_last")
    P = (
        P.merge(prof, left_on="participant_id", right_index=True, how="left")
        .merge(first, left_on="participant_id", right_index=True, how="left")
        .merge(last, left_on="participant_id", right_index=True, how="left")
    )
    curve = S.groupby("session_idx")["composite"].agg(["mean", "sem", "count"]).reset_index()
    R["learning_curve"] = curve.round(4).to_dict("records")
    L = P[P.arm == "llm"]
    rs = stats.spearmanr(L.intrial_first, L.intrial_last, nan_policy="omit")
    Lfl = L[
        L.intrial_first.notna() & L.intrial_last.notna()
    ]  # CI on the same rows as the point estimate (LLM rows without >=2 judged sessions are NaN)
    R["rank_stability_first_vs_last"] = {
        "spearman": round(float(rs.statistic), 3),
        "p": round(float(rs.pvalue), 4),
        "n": int(L.intrial_first.notna().sum()),
        "ci95": boot_ci(lambda df: stats.spearmanr(df.intrial_first, df.intrial_last).statistic, Lfl),
    }
    R["gain_first_to_last"] = {
        "mean": round(float((L.intrial_last - L.intrial_first).mean()), 3),
        "sd": round(float((L.intrial_last - L.intrial_first).std()), 3),
    }

    # ---- B. predictive validity of pre-trial measures for in-trial elicitation
    pv = {}
    if not has_est:
        R["predictive_validity_note"] = NO_EST + "; only self-report rows (if any) are shown"
    for col in [c for c in P.columns if (c == "est_composite" and has_est) or c.startswith("selfreport")]:
        x, y = L[col].astype(float), L.intrial_composite
        ok = x.notna() & y.notna()
        if ok.sum() < 3:
            continue
        pr = stats.pearsonr(x[ok], y[ok])
        sp = stats.spearmanr(x[ok], y[ok])
        pv[col] = {
            "pearson_r": round(float(pr.statistic), 3),
            "r2": round(float(pr.statistic**2), 3),
            "spearman": round(float(sp.statistic), 3),
            "n": int(ok.sum()),
            "r_ci95": boot_ci(
                lambda df, c=col: stats.pearsonr(df[c].astype(float), df.intrial_composite).statistic, L[ok]
            ),
        }
    R["predictive_validity_vs_intrial_composite"] = pv

    # ---- C. under-elicitation audit (LLM arm sessions)
    R["under_elicitation_audit"] = {
        "sessions_coverage_below_half": round(float((S.coverage < 0.5).mean()), 3),
        "sessions_no_specific_request": round(float((S.specificity == 0).mean()), 3),
        "sessions_nonanswer_never_retried": round(float(((S.n_nonanswers > 0) & (S.n_retries == 0)).mean()), 3),
        "sessions_no_verification": round(float((S.verification == 0).mean()), 3),
        "sessions_uptake_below_half_of_defined": (
            round(float((S.uptake[S.uptake.notna()] < 0.5).mean()), 3) if S.uptake.notna().any() else None
        ),
        "sessions_persistence_undefined_no_nonanswer_met": round(float(S.persistence.isna().mean()), 3),
        "sessions_uptake_undefined_nothing_provided": round(float(S.uptake.isna().mean()), 3),
        "participants_all_sessions_coverage_below_half": round(
            float(S.groupby("participant_id").coverage.max().lt(0.5).mean()), 3
        ),
    }

    # ---- E. elicitation ratio against BOTH ceilings (owner decision 2026-09-07: model-alone = capability ceiling,
    #         expert+model = human ceiling; they answer different questions and are reported side by side, never max())
    # (B14-B3 2026-09-08) trial-level metadata (arms.yaml, grading.yaml, prereg.yaml; checklist items 7, 9 to 13) is read first so
    # the ceiling rows can be checked against the arm's condition, model and grading batch; absent files are reported, not skipped.
    R["trial_metadata"] = load_trial_metadata(d)
    arm_meta = R["trial_metadata"]["arms.yaml"].get("fields") or {}
    grading_meta = R["trial_metadata"]["grading.yaml"].get("fields") or {}
    if (d / "ceilings.jsonl").exists():
        Craw = [json.loads(l) for l in open(d / "ceilings.jsonl") if l.strip()]
        ceil_problems, fatal = [], []
        for i, rec in enumerate(Craw):
            rec, prob = normalise_ceiling_record(rec, i)
            if prob:
                ceil_problems.append(prob)
            if rec.get("task_id") is None or rec.get("participant_id") is None:
                fatal.append(prob)
        R["ceilings_schema_problems"] = ceil_problems
        # (V57b-7) a record with no task_id or participant_id cannot be scored or attributed; stop with the validator's text
        #   rather than a bare KeyError further down
        if fatal:
            sys.exit(
                f"ceilings.jsonl: {len(fatal)} record(s) lack task_id or participant_id and cannot be scored; first: {fatal[0]}"
            )
        cu = {}
        for rec in Craw:
            cu.setdefault(session_hash(rec, tasks.get(rec["task_id"])), rec)
        with ThreadPoolExecutor(a.workers) as ex:
            cj = dict(
                zip(
                    cu.keys(),
                    ex.map(
                        lambda h: judge_session(cu[h], tasks.get(cu[h]["task_id"]), d / "judge_cache"), list(cu.keys())
                    ),
                )
            )
        crows = []
        for rec in Craw:
            task = tasks.get(rec["task_id"])
            h = session_hash(rec, task)
            m = metrics(cj[h], list(((task or {}).get("targets") or {}).keys()) or None)
            crows.append(
                {
                    "participant_id": rec["participant_id"],
                    "ceiling": rec["ceiling"],
                    "circular": bool(rec.get("circular", False)),
                    "task_id": rec["task_id"],
                    "outcome": rec.get("outcome"),
                    "transcript_hash": h,
                    "protocol_id": rec.get("protocol_id"),
                    "prompt_template_sha1": rec.get("prompt_template_sha1"),
                    "model_id": rec.get("model_id"),
                    "assistant_condition": rec.get("assistant_condition"),
                    "aggregation": rec.get("aggregation"),
                    "n_samples": rec.get("n_samples"),
                    "grader": rec.get("grader"),
                    "grading_batch_id": rec.get("grading_batch_id"),
                    "graded_blind": rec.get("graded_blind"),
                    "run_at": rec.get("run_at"),
                    # the resampling unit for the ceiling side (trial/SCHEMA.md minimum numbers): the elicitor for the human
                    # ceiling (no elicitor_id -> no unit, the CI is withheld; V57b-1), the seed for the model, else the transcript
                    # itself, so byte-identical duplicate records collapse to one unit rather than counting as independent runs
                    "unit_id": ceiling_unit_id(rec, h),
                    **m,
                }
            )
        C = pd.DataFrame(crows)
        C.to_json(out / "ceilings_scored.json", orient="records", indent=1)
        S_llm = S[S.participant_id.isin(P[P.arm == "llm"].participant_id)]
        R["elicitation_ratio"] = {
            ct: elicitation_ratio(S_llm, C, ct, P[P.arm == "llm"], arm_meta=arm_meta, grading_meta=grading_meta)
            for ct in sorted(C.ceiling.unique())
        }
        R["elicitation_ratio_absent_kinds"] = [k for k in CEIL_KINDS if k not in R["elicitation_ratio"]]
        R["elicitation_ratio_note"] = (
            "Two ceilings, two questions. model_alone: how much of what the model can produce with nothing withheld reached "
            "participants' answers (capability ceiling, R_cap). expert_with_model: how much of what a skilled human elicitor gets out of the "
            "same gated assistant the participants got (human ceiling, R_hum). A trial should run and report both; a missing kind is printed as NOT COMPUTABLE."
        )
    else:
        R["elicitation_ratio"] = None
        R["elicitation_ratio_absent_reason"] = "no ceilings.jsonl in the trial directory"
        R["elicitation_ratio_absent_kinds"] = list(CEIL_KINDS)

    # ---- D. estimates
    E = {}
    E["E0_unadjusted"] = {"ate": diff_means(P), "ci95": boot_ci(diff_means, P), "valid": True}
    if has_est:
        P["est_stratum"], cuts = tertiles(P.est_composite.values)
        ate1, per1 = stratified(P, "est_stratum")
        E["E1_prestratified_EST_tertiles"] = {
            "ate": ate1,
            "ci95": boot_ci(
                lambda df: stratified(df.assign(est_stratum=tertiles(df.est_composite.values, cuts)[0]), "est_stratum")[
                    0
                ],
                P,
            ),
            "per_stratum": per1,
            "cuts": [float(c) for c in cuts],
            "valid": True,
            "note": "strata are a function of a pre-randomisation score only",
        }
    else:
        E["E1_prestratified_EST_tertiles"] = {
            "ate": None,
            "ci95": [None, None],
            "per_stratum": {},
            "skipped": True,
            "note": NO_EST,
        }
    pre_cols = [
        c
        for c in P.columns
        if ((c.startswith("est_") and c != "est_stratum") or c.startswith("selfreport") or c.startswith("pre_"))
        and P[c].notna().any()
    ]
    subs_present = [c for c in pre_cols if c.startswith("est_") and c != "est_composite"]
    if subs_present and "est_composite" in pre_cols:
        pre_cols.remove("est_composite")  # composite = mean of subscales → collinear; keep the parts
    P, coefs = crossfit_index(P, pre_cols) if pre_cols else (P.assign(cal_index=np.nan, cal_stratum=np.nan), [])
    if not pre_cols:
        E["E2_note"] = "E2 not computed: no pre-randomisation covariates (est_*/selfreport*/pre_*) with data"
    elif P.cal_index.notna().sum() <= 10:
        E["E2_note"] = (
            f"E2 not computed: cross-fit folds skipped (too few LLM-arm rows with transcripts for {len(pre_cols)} covariates): {coefs}"
        )
    if P.cal_index.notna().sum() > 10:
        ate2, per2 = stratified(P, "cal_stratum")
        okc = P.cal_index.notna() & P.intrial_composite.notna()
        E["E2_calibrated_pre_index_tertiles"] = {
            "ate": ate2,
            "ci95": boot_ci(lambda df: stratified(df, "cal_stratum")[0], P),
            "ci_note": "bootstrap holds the fitted index and cuts fixed, so index-estimation uncertainty is omitted (CI somewhat too narrow)",
            "same_as_E1_strata": (bool((P.cal_stratum == P.est_stratum).all()) if has_est else None),
            "per_stratum": per2,
            "weights_per_fold": coefs,
            "valid": True,
            "index_vs_intrial_r": round(float(stats.pearsonr(P.cal_index[okc], P.intrial_composite[okc]).statistic), 3),
            "note": "index = cross-fitted prediction of in-trial elicitation from pre-randomisation covariates only; transcripts supply the target, never the inputs",
        }
    # E3: naive post-hoc (BIASED) — shown only so readers can see the size of the error
    Lm = P[(P.arm == "llm") & P.intrial_composite.notna()]
    C = P[P.arm == "control"]
    tcut = np.nanpercentile(Lm.intrial_composite, [100 / 3, 200 / 3])
    top = Lm[Lm.intrial_composite >= tcut[1]]
    nobottom = Lm[Lm.intrial_composite >= tcut[0]]
    why = (
        "(1) it silently changes the estimand from the population ATE to uplift among good elicitors; (2) it selects the LLM arm on a "
        "post-treatment variable correlated with baseline ability while controls stay unselected, adding baseline differences to the estimate; "
        "(3) misclassification of who is a good elicitor dilutes it. The three can offset, so closeness to any target is not evidence of validity."
    )
    E["E3a_BIASED_posthoc_top_elicitors_vs_all_controls"] = {
        "estimate": float(top.outcome.mean() - C.outcome.mean()),
        "n_llm": int(len(top)),
        "valid": False,
        "why_invalid": why,
    }
    E["E3b_BIASED_posthoc_drop_under_elicitors"] = {
        "estimate": float(nobottom.outcome.mean() - C.outcome.mean()),
        "n_llm": int(len(nobottom)),
        "valid": False,
        "why_invalid": why,
    }
    R["estimates"] = E

    # ---- G. use-adjusted estimands (est/estimands.py). Use = any user turn across sessions (LLM-arm participants with
    #         no transcript are non-users); score = per-participant mean of --estimand-score over sessions, non-users at the
    #         minimum; pre-randomisation columns (pre_*, selfreport*, est_* subscales) tighten the stratum bounds.
    try:
        turns = S.groupby("participant_id").n_user_turns.sum()
        sc_col = a.estimand_score if a.estimand_score in S.columns else "coverage"
        per = S.groupby("participant_id")[sc_col].mean() if sc_col != "n_user_turns" else turns
        llm = P.arm == "llm"
        t_all = P.participant_id.map(turns).fillna(0)
        s_all = P.participant_id.map(per)
        use_g = np.where(llm, (t_all >= 1).astype(float), np.nan)
        floor = float(np.nanmin(s_all[llm])) if s_all[llm].notna().any() else 0.0
        score_g = np.where(llm, np.where(use_g == 1, s_all.fillna(floor), min(floor, 0.0)), np.nan)
        g_pre = [c for c in pre_cols if c in P.columns]
        thr = [(t.split(":")[0], t.split(":")[1], float(t.split(":")[2])) for t in a.threshold]
        # (B14-B3) pre-registered thresholds drive the decision table when none are given on the command line: prereg.yaml
        #   thresholds: [{name: ..., kind: ratio|diff, value: ...}]; the report names the source either way. (V57b-4) a malformed
        #   list (not a list, missing keys, non-numeric value) is reported as malformed and never aborts section G; a command-line
        #   threshold overrides a pre-registered one and the report says so.
        pm = R["trial_metadata"]["prereg.yaml"]
        pre_raw = (pm.get("fields") or {}).get("thresholds") if pm.get("present") else None
        pre_thr, pre_state = [], ("absent" if not pm.get("present") else "none" if pre_raw in (None, [], "") else "ok")
        if pre_state == "ok":
            try:
                if not isinstance(pre_raw, list):
                    raise TypeError("thresholds is not a list")
                pre_thr = [(str(t["name"]), str(t["kind"]), float(t["value"])) for t in pre_raw]
                if any(k not in ("ratio", "diff") for _, k, _ in pre_thr):
                    raise ValueError("kind must be ratio or diff")
            except Exception as ex:
                pre_thr, pre_state = [], f"malformed ({type(ex).__name__}: {ex})"
        if thr:
            thr_src = "command line (--threshold)" + (
                "; prereg.yaml thresholds present but overridden"
                if pre_thr
                else f"; prereg.yaml thresholds {pre_state}" if pre_state.startswith("malformed") else ""
            )
        elif pre_thr:
            thr, thr_src = pre_thr, "prereg.yaml"
        else:
            thr_src = {"absent": "none (no prereg.yaml)", "none": "none (prereg.yaml lists no thresholds)"}.get(
                pre_state, f"none (prereg.yaml thresholds {pre_state})"
            )
        # ceilings on the OUTCOME scale: --ceiling name:value, plus any ceiling whose submissions were graded on the trial rubric (section E outcome_scale)
        ceil_g = {t.split(":")[0]: float(t.split(":")[1]) for t in a.ceiling}
        for ct, er in (R.get("elicitation_ratio") or {}).items():
            if (
                isinstance(er, dict)
                and (er.get("outcome_scale") or {}).get("ceiling_mean_outcome") is not None
                and ct not in ceil_g
            ):
                ceil_g[ct] = float(er["outcome_scale"]["ceiling_mean_outcome"])
        cexp = {t.split(":")[0]: float(t.split(":")[1]) for t in a.control_exposure} or None
        R["use_adjusted_estimands"] = run_estimands(
            P,
            score=pd.Series(score_g),
            use=pd.Series(use_g),
            pre_cols=g_pre,
            thresholds=thr,
            B=1000,
            intensity=pd.Series(np.where(llm, t_all, np.nan)),
            intensity_name="total user turns",
            ceilings=ceil_g or None,
            perm_reps=100,
            fold_reps=a.fold_reps,
            control_model_access=a.control_access,
            control_model_exposure=cexp,
        )
        R["use_adjusted_estimands"]["inputs"] = {
            "score": sc_col,
            "use_definition": "total user turns >= 1 in sessions.json (LLM-arm participants with no session rows count as use = 0)",
            "pre_cols": g_pre,
            "ceilings": ceil_g,
            "fold_reps": a.fold_reps,
            "control_access": a.control_access,
            "control_exposure": cexp,
            "thresholds_source": thr_src,
        }
    except Exception as ex:
        R["use_adjusted_estimands"] = {"error": repr(ex)}
        print("section G skipped:", repr(ex))

    # ---- E/F. truth comparison (simulated trials only)
    if truth:
        tiers = pd.Series({k: v["tier"] for k, v in truth["participants"].items()}, name="tier")
        P = P.merge(tiers, left_on="participant_id", right_index=True, how="left")
        topt = max(truth["U"], key=truth["U"].get)
        strong_llm = P[(P.arm == "llm") & (P.tier == topt)]
        R["truth"] = {
            "ATE_population": truth["true_ATE_population"],
            "ATE_sample_mix": truth["true_ATE_sample_llm_arm_mix"],
            "per_tier_uplift": truth["U"],
            "oracle_stratified_by_true_tier": stratified(P, "tier")[1],
            "E3a_decomposition": {
                "conditional_uplift_top_tier": float(truth["U"][topt]),
                "true_tier_selected_llm_minus_all_controls": float(strong_llm.outcome.mean() - C.outcome.mean()),
                "reported_E3a": E["E3a_BIASED_posthoc_top_elicitors_vs_all_controls"]["estimate"],
                "top_tertile_composition": top.merge(
                    tiers, left_on="participant_id", right_index=True, how="left", suffixes=("", "_t")
                )
                .iloc[:, -1]
                .value_counts()
                .to_dict(),
                "reading": "conditional uplift → +selection bias (baseline rises with tier) → −dilution (tertile ≠ tier); gap to ATE is mostly estimand change in this simulation",
            },
        }
        for k in (
            "section_g_note",
            "circularity_note",
        ):  # a non-circular simulated trial (demo_trial_v2, V26) may supply its own notes
            if truth.get(k) is not None:
                R["truth"].setdefault(k, truth[k])
        if truth.get("sessions"):
            rows = []
            for _, s in S.iterrows():
                t = truth["sessions"].get(f"{s.participant_id}:{s.session_idx}")
                if t:
                    rows.append(
                        {
                            "cov_j": s.coverage,
                            "cov_c": t["controller_subscales"]["coverage"],
                            "ver_j": s.verification,
                            "ver_c": t["controller_subscales"]["verification"],
                            "per_j": s.persistence,
                            "rr_c": t["controller_subscales"]["refusal_recovery"],
                            "comp_j": s.composite,
                            "comp_c": t["controller_subscales"]["composite"],
                            "run": t["run"],
                        }
                    )
            J = pd.DataFrame(rows).drop_duplicates(
                "run"
            )  # identical transcripts now share one judge call, so keep-first == keep-last
            R["judge_vs_controller_on_unique_transcripts"] = {
                "n": int(len(J)),
                "coverage_mae": round(float((J.cov_j - J.cov_c).abs().mean()), 3),
                "coverage_r": round(float(J.cov_j.corr(J.cov_c)), 3),
                "verification_agreement": round(float((J.ver_j == J.ver_c).mean()), 3),
                "composite_spearman": round(float(J.comp_j.corr(J.comp_c, method="spearman")), 3),
                "note": "constructs differ by design (controller specificity = T2 unlocks; judge specificity = share of specific asks), so only coverage/verification/composite-rank are compared",
            }

    # ---- write
    P.to_csv(out / "participants_scored.csv", index=False)
    json.dump(R, open(out / "trial_report.json", "w"), indent=1, default=float)
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(1, 2, figsize=(9, 3.4))
        ax[0].errorbar(curve.session_idx, curve["mean"], yerr=1.96 * curve["sem"], marker="o", color="k")
        ax[0].set_xlabel("session index (LLM arm)")
        ax[0].set_ylabel("in-trial elicitation composite")
        ax[0].set_ylim(0, 1)
        ax[0].set_title("learning curve")
        if has_est:
            ax[1].scatter(L.est_composite, L.intrial_composite, s=14, color="k")
            ax[1].set_xlabel("pre-trial EST composite")
            ax[1].set_ylabel("in-trial composite (mean over sessions)")
            ax[1].set_xlim(0, 1)
            ax[1].set_ylim(0, 1)
            ax[1].set_title("predictive validity")
        else:
            ax[1].text(0.5, 0.5, "no pre-test available", ha="center", va="center")
            ax[1].set_axis_off()
        fig.tight_layout()
        fig.savefig(out / "learning_curve.png", dpi=130)
    except Exception as e:
        print("plot skipped:", e)
    write_md(R, out / "trial_report.md", truth is not None)
    print("wrote", out / "trial_report.md")


def f3(x):
    return "n/a" if x is None or (isinstance(x, float) and x != x) else f"{x:.3f}"


def write_md(R, path, has_truth):
    E = R["estimates"]
    L = []
    L += [
        "# Post-trial transcript report",
        "",
        f"{R['n_participants']} participants ({R['n_llm']} LLM arm), {R['n_sessions']} sessions, {R['n_unique_transcripts']} unique transcripts judged. Composite = {R['composite_definition']}; sessions by number of defined subscales {R['sessions_by_n_defined']}.",
    ]
    if R.get("pseudo_replication_warning"):
        L += ["", "**Warning: " + R["pseudo_replication_warning"] + ".**"]
    if R["tasks_without_designer_targets"]:
        L += [f"Tasks judged against an LLM-derived target list (weaker): {R['tasks_without_designer_targets']}"]
    # (B14-B3 2026-09-08) what the trial recorded about itself (checklist items 7, 9 to 13): quoted when present, NOT COLLECTED when absent
    TM = R.get("trial_metadata") or {}
    if TM:
        L += ["", "## Trial metadata (trial/SCHEMA.md checklist items 7, 9 to 13)", ""]
        for fn, item in (
            (
                "prereg.yaml",
                "item 7, pre-registered estimands, compliance definition, analysis model, thresholds, date",
            ),
            (
                "arms.yaml",
                "items 9 to 11 and 13, assistant condition, model snapshot, tools, time budget, training, data handling",
            ),
            ("grading.yaml", "item 12, grader identity, blinding, grading batch shared with the ceilings"),
        ):
            m = TM.get(fn) or {}
            if not m.get("present"):
                L += [
                    f"- `{fn}` ({item}): NOT COLLECTED"
                    + (f" ({m['error']})" if m.get("error") else "")
                    + ". "
                    + (
                        "Without it the report cannot say which estimand the headline number was registered to answer; thresholds below come from the command line or are absent."
                        if fn == "prereg.yaml"
                        else (
                            "Without it the assistant condition and model the LLM arm faced are undocumented, so persistence and any ceiling ratio cannot be compared across trials."
                            if fn == "arms.yaml"
                            else "Without it nothing ties the ceiling grades to the participants' grading pass, so a rubric-scale ratio is not comparable."
                        )
                    )
                ]
            else:
                f = m["fields"]
                shown = {k: f[k] for k in TRIAL_META_FILES[fn] if f.get(k) not in (None, "", [])}
                L += [
                    f"- `{fn}` ({item}): "
                    + (
                        "; ".join(f"{k} = {json.dumps(v, default=str)}" for k, v in shown.items())
                        if shown
                        else "present but empty (no checklist field filled)"
                    )
                    + (f". Missing fields: {m['missing_fields']}." if m.get("missing_fields") else ".")
                ]
    L += [
        "",
        "## Uplift estimates",
        "",
        "| estimator | estimate | 95% CI | valid for inference? |",
        "|---|---|---|---|",
    ]
    L += [
        f"| E0 unadjusted difference in means | {f3(E['E0_unadjusted']['ate'])} | {f3(E['E0_unadjusted']['ci95'][0])} to {f3(E['E0_unadjusted']['ci95'][1])} | yes |"
    ]
    e1 = E["E1_prestratified_EST_tertiles"]
    if e1.get("skipped"):
        L += [f"| E1 pre-stratified on EST tertiles | not computed | n/a | ({e1['note']}) |"]
    else:
        L += [
            f"| E1 pre-stratified on EST tertiles | {f3(e1['ate'])} | {f3(e1['ci95'][0])} to {f3(e1['ci95'][1])} | yes |"
        ]
    if "E2_calibrated_pre_index_tertiles" in E:
        e2 = E["E2_calibrated_pre_index_tertiles"]
        L += [
            f"| E2 stratified on calibrated pre-treatment index | {f3(e2['ate'])} | {f3(e2['ci95'][0])} to {f3(e2['ci95'][1])} | yes |"
        ]
    elif E.get("E2_note"):
        L += [f"| E2 stratified on calibrated pre-treatment index | not computed | n/a | ({E['E2_note']}) |"]
    L += [
        f"| E3a post-hoc: top-tertile in-trial elicitors vs all controls | {f3(E['E3a_BIASED_posthoc_top_elicitors_vs_all_controls']['estimate'])} | not computed | **NO, biased** |",
        f"| E3b post-hoc: drop bottom-tertile elicitors vs all controls | {f3(E['E3b_BIASED_posthoc_drop_under_elicitors']['estimate'])} | not computed | **NO, biased** |",
    ]
    if has_truth:
        T = R["truth"]
        D = T["E3a_decomposition"]
        L += [
            "",
            f"Known truth (simulated trial): population ATE {T['ATE_population']:.3f}; sample-mix ATE {T['ATE_sample_mix']:.3f}; per-tier uplift {T['per_tier_uplift']}.",
            "Oracle per-true-tier effects: "
            + ", ".join(f"{k} {f3(v['effect'])} (n={v['n']})" for k, v in T["oracle_stratified_by_true_tier"].items()),
            f"E3a decomposition: true conditional uplift in top tier {f3(D['conditional_uplift_top_tier'])}; selecting true-top-tier LLM participants vs all controls gives {f3(D['true_tier_selected_llm_minus_all_controls'])} (selection bias from the tier-dependent baseline); reported E3a {f3(D['reported_E3a'])} after dilution because the in-trial top tertile is {D['top_tertile_composition']}. {D['reading']}.",
            "**Circularity (simulated demo): pre-test scores and transcripts come from the same scripted policies, so predictive validity, E1 per-stratum effects (= oracle), E2 per-stratum effects, rank stability and the learning curve below are artefacts of construction, not evidence. Only the judge-vs-controller agreement is a non-circular check; the estimator table shows the code runs and that E3 targets a different estimand.**",
        ]
    if not e1.get("skipped"):
        L += [
            "",
            "Per-stratum effects (E1, pre-test tertiles low→high): "
            + ", ".join(f"{f3(v['effect'])} (n={v['n']})" for v in e1["per_stratum"].values()),
        ]
    else:
        L += [""]
    if "E2_calibrated_pre_index_tertiles" in E:
        L += [
            "Per-stratum effects (E2, calibrated index tertiles low→high): "
            + ", ".join(f"{f3(v['effect'])} (n={v['n']})" for v in e2["per_stratum"].values())
            + f"; index vs in-trial r = {e2['index_vs_intrial_r']}; strata identical to E1: {e2['same_as_E1_strata']}. {e2['ci_note']}."
        ]
    # (B14-B3 2026-09-08) the section is always printed: an absent ceiling file or kind is a gap in the trial's data collection
    # and is said so (NOT COMPUTABLE), never left out; a ceiling that covers too few tasks or mixes protocols is REFUSED.
    ER = R.get("elicitation_ratio")
    L += [
        "",
        "## Elicitation ratio (LLM arm as a share of each ceiling; both reported, they answer different questions)",
    ]
    if not ER:
        L += [
            "",
            "NOT COMPUTABLE: "
            + R.get("elicitation_ratio_absent_reason", "no ceiling records")
            + ". Without a `model_alone` and an "
            "`expert_with_model` ceiling on this trial's tasks (trial/SCHEMA.md, section ceilings.jsonl) the effect above cannot be expressed as a "
            "share of what the model can produce (R_cap) or of what a skilled elicitor extracts (R_hum). This is a gap in the trial's data collection, not a null result.",
        ]
    else:
        for need in CEIL_KINDS:
            if need not in ER or ER[need] is None:
                L += [
                    "",
                    f"NOT COMPUTABLE for `{need}`: "
                    + ("no records of this kind" if need not in ER else "its records share no task with the LLM arm")
                    + f"; {'R_cap' if need == 'model_alone' else 'R_hum'} is not reported.",
                ]
        for ct, e in ER.items():
            if e and e.get("refused"):
                L += ["", f"REFUSED for `{ct}`: {e['refused']}."]
        for ct, e in ER.items():
            if e and not e.get("refused") and e.get("flags"):
                L += ["", f"Flags for `{ct}`: " + "; ".join(e["flags"]) + "."]
        if R.get("ceilings_schema_problems"):
            L += [
                "",
                f"ceilings.jsonl provenance: {len(R['ceilings_schema_problems'])} record(s) lack required fields (first: {R['ceilings_schema_problems'][0]}); "
                "full list under ceilings_schema_problems in trial_report.json. Required fields and why: trial/SCHEMA.md, section ceilings.jsonl.",
            ]
    if ER and any(e and not e.get("refused") for e in ER.values()):
        ER = {ct: e for ct, e in ER.items() if e and not e.get("refused")}
        L += [
            "",
            "| ceiling | question it answers | LLM-arm yield | ceiling yield | ratio | 95% CI | ceiling records (per task) | circular in this run? |",
            "|---|---|---|---|---|---|---|---|",
        ]
        qs = {
            "model_alone": "capability: share of what the model produces with full access that reached participants' answers",
            "expert_with_model": "human: share of what a skilled elicitor extracts from the same gated assistant",
        }
        for ct, e in ER.items():
            if not e:
                continue
            if e.get("ci_withheld"):
                pci = e.get("ratio_ci95_participants_only_ceiling_fixed")
                why = (
                    f"elicitor_id missing on {e['records_without_unit']} record(s)"
                    if e.get("records_without_unit")
                    else f"<{MIN_REF_RECORDS} independent ceiling units on some task"
                )
                ci = f"WITHHELD ({why})" + (
                    f"; participant-side only, ceiling held fixed: {f3(pci[0])} to {f3(pci[1])}" if pci else ""
                )
            else:
                ci = f"{f3(e['ratio_ci95'][0])} to {f3(e['ratio_ci95'][1])}" if e.get("ratio_ci95") else "n/a"
            ov = e.get("ceiling_records_hash_identical_to_llm_sessions")
            circ = ("YES (stand-in)" if e["circular"] else "no") + (
                f"; {ov} of {e['n_ceiling_records']} ceiling records hash-identical to {e.get('llm_sessions_hash_identical_to_ceiling_records')} of {e['n_llm_sessions']} LLM-arm sessions"
                if ov is not None
                else ""
            )
            rpt = "/".join(str(v) for v in e.get("ceiling_records_per_task", {}).values())
            if not (e.get("reference_adequacy") or {}).get("adequate", True):
                rpt += f"; fewer than {MIN_REF_RECORDS} independent units on some task: insufficient reference sessions"
            L += [
                f"| {ct} | {qs.get(ct, ct)} | {f3(e['llm_arm_yield'])} | {f3(e['ceiling_yield'])} | {f3(e['ratio'])} | {ci} | {e['n_ceiling_records']} ({rpt}) | {circ} |"
            ]
        e0 = next(iter([e for e in ER.values() if e]))
        L += [
            "",
            "Yield is the share of designer targets reflected in the final answer, macro-averaged over tasks. "
            + e0["scale_note"]
            + ". If ceiling submissions are graded on the trial's own rubric (add `outcome` to ceilings.jsonl), the same table is also printed on that scale.",
            "",
            "CI note: percentile interval from a cluster bootstrap over LLM-arm participants with ceiling records resampled within task "
            + f"({e0['bootstrap']['n_boot']} replicates; dropped replicates: "
            + ", ".join(f"{ct} {e['bootstrap']['dropped']}" for ct, e in ER.items() if e)
            + "). "
            + f"With fewer than {MIN_REF_RECORDS} independent ceiling units (seeds, elicitors or distinct transcripts; an expert_with_model record without elicitor_id has no unit) on any task the ceiling side of the interval is unmeasured, so the 95% CI is WITHHELD and only the participant-side interval (ceiling held fixed) is shown for orientation; if LLM-arm transcripts are duplicated across participants (see pseudo-replication warning above, if printed) even that is too narrow. Treat it as a code check in the demo, not as an inferential interval.",
            "",
            "Where the gap sits. Each designer target is weighted by the share of the task's ceiling records whose final answer used it (the ceiling's reach frequency), so a target every ceiling run reached counts fully and one reached by a single run out of n counts 1/n. "
            "Each cell is the weighted share of (session x target) mass in that category, divided by the expected number of targets one ceiling run reaches, pooled over tasks with the same ceiling-yield weighting as the ratio above. "
            "'Beyond ceiling' is the mass participants reached on targets the ceiling did not reach, or reached in only some runs; by construction reached + beyond ceiling = ratio, so the table accounts for the whole ratio. "
            "'Ceiling self-agreement' scores each ceiling run on the same 'reached' scale against the other runs of its task (leave-one-out); participants' 'reached' should be read against that number, not against 1. "
            f"With fewer than {MIN_REF_RECORDS} independent ceiling units (seeds, elicitors or distinct transcripts; records that repeat a unit do not count) on some task the row is flagged: the weights are then 0/1 (one run) or 0/0.5/1 (two runs), self-agreement is undefined or rests on one pair, and the table describes the shortfall against the available run(s) rather than against what the ceiling reliably reaches. Tasks on which the ceiling reached nothing have no per-task shares (listed in the JSON as gap_tasks_with_empty_ceiling) but still enter the pooled row through 'beyond ceiling'.",
            "",
            "| ceiling | ceiling records per task (min) | reference status | reached by participant | beyond ceiling | never raised | raised only generally, not provided | raised specifically, still not provided | provided, not used in answer | ceiling self-agreement (LOO) | sessions with a non-answer never retried | verification rate: arm vs ceiling |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for ct, e in ER.items():
            if not e or not e.get("gap_decomposition_share_of_ceiling_targets"):
                continue
            g = e["gap_decomposition_share_of_ceiling_targets"]
            ra = e.get("reference_adequacy") or {}
            status = (
                "adequate"
                if ra.get("adequate")
                else f"INSUFFICIENT (<{MIN_REF_RECORDS} independent units; min {ra.get('min_independent_units_per_task')})"
            )
            cver = (
                f3(e["ceiling_verification_rate"])
                if e.get("ceiling_verification_rate") is not None
                else "n/a (single-turn ceiling)"
            )
            loo = (
                f3(e.get("ceiling_loo_self_agreement"))
                if e.get("ceiling_loo_self_agreement") is not None
                else "n/a (1 record)"
            )
            L += [
                f"| {ct} | {ra.get('min_ceiling_records_per_task')} | {status} | {f3(e['reached_share_of_ceiling_targets'])} | {f3(e.get('beyond_ceiling_share'))} | {f3(g['never_raised'])} | {f3(g['raised_general_only_not_provided'])} | {f3(g['raised_specific_not_provided'])} | {f3(g['provided_not_used'])} | {loo} | {f3(e['llm_sessions_with_nonanswer_never_retried'])} | {f3(e['llm_arm_verification_rate'])} vs {cver} |"
            ]
        for ct, e in ER.items():
            if e and e.get("outcome_scale"):
                o = e["outcome_scale"]
                L += [
                    "",
                    f"On the trial-rubric scale ({ct}): LLM arm {f3(o['llm_arm_mean_outcome'])} vs ceiling {f3(o['ceiling_mean_outcome'])}, ratio {f3(o['ratio'])}. {o['note']}.",
                ]
        if has_truth:
            L += [
                "",
                "**Demo caveats: the `expert_with_model` ceiling here (legacy kind `expert`) is the scripted STRONG policy; its transcripts are hash-identical to the simulated top-tier participants' sessions (same cached judge call, see the circular column), so its ratio and CI are circular and shown only to exercise the code. 'Provided, not used' is 0 in this demo: synthetic submissions summarise the conversation, so dropping an obtained record is rare by construction and did not occur. The `model_alone` ceiling is a genuine single model call with every record in context and is not circular, but on EST items it is near-trivial by construction (nothing is withheld from it), so the informative real-trial analogue is a model or agent given the trial task and tools with no human in the loop.**",
            ]
    L += [
        "",
        "E3 is printed only to show what NOT to report. "
        + E["E3a_BIASED_posthoc_top_elicitors_vs_all_controls"]["why_invalid"]
        + " (Montgomery, Nyhan & Torres 2018.) Use transcripts to validate and, where several pre-trial covariates exist, re-weight the PRE-trial measure (E2); whether that improves on E1 is an empirical question the demo cannot answer.",
    ]
    G = R.get("use_adjusted_estimands")
    csd = ((G or {}).get("itt") or {}).get("control_sd")
    if G and "error" not in G:
        gi = G.get("inputs", {})
        if csd is not None and not (csd > 0):
            # A control arm with zero outcome variance (every control at the same score, as in the shipped simulation)
            # makes the stratum bounds collapse to a point and every control-SD scaling undefined; print one line, not
            # the table. The JSON output keeps the full section.
            L += [
                "",
                "## Use-adjusted estimands (section G)",
                "",
                f"Table not printed for this trial: the control-arm outcome has no variance (mean {f3(G['itt']['control_mean'])}, SD 0), "
                "so the stratum bounds collapse to a point and quantities scaled by the control SD are undefined. "
                "The values are in trial_report.json; the full section prints for a trial whose control arm has a "
                "non-degenerate outcome.",
            ]
        else:
            L += [""] + estimands_md(
                G,
                title="Use-adjusted estimands (section G: what the ITT leaves out)",
                score_name=f"per-participant mean session {gi.get('score', 'coverage')}",
                use_def=gi.get("use_definition", "any user turn"),
            )
        ts = gi.get("thresholds_source")
        if ts == "prereg.yaml":
            L += [
                "",
                "Decision thresholds in section G come from prereg.yaml (pre-registered, trial/SCHEMA.md item 7).",
            ]
        elif ts and ts.startswith("command line"):
            L += [
                "",
                "Decision thresholds in section G were given on the command line (--threshold); "
                + (
                    "prereg.yaml also lists thresholds and the command line overrode them, which the reader should treat as a departure from the pre-registration."
                    if "overridden" in ts
                    else (
                        "prereg.yaml lists thresholds but they are malformed "
                        + ts.split("malformed ", 1)[1]
                        + ", so the pre-registered rule could not be applied."
                        if "malformed" in ts
                        else "no prereg.yaml thresholds were found."
                    )
                )
                + " A threshold chosen after seeing the data is not a pre-registered decision rule.",
            ]
        elif ts:
            L += [
                "",
                "No decision thresholds in section G: nothing was given on the command line and "
                + {
                    "none (no prereg.yaml)": "there is no prereg.yaml",
                    "none (prereg.yaml lists no thresholds)": "prereg.yaml lists no thresholds",
                }.get(ts, ts[len("none (") : -1] if ts.startswith("none (") and ts.endswith(")") else ts)
                + ", so no rule-out or rule-in statement is made.",
            ]
        if has_truth:
            tn = R.get("truth") or {}
            gnote = tn.get("section_g_note") or (
                (
                    "**Simulated trial (section G): the set arithmetic is a code check at this size; see truth.json circularity_note for what the pre-test covariates are.**"
                    if tn.get("circularity_note")
                    else "**Demo caveat for section G: the pre-test covariates and the in-trial scores come from the same scripted policies, so the covariate-tightened set and its AUC are circular here; only the unconditional set and the CACE arithmetic are a genuine code check.**"
                )
            )
            L += ["", gnote]
    elif G:
        L += ["", f"Section G (use-adjusted estimands) skipped: {G['error']}"]
    pv = R["predictive_validity_vs_intrial_composite"]
    L += (
        ["", "## Does the pre-trial test predict in-trial elicitation?", ""]
        + ([f"**{R['predictive_validity_note']}.**", ""] if R.get("predictive_validity_note") else [])
        + ["| pre-trial measure | Pearson r | R² | Spearman | 95% CI (r) | n |", "|---|---|---|---|---|---|"]
    )
    L += [
        f"| {k} | {v['pearson_r']} | {v['r2']} | {v['spearman']} | {f3(v['r_ci95'][0])} to {f3(v['r_ci95'][1])} | {v['n']} |"
        for k, v in pv.items()
    ]
    rs = R["rank_stability_first_vs_last"]
    g = R["gain_first_to_last"]
    L += [
        "",
        "## Learning and rank stability within the trial (LLM arm)",
        "",
        f"First-session vs last-session composite: Spearman {rs['spearman']} (95% CI {f3(rs['ci95'][0])} to {f3(rs['ci95'][1])}, n={rs['n']}); mean gain {g['mean']} (SD {g['sd']}).",
        "Learning curve (mean composite by session index): "
        + ", ".join(
            f"{c['session_idx']}: {c['mean']:.3f}±{1.96*c['sem']:.3f} (n={c['count']})" for c in R["learning_curve"]
        ),
        "If rank stability is low, the pre-trial score's value as a stratifier is correspondingly low (README kill criterion); the warm-up use is unaffected.",
    ]
    u = R["under_elicitation_audit"]
    L += ["", "## Under-elicitation audit (share of LLM-arm sessions)", "", "| indicator | share |", "|---|---|"] + [
        f"| {k.replace('_',' ')} | {v} |" for k, v in u.items()
    ]
    if "judge_vs_controller_on_unique_transcripts" in R:
        j = R["judge_vs_controller_on_unique_transcripts"]
        L += [
            "",
            "## Transcript judge vs controller ground truth (EST transcripts only)",
            "",
            f"n={j['n']} unique transcripts: coverage MAE {j['coverage_mae']}, r {j['coverage_r']}; verification agreement {j['verification_agreement']}; composite Spearman {j['composite_spearman']}. {j['note']}",
        ]
    L += ["", "Inputs and schema: trial/SCHEMA.md. Judge prompt: est/transcripts.py. All numbers in trial_report.json."]
    open(path, "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()

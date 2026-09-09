"""Checks for the ceiling provenance rules in analyze_trial.py (B14 Block B3, 2026-09-08; trial/SCHEMA.md, section ceilings.jsonl)
and the B06 frequency-weighted gap identity. Run: .venv/bin/python tests/test_analyze_trial_ceilings.py
Parts 1 to 4 are unit checks on synthetic scored frames (no judge, no files). Part 5 runs analyze_trial.main() end to end on a
temporary copy of demo_trial_v2 with every model call stubbed to raise, once without ceilings.jsonl (NOT COMPUTABLE path) and
once with arms.yaml / grading.yaml / prereg.yaml added (metadata path, prereg thresholds driving section G). Part 5 needs
demo_trial_v2/judge_cache.json to be complete; it is skipped with a message when demo_trial_v2 is absent."""
import pathlib, sys, json, shutil, tempfile, io, contextlib, copy
W = pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0, str(W))
import numpy as np, pandas as pd
import analyze_trial as az

fails = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond: fails.append(name)

# ---------------------------------------------------------------------------------------------------------------------
# synthetic scored frames: 4 tasks, 6 LLM-arm participants, designer targets K1..K4 per task
TASKS = ["t1", "t2", "t3", "t4"]; K = ["K1", "K2", "K3", "K4"]
def sess(pid, t, used, provided=(), specific=(), asked=(), nonans=0, retries=0, ver=0):
    used = list(used); provided = list(set(provided) | set(used)); specific = list(set(specific) | set(provided)); asked = list(set(asked) | set(specific))
    return {"participant_id": pid, "task_id": t, "target_yield": len(used) / len(K), "used_ids": used, "provided_ids": provided, "specific_ids": specific,
            "asked_ids": asked, "n_nonanswers": nonans, "n_retries": retries, "verification": ver, "transcript_hash": f"h_{pid}_{t}", "n_user_turns": 3}
def ceil(kind, t, used, unit, protocol="MA-v1", cond="helpful_only", agg="single", model="m-A", batch="b1", rid=None):
    return {"participant_id": rid or f"c_{kind}_{t}_{unit}", "ceiling": kind, "task_id": t, "target_yield": len(used) / len(K), "used_ids": list(used),
            "verification": 0, "n_user_turns": 1, "circular": False, "transcript_hash": f"hc_{kind}_{t}_{unit}", "outcome": 1.0,
            "protocol_id": protocol, "assistant_condition": cond, "aggregation": agg, "model_id": model, "grading_batch_id": batch, "unit_id": unit}
rng = np.random.default_rng(3)
S_rows = []
for i in range(6):
    for t in TASKS:
        used = [k for k in K if rng.random() < 0.5]
        S_rows.append(sess(f"p{i}", t, used, specific=[k for k in K if rng.random() < 0.3], asked=[k for k in K if rng.random() < 0.3]))
S = pd.DataFrame(S_rows)
P_llm = pd.DataFrame({"participant_id": [f"p{i}" for i in range(6)], "arm": "llm", "outcome": rng.random(6)})
def C_of(rows): return pd.DataFrame(rows)

# ---- 1. record normalisation ------------------------------------------------------------------------------------------
print("--- 1. normalise_ceiling_record")
r, prob = az.normalise_ceiling_record({"ceiling": "expert", "task_id": "t1", "participant_id": "c1", "messages": [], "submission": "x", "ceiling_model": "m-A"}, 0)
check("legacy kind 'expert' maps to expert_with_model", r["ceiling"] == "expert_with_model")
check("legacy ceiling_model copied to model_id", r["model_id"] == "m-A")
check("missing provenance listed, elicitor_id required for the human ceiling", prob is not None and "protocol_id" in prob and "elicitor_id" in prob and "model_id" not in prob, prob)
r, prob = az.normalise_ceiling_record({"kind": "model_alone", "task_id": "t1", "participant_id": "c1", "messages": [], "submission": "x", "protocol_id": "MA-v1",
                                       "model_id": "m", "assistant_condition": "helpful_only", "aggregation": "single"}, 1)
check("complete model_alone record has no problem", prob is None and r["ceiling"] == "model_alone", prob)
try:
    az.normalise_ceiling_record({"kind": "best_guess", "task_id": "t1", "participant_id": "c1"}, 2); check("unknown kind stops the run", False)
except SystemExit as ex: check("unknown kind stops the run", "best_guess" in str(ex))

# ---- 2. refusals ----------------------------------------------------------------------------------------------------
print("--- 2. refusals")
C1 = C_of([ceil("model_alone", "t1", ["K1", "K2", "K3"], "s1")])                     # covers 1 of 4 tasks
out = az.elicitation_ratio(S, C1, "model_alone", P_llm, n_boot=50)
check("ceiling on 1 of 4 LLM-arm tasks is refused", out is not None and "refused" in out and "ratio" not in out, out.get("refused") if out else None)
check("refusal names the uncovered tasks", sorted(out.get("llm_tasks_without_ceiling", [])) == ["t2", "t3", "t4"])
C2 = C_of([ceil("model_alone", t, ["K1", "K2", "K3"], "s1", protocol=("MA-v1" if t != "t4" else "MA-v2")) for t in TASKS])
out = az.elicitation_ratio(S, C2, "model_alone", P_llm, n_boot=50)
check("mixed protocol_id within a kind is refused", out is not None and "refused" in out and "protocol" in out["refused"], out.get("refused") if out else None)
check("refusal lists both protocols", out.get("protocols") == ["MA-v1", "MA-v2"])
C3 = C_of([ceil("model_alone", t, ["K1", "K2", "K3"], "s1") for t in TASKS[:2]])         # exactly 50% coverage is allowed
out = az.elicitation_ratio(S, C3, "model_alone", P_llm, n_boot=50)
check("exactly half the tasks covered is not refused (boundary)", out is not None and "refused" not in out and out["tasks"] == ["t1", "t2"])
S5 = pd.concat([S, pd.DataFrame([sess("p0", "t5", ["K1"]), sess("p1", "t5", ["K2"])])], ignore_index=True)   # 5 LLM-arm tasks
out = az.elicitation_ratio(S5, C3, "model_alone", P_llm, n_boot=20)
check("2 of 5 tasks (40%) is refused: the rule is under 50%, not under 40%", out is not None and "refused" in out and "2 of 5" in out["refused"], out.get("refused") if out else None)
check("no ceiling task overlap returns None (reported as NOT COMPUTABLE for that kind)", az.elicitation_ratio(S, C_of([ceil("model_alone", "zz", ["K1"], "s1")]), "model_alone", P_llm, n_boot=5) is None)

# ---- 3. CI withheld vs reported, independent units --------------------------------------------------------------------
print("--- 3. CI rule")
C_n1 = C_of([ceil("model_alone", t, ["K1", "K2", "K3"], "s1") for t in TASKS])
o1 = az.elicitation_ratio(S, C_n1, "model_alone", P_llm, n_boot=100)
check("1 unit per task: CI withheld, ratio still reported", o1["ci_withheld"] and o1["ratio_ci95"] is None and o1["ratio"] is not None)
check("1 unit per task: participant-side interval kept under its own name", isinstance(o1["ratio_ci95_participants_only_ceiling_fixed"], list) and len(o1["ratio_ci95_participants_only_ceiling_fixed"]) == 2)
check("1 unit per task: reference_adequacy.adequate False and md flag text present", o1["reference_adequacy"]["adequate"] is False and "insufficient" in (o1["reference_adequacy"]["note"] or ""))
C_n3 = C_of([ceil("model_alone", t, u, f"s{j}") for t in TASKS for j, u in enumerate([["K1", "K2", "K3"], ["K1", "K2"], ["K1", "K2", "K3", "K4"]])])
o3 = az.elicitation_ratio(S, C_n3, "model_alone", P_llm, n_boot=100)
check("3 distinct seeds per task: CI reported, not withheld", (not o3["ci_withheld"]) and isinstance(o3["ratio_ci95"], list) and o3["ratio_ci95_participants_only_ceiling_fixed"] is None)
check("3 seeds per task: reference adequate, LOO self-agreement defined in (0,1]", o3["reference_adequacy"]["adequate"] and o3["ceiling_loo_self_agreement"] is not None and 0 < o3["ceiling_loo_self_agreement"] <= 1)
check("independent_units_per_task counted", o3["independent_units_per_task"] == {t: 3 for t in TASKS})
# three records per task but the same elicitor: one independent unit, CI withheld
C_same = C_of([ceil("expert_with_model", t, u, "elicitor_X", rid=f"e_{t}_{j}") for t in TASKS for j, u in enumerate([["K1", "K2", "K3"], ["K1", "K2"], ["K1", "K2", "K3", "K4"]])])
os_ = az.elicitation_ratio(S, C_same, "expert_with_model", P_llm, n_boot=100)
check("3 records per task from ONE elicitor count as 1 unit: CI withheld", os_["ci_withheld"] and os_["independent_units_per_task"] == {t: 1 for t in TASKS} and os_["n_ceiling_records"] == 12)
check("B06 identity holds on synthetic data: reached + beyond = ratio (pooled)", abs((o3["reached_share_of_ceiling_targets"] + o3["beyond_ceiling_share"]) - o3["ratio"]) < 2e-3 and o3["gap_identity_max_abs_error"] < 1e-6,
      f"{o3['reached_share_of_ceiling_targets']}+{o3['beyond_ceiling_share']} vs {o3['ratio']}")

# three elicitors on every task but one extra record without a unit on t1: independence not established -> withheld, adequacy false
C_mix = C_of([ceil("expert_with_model", t, ["K1", "K2", "K3"], f"e{j}") for t in TASKS for j in range(3)] + [ceil("expert_with_model", "t1", ["K1"], None, rid="c_nounit")])
out = az.elicitation_ratio(S, C_mix, "expert_with_model", P_llm, n_boot=50)
check("3 units per task plus one unit-less record: CI withheld with the elicitor reason, 3 units still counted", out["ci_withheld"] and out["records_without_unit"] == 1
      and "elicitor_id missing" in out["ci_withheld_reason"] and out["independent_units_per_task"] == {t: 3 for t in TASKS} and out["ratio_ci95"] is None)
# reference adequacy follows units, not records (V57b fix round issue 1)
C_dup = C_of([ceil("model_alone", t, ["K1", "K2", "K3"], "s1", rid=f"c_{t}_{j}") for t in TASKS for j in range(3)])
out = az.elicitation_ratio(S, C_dup, "model_alone", P_llm, n_boot=50)
check("3 records from one unit per task: reference INSUFFICIENT (min units 1, min records 3), LOO flagged inflated", out["reference_adequacy"]["adequate"] is False
      and out["reference_adequacy"]["min_independent_units_per_task"] == 1 and out["reference_adequacy"]["min_ceiling_records_per_task"] == 3 and "inflated" in out["reference_adequacy"]["note"])
out = az.elicitation_ratio(S, C_of([ceil("model_alone", t, ["K1", "K2", "K3"], f"s{j}") for t in TASKS for j in range(3)]), "model_alone", P_llm, n_boot=50)
check("3 distinct units per task: reference adequate", out["reference_adequacy"]["adequate"] is True and out["reference_adequacy"]["min_independent_units_per_task"] == 3)

# ---- 4. flags -------------------------------------------------------------------------------------------------------
print("--- 4. flags")
check("fully documented ceiling carries no flags", o3["flags"] == [] and o3["protocol_id"] == "MA-v1" and o3["ceiling_model_ids"] == ["m-A"], o3["flags"])
C_f = C_of([ceil("model_alone", t, ["K1", "K2", "K3"], f"s{j}", protocol=None, cond=None, agg=("best_of_k" if j == 0 else "single"), model=None) for t in TASKS for j in range(3)])
of = az.elicitation_ratio(S, C_f, "model_alone", P_llm, n_boot=50)
fl = " | ".join(of["flags"])
check("undocumented protocol flagged", "protocol undocumented" in fl)
check("missing assistant_condition flagged", "assistant_condition missing" in fl)
check("best_of_k aggregation flagged", "best-of-k" in fl)
check("missing model_id flagged", "model_id missing" in fl)
og = az.elicitation_ratio(S, C_n3, "model_alone", P_llm, n_boot=50, arm_meta={"assistant_condition": "safeguarded", "model_id": "m-B"}, grading_meta={"batch_id": "b2"})
fl = " | ".join(og["flags"])
check("condition differing from arms.yaml flagged", "assistant_condition differs" in fl)
check("cross-model vs arms.yaml flagged", "cross-model" in fl and "m-B" in fl)
check("grading batch differing from grading.yaml flagged", "grading_batch_id differs" in fl)
oh = az.elicitation_ratio(S, C_n3, "model_alone", P_llm, n_boot=50, arm_meta={"assistant_condition": "helpful_only", "model_id": "m-A"}, grading_meta={"batch_id": "b1"})
check("matching arms.yaml / grading.yaml produce no flags", oh["flags"] == [], oh["flags"])

# ---- 5. end to end: NOT COMPUTABLE and metadata paths (model calls stubbed) --------------------------------------------
print("--- 5. end to end on a copy of demo_trial_v2 (model calls blocked)")
src = W / "demo_trial_v2"
if not (src / "participants.csv").exists() or not ((src / "judge_cache").exists() or (src / "judge_cache.json").exists()):
    print("SKIP part 5: demo_trial_v2 not available")
else:
    import est.llm as _llm, est.transcripts as _tr
    def _blocked(*a, **k): raise RuntimeError("MODEL CALL BLOCKED in test: uncached judge item")
    _llm.complete = _blocked; _llm.complete_json = _blocked; _tr.complete_json = _blocked
    def run_copy(tag, prepare, extra_args=()):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"b3_{tag}_"))
        for f in ["participants.csv", "transcripts.jsonl", "tasks.yaml", "truth.json", "ceilings.jsonl"]:
            if (src / f).exists(): shutil.copy(src / f, tmp / f)
        for f in ["judge_cache.json"]:  # shipped judge outputs, one bundle file; a loose judge_cache/ dir is copied too if present
            if (src / f).exists(): shutil.copy(src / f, tmp / f)
        if (src / "judge_cache").is_dir(): shutil.copytree(src / "judge_cache", tmp / "judge_cache")
        (tmp / "results").mkdir(); shutil.copy(src / "results" / "sessions.json", tmp / "results" / "sessions.json")
        old_argv = sys.argv; sys.argv = ["analyze_trial.py", "--trial-dir", str(tmp), "--no-judge", "--fold-reps", "3", *extra_args]
        buf = io.StringIO()
        try:   # (V57b round 3) the tmp dir is removed on every exit path, so a SystemExit inside main() leaves nothing behind
            prepare(tmp)
            with contextlib.redirect_stdout(buf): az.main()
            R = json.load(open(tmp / "results" / "trial_report.json")); md = open(tmp / "results" / "trial_report.md").read()
        finally:
            sys.argv = old_argv; shutil.rmtree(tmp, ignore_errors=True)
        return R, md
    # 5a: no ceilings.jsonl
    R, md = run_copy("noceil", lambda tmp: (tmp / "ceilings.jsonl").unlink())
    check("5a no ceilings.jsonl: section still printed with NOT COMPUTABLE", "## Elicitation ratio" in md and "NOT COMPUTABLE: no ceilings.jsonl" in md)
    check("5a JSON records the absence and both missing kinds", R["elicitation_ratio"] is None and R["elicitation_ratio_absent_kinds"] == ["model_alone", "expert_with_model"])
    check("5a trial metadata files reported NOT COLLECTED", md.count("NOT COLLECTED") == 3 and all(not R["trial_metadata"][f]["present"] for f in az.TRIAL_META_FILES))
    check("5a section G still ran without ceilings", isinstance(R.get("use_adjusted_estimands"), dict) and "error" not in R["use_adjusted_estimands"])
    # 5b: only model_alone kind kept -> NOT COMPUTABLE for expert_with_model; metadata files present; prereg thresholds drive section G
    def prep_meta(tmp):
        recs = [json.loads(l) for l in open(tmp / "ceilings.jsonl") if l.strip()]
        with open(tmp / "ceilings.jsonl", "w") as fh:
            for rec in recs:
                if rec.get("kind", rec.get("ceiling")) == "model_alone": fh.write(json.dumps(rec) + "\n")
        (tmp / "arms.yaml").write_text("assistant_condition: helpful_only\nmodel_id: demo-sim-v2\ntools: []\ntime_budget_min: 20\n")
        (tmp / "grading.yaml").write_text("grader_ids: [g1]\nblinded: true\nbatch_id: batch-1\n")
        (tmp / "prereg.yaml").write_text("estimands: [ITT, CACE]\ncompliance_definition: at least one user turn\nanalysis_model: difference in means\n"
                                         "thresholds:\n  - {name: prereg_diff, kind: diff, value: 0.25}\ndate_registered: 2026-09-01\n")
    R, md = run_copy("meta", prep_meta)
    check("5b expert_with_model absent: NOT COMPUTABLE line names R_hum", "NOT COMPUTABLE for `expert_with_model`" in md and "R_hum is not reported" in md)
    check("5b model_alone still tabulated with CI withheld (2 records per task)", "| model_alone |" in md and "WITHHELD" in md and R["elicitation_ratio"]["model_alone"]["ci_withheld"])
    check("5b metadata files quoted, none NOT COLLECTED", "NOT COLLECTED" not in md and all(R["trial_metadata"][f]["present"] for f in az.TRIAL_META_FILES) and "compliance_definition = " in md)
    check("5b prereg thresholds drive section G and the report says so", R["use_adjusted_estimands"]["inputs"]["thresholds_source"] == "prereg.yaml" and "come from prereg.yaml" in md
          and any(t.get("name") == "prereg_diff" for t in (R["use_adjusted_estimands"].get("thresholds") or [])) if isinstance(R["use_adjusted_estimands"].get("thresholds"), list)
          else R["use_adjusted_estimands"]["inputs"]["thresholds_source"] == "prereg.yaml" and "come from prereg.yaml" in md)
    check("5b model_id-missing flag raised because ceiling records carry no model_id (arms.yaml does)", "model_id missing" in " | ".join(R["elicitation_ratio"]["model_alone"]["flags"]))
    check("5b md prints the Flags line and the provenance line (V57b-2)", "Flags for `model_alone`:" in md and "ceilings.jsonl provenance:" in md and "lack required fields" in md)
    # 5c (V57b-1, V57b-2): the unit derivation in main(). Every record is copied three times under DISTINCT participant_ids, so a
    # participant-based fallback would count 6 units per task and report a CI; the transcript-hash fallback collapses the copies.
    def dup(tmp, fn):
        recs = [json.loads(l) for l in open(tmp / "ceilings.jsonl") if l.strip()]
        with open(tmp / "ceilings.jsonl", "w") as fh:
            for rec in recs:
                for j in range(3):
                    r = dict(rec); r["participant_id"] = f"{rec['participant_id']}_copy{j}"; fn(r, j); fh.write(json.dumps(r) + "\n")
    R, md = run_copy("dup_nounit", lambda tmp: dup(tmp, lambda r, j: None))
    ma, ex = R["elicitation_ratio"]["model_alone"], R["elicitation_ratio"]["expert_with_model"]
    check("5c model_alone: 6 records per task but 2 distinct transcripts -> 2 units, CI withheld", ma["ci_withheld"] and set(ma["independent_units_per_task"].values()) == {2} and set(ma["ceiling_records_per_task"].values()) == {6})
    check("5c expert_with_model without elicitor_id: no unit, CI withheld with the elicitor reason", ex["ci_withheld"] and ex["records_without_unit"] == 18 and "elicitor_id missing" in ex["ci_withheld_reason"]
          and set(ex["independent_units_per_task"].values()) == {0} and "WITHHELD (elicitor_id missing on 18 record(s))" in md)
    check("5c the ratio itself is unchanged by duplication (mean over records)", abs(ma["ratio"] - 0.494) < 1e-9 and abs(ex["ratio"] - 0.53) < 1e-9)
    check("5c gap table status follows units: INSUFFICIENT with 6 records / 2 units, md says so", not ma["reference_adequacy"]["adequate"] and ma["reference_adequacy"]["min_independent_units_per_task"] == 2
          and "INSUFFICIENT (<3 independent units; min 2)" in md and "INSUFFICIENT (<3 independent units; min 0)" in md)
    check("5c adequacy note names the cause: repeated units for model_alone, unit-less records for expert_with_model (V57b round 3)",
          "repeat a unit" in ma["reference_adequacy"]["note"] and "repeat a unit" not in ex["reference_adequacy"]["note"] and "18 record(s) carry no unit" in ex["reference_adequacy"]["note"])
    def units(r, j):
        if r["ceiling"] == "expert" or r.get("kind") == "expert": r["elicitor_id"] = f"e{j}"
        else: r["seed"] = j   # seed 0 must count (V57b)
    R, md = run_copy("dup_units", lambda tmp: dup(tmp, units))
    ma, ex = R["elicitation_ratio"]["model_alone"], R["elicitation_ratio"]["expert_with_model"]
    check("5c model_alone with seeds 0,1,2 on the copies -> 3 units, CI reported", not ma["ci_withheld"] and set(ma["independent_units_per_task"].values()) == {3} and isinstance(ma["ratio_ci95"], list))
    check("5c expert_with_model with three elicitors -> 3 units, CI reported, participant-side key empty", not ex["ci_withheld"] and ex["records_without_unit"] == 0
          and set(ex["independent_units_per_task"].values()) == {3} and isinstance(ex["ratio_ci95"], list) and ex["ratio_ci95_participants_only_ceiling_fixed"] is None)
    check("5c with 3 units per task both gap rows are adequate in the md", ma["reference_adequacy"]["adequate"] and ex["reference_adequacy"]["adequate"] and "INSUFFICIENT" not in md)
    # (V57b round 3) unequal units across tasks: the minimum over tasks decides, not the maximum. Seeds 0,1,2 on every task except
    # the first sorted task_id, which keeps one seed -> min 1, max 3.
    def uneven(tmp):
        recs = [json.loads(l) for l in open(tmp / "ceilings.jsonl") if l.strip()]
        first = sorted({r["task_id"] for r in recs})[0]
        with open(tmp / "ceilings.jsonl", "w") as fh:
            for rec in recs:
                for j in range(3):
                    r = dict(rec); r["participant_id"] = f"{rec['participant_id']}_copy{j}"
                    if r.get("ceiling") == "expert" or r.get("kind") == "expert": r["elicitor_id"] = f"e{j}"
                    else: r["seed"] = 0 if r["task_id"] == first else j
                    fh.write(json.dumps(r) + "\n")
    R, md = run_copy("dup_uneven", uneven)
    ma = R["elicitation_ratio"]["model_alone"]; upt = ma["independent_units_per_task"]
    check("5c unequal units across tasks (1 on one task, 3 on the others): adequacy and CI follow the minimum", sorted(upt.values()) == [1, 3, 3] and ma["ci_withheld"]
          and not ma["reference_adequacy"]["adequate"] and ma["reference_adequacy"]["min_independent_units_per_task"] == 1 and "INSUFFICIENT (<3 independent units; min 1)" in md)
    R, md = run_copy("dup_oneelic", lambda tmp: dup(tmp, lambda r, j: r.update(elicitor_id="e_same") if r.get("ceiling") == "expert" else r.update(seed=7)))
    ma, ex = R["elicitation_ratio"]["model_alone"], R["elicitation_ratio"]["expert_with_model"]
    check("5c one elicitor / one seed on all copies -> 1 unit each, both CIs withheld", ma["ci_withheld"] and ex["ci_withheld"] and set(ma["independent_units_per_task"].values()) == {1} and set(ex["independent_units_per_task"].values()) == {1})
    # 5d (V57b-4): prereg.yaml thresholds, malformed and overridden
    def prereg(text):
        def f(tmp): (tmp / "prereg.yaml").write_text("estimands: [ITT]\n" + text)
        return f
    R, md = run_copy("pre_map", prereg("thresholds: {diff: 0.25}\n"))
    G = R["use_adjusted_estimands"]
    check("5d mapping-shaped thresholds: reported malformed, section G still ran", "error" not in G and G["inputs"]["thresholds_source"].startswith("none (prereg.yaml thresholds malformed") and "malformed" in md)
    R, md = run_copy("pre_str", prereg("thresholds:\n  - {name: t1, kind: diff, value: abc}\n"))
    G = R["use_adjusted_estimands"]
    check("5d non-numeric threshold value: reported malformed, section G still ran (was: whole section dropped)", "error" not in G and "malformed" in G["inputs"]["thresholds_source"] and "ValueError" in G["inputs"]["thresholds_source"])
    R, md = run_copy("pre_both", prereg("thresholds:\n  - {name: prereg_diff, kind: diff, value: 0.25}\n"), extra_args=["--threshold", "cli_diff:diff:0.1"])
    G = R["use_adjusted_estimands"]; names = [t.get("name") for t in (G.get("thresholds") or [])] if isinstance(G.get("thresholds"), list) else []
    check("5d command line overrides prereg and the report says so", G["inputs"]["thresholds_source"] == "command line (--threshold); prereg.yaml thresholds present but overridden"
          and "overrode them" in md and "no prereg.yaml thresholds were found" not in md and (names == ["cli_diff"] if names else True))
    R, md = run_copy("pre_kind", prereg("thresholds:\n  - {name: t1, kind: Ratio, value: '0.25'}\n"))
    check("5d kind 'Ratio' is malformed (ratio|diff only); footer sentence closes its parenthesis", "malformed" in R["use_adjusted_estimands"]["inputs"]["thresholds_source"]
          and "kind must be ratio or diff" in R["use_adjusted_estimands"]["inputs"]["thresholds_source"] and "kind must be ratio or diff), so no rule-out" in md)
    R, md = run_copy("pre_str_num", prereg("thresholds:\n  - {name: t1, kind: diff, value: '0.25'}\n"))
    check("5d numeric string value is accepted", R["use_adjusted_estimands"]["inputs"]["thresholds_source"] == "prereg.yaml")
    R, md = run_copy("pre_bad_cli", prereg("thresholds: {diff: 0.25}\n"), extra_args=["--threshold", "cli_diff:diff:0.1"])
    check("5d malformed prereg plus command line: the malformed pre-registration is named", "malformed" in R["use_adjusted_estimands"]["inputs"]["thresholds_source"]
          and R["use_adjusted_estimands"]["inputs"]["thresholds_source"].startswith("command line") and "they are malformed (TypeError" in md and "malformed ((" not in md and "no prereg.yaml thresholds were found" not in md)
    R, md = run_copy("pre_absent", lambda tmp: None)
    check("5d no prereg.yaml: footer says there is no prereg.yaml (not 'supplied none')", R["use_adjusted_estimands"]["inputs"]["thresholds_source"] == "none (no prereg.yaml)" and "there is no prereg.yaml" in md and "supplied none" not in md)
    # 5e (V57b-7): a record without task_id stops the run with the validator text, not a KeyError
    def drop_field(field):
        def f(tmp):
            recs = [json.loads(l) for l in open(tmp / "ceilings.jsonl") if l.strip()]; del recs[0][field]
            (tmp / "ceilings.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        return f
    for field in ["task_id", "participant_id"]:
        try: run_copy("no" + field, drop_field(field)); caught = None
        except SystemExit as ex: caught = str(ex)
        except KeyError as ex: caught = f"KeyError {ex}"
        check(f"5e missing {field}: SystemExit naming the record, not a bare KeyError", caught is not None and "lack task_id or participant_id" in caught and "record 0" in caught, caught or "")

check("constants pinned to trial/SCHEMA.md: MIN_TASK_COVERAGE 0.5, MIN_REF_RECORDS 3 (V57b-2)", az.MIN_TASK_COVERAGE == 0.5 and az.MIN_REF_RECORDS == 3)

print(); print("ALL PASS" if not fails else f"FAILURES ({len(fails)}): " + "; ".join(fails))
sys.exit(1 if fails else 0)
